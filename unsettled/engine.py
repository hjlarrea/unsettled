"""Authoritative base-game rules. No graphics or filesystem dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from collections import Counter
from copy import deepcopy
from math import sqrt, cos, sin, pi, atan2
import random
from typing import Any

RESOURCES = ("wood", "brick", "wheat", "sheep", "ore")
COSTS = {
    "road": {"wood": 1, "brick": 1},
    "settlement": {"wood": 1, "brick": 1, "wheat": 1, "sheep": 1},
    "city": {"wheat": 2, "ore": 3},
    "development": {"wheat": 1, "sheep": 1, "ore": 1},
}
DECK = ["knight"] * 14 + ["victory"] * 5 + ["roads"] * 2 + ["plenty"] * 2 + ["monopoly"] * 2


class RuleError(ValueError):
    """A rejected command, with a message suitable for the player."""


@dataclass
class Board:
    hexes: list[dict]
    vertices: list[tuple[float, float]]
    edges: list[tuple[int, int]]
    hex_vertices: list[list[int]]
    ports: dict[int, str]

    @classmethod
    def create(cls, seed: int, recommended: bool = False) -> Board:
        rng = random.Random(11 if recommended else seed)
        coords = [(q, r) for r in range(-2, 3) for q in range(-2, 3) if abs(q + r) <= 2]
        vertices, lookup, hex_vertices, edges = [], {}, [], set()
        for q, r in coords:
            center = (sqrt(3) * (q + r / 2), 1.5 * r)
            vs = []
            for i in range(6):
                angle = pi / 6 + i * pi / 3
                p = (round(center[0] + cos(angle), 5), round(center[1] + sin(angle), 5))
                if p not in lookup:
                    lookup[p] = len(vertices)
                    vertices.append(p)
                vs.append(lookup[p])
            hex_vertices.append(vs)
            edges.update(tuple(sorted((vs[i], vs[(i + 1) % 6]))) for i in range(6))
        terrain = ["wood"] * 4 + ["sheep"] * 4 + ["wheat"] * 4 + ["brick"] * 3 + ["ore"] * 3 + ["desert"]
        rng.shuffle(terrain)
        if recommended:
            # Official beginner layout, rows from top to bottom; fixed port positions below.
            terrain = ["ore", "sheep", "wood", "wheat", "brick", "sheep", "brick", "wheat", "wood", "desert", "wood", "ore", "wood", "ore", "wheat", "sheep", "brick", "wheat", "sheep"]
            numbers = [10, 2, 9, 12, 6, 4, 10, 9, 11, 0, 3, 8, 8, 3, 4, 5, 5, 6, 11]
        else:
            tokens = [2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]
            while True:
                rng.shuffle(tokens)
                it = iter(tokens)
                numbers = [0 if t == "desert" else next(it) for t in terrain]
                red = [i for i, n in enumerate(numbers) if n in (6, 8)]
                if all(len(set(hex_vertices[a]) & set(hex_vertices[b])) < 2 for a in red for b in red if a != b):
                    break
        hexes = [dict(q=q, r=r, resource=t, number=n) for (q, r), t, n in zip(coords, terrain, numbers)]
        edge_list = sorted(edges)
        counts = Counter(tuple(sorted((vs[i], vs[(i + 1) % 6]))) for vs in hex_vertices for i in range(6))
        coast = sorted((e for e in edge_list if counts[e] == 1), key=lambda e: atan2(sum(vertices[v][1] for v in e), sum(vertices[v][0] for v in e)))
        kinds = ["any", "wood", "any", "brick", "any", "wheat", "sheep", "any", "ore"]
        if not recommended:
            rng.shuffle(kinds)
        ports = {}
        for i, kind in zip((0, 3, 6, 10, 13, 16, 20, 23, 26), kinds):
            ports[edge_list.index(coast[i])] = kind
        return cls(hexes, vertices, edge_list, hex_vertices, ports)

    def adjacent(self, vertex: int) -> list[int]:
        return [b if a == vertex else a for a, b in self.edges if vertex in (a, b)]


@dataclass
class Player:
    name: str
    difficulty: str = "Standard"
    hand: dict[str, int] = field(default_factory=lambda: dict.fromkeys(RESOURCES, 0))
    cards: list[list[Any]] = field(default_factory=list)  # [kind, purchase turn]
    knights: int = 0


class Game:
    def __init__(self, bots: int = 3, seed: int = 1, recommended: bool = False, difficulties: list[str] | None = None):
        if bots not in (2, 3):
            raise RuleError("Choose two or three opponents.")
        self.seed = seed
        self.rng = random.Random(seed)
        self.board = Board.create(seed, recommended)
        self.players = [Player("You", "Human")] + [Player(n, (difficulties or ["Standard"] * bots)[i]) for i, n in enumerate(("Juniper", "Flint", "Marina")[:bots])]
        self.bank = dict.fromkeys(RESOURCES, 19)
        self.deck = DECK.copy()
        self.rng.shuffle(self.deck)
        self.buildings: dict[int, list[int]] = {}  # vertex -> [owner, size]
        self.roads: dict[int, int] = {}
        self.robber = next(i for i, h in enumerate(self.board.hexes) if h["resource"] == "desert")
        self.current = self.rng.randrange(len(self.players))
        order = [(self.current + i) % len(self.players) for i in range(len(self.players))]
        self.setup_order = order + order[::-1]
        self.setup_index = 0
        self.setup_vertex = None
        self.phase = "setup_settlement"
        self.turn = 0
        self.dice: list[int] = []
        self.played_card = False
        self.return_phase = "main"
        self.free_roads = 0
        self.discards: dict[int, int] = {}
        self.victims: list[int] = []
        self.trade: dict | None = None
        self.longest = None
        self.army = None
        self.winner = None
        self.log: list[str] = ["Welcome to Unsettled. Place two settlements and roads in snake order."]
        self.bot_memory: dict[str, dict] = {}

    def note(self, message: str):
        self.log.append(message)
        self.log = self.log[-200:]

    @property
    def actor(self) -> int:
        if self.phase == "discard":
            return next(iter(self.discards))
        if self.phase == "trade":
            return self.trade["target"]
        return self.current

    def pieces(self, player: int, size: int) -> int:
        return sum(p == player and s == size for p, s in self.buildings.values())

    def settlement_sites(self, player: int, setup: bool = False) -> list[int]:
        if self.pieces(player, 1) >= 5:
            return []
        return [v for v in range(len(self.board.vertices)) if v not in self.buildings
                and all(n not in self.buildings for n in self.board.adjacent(v))
                and (setup or any(owner == player and v in self.board.edges[e] for e, owner in self.roads.items()))]

    def road_sites(self, player: int, setup_vertex: int | None = None) -> list[int]:
        if sum(p == player for p in self.roads.values()) >= 15:
            return []
        result = []
        for i, edge in enumerate(self.board.edges):
            if i in self.roads:
                continue
            if setup_vertex is not None:
                if setup_vertex in edge:
                    result.append(i)
                continue
            for v in edge:
                if v in self.buildings:
                    if self.buildings[v][0] == player:
                        result.append(i)
                        break
                elif any(p == player and v in self.board.edges[e] for e, p in self.roads.items()):
                    result.append(i)
                    break
        return result

    def city_sites(self, player: int) -> list[int]:
        if self.pieces(player, 2) >= 4:
            return []
        return [v for v, b in self.buildings.items() if b == [player, 1]]

    def afford(self, player: int, kind: str) -> bool:
        return all(self.players[player].hand[r] >= n for r, n in COSTS[kind].items())

    def pay(self, player: int, kind: str):
        if not self.afford(player, kind):
            raise RuleError("You do not have the resources for that.")
        for r, n in COSTS[kind].items():
            self.players[player].hand[r] -= n
            self.bank[r] += n

    def ratio(self, player: int, resource: str) -> int:
        kinds = [kind for edge, kind in self.board.ports.items() if any(self.buildings.get(v, [-1])[0] == player for v in self.board.edges[edge])]
        return 2 if resource in kinds else 3 if "any" in kinds else 4

    def road_length(self, player: int) -> int:
        owned = {e for e, p in self.roads.items() if p == player}
        adjacency: dict[int, list[tuple[int, int]]] = {}
        for e in owned:
            a, b = self.board.edges[e]
            adjacency.setdefault(a, []).append((e, b))
            adjacency.setdefault(b, []).append((e, a))

        def walk(v, used):
            if used and v in self.buildings and self.buildings[v][0] != player:
                return len(used)
            return max([len(used)] + [walk(n, used | {e}) for e, n in adjacency.get(v, []) if e not in used])
        return max((walk(v, set()) for v in adjacency), default=0)

    def awards(self):
        for attr, values, minimum in (("longest", [self.road_length(p) for p in range(len(self.players))], 5), ("army", [p.knights for p in self.players], 3)):
            high = max(values)
            leaders = [i for i, v in enumerate(values) if v == high and v >= minimum]
            old = getattr(self, attr)
            new = leaders[0] if len(leaders) == 1 else old if old in leaders else None
            setattr(self, attr, new)
            if new != old:
                label = "Longest Road" if attr == "longest" else "Largest Army"
                self.note(f"{self.players[new].name} takes {label}." if new is not None else f"{label} is unclaimed.")

    def points(self, player: int, private: bool = False) -> int:
        return (sum(s for p, s in self.buildings.values() if p == player)
                + 2 * (self.longest == player) + 2 * (self.army == player)
                + (sum(c == "victory" for c, _ in self.players[player].cards) if private else 0))

    def check_win(self):
        if not self.phase.startswith("setup") and self.points(self.current, True) >= 10:
            self.winner = self.current
            self.phase = "game_over"
            self.note(f"{self.players[self.current].name} wins with {self.points(self.current, True)} points!")

    def command(self, player: int, action: str, **data):
        """Validate a complete command before applying it. Rejections leave state untouched."""
        if self.phase == "game_over":
            raise RuleError("This game has finished.")
        if player != self.actor:
            raise RuleError("Wait for your turn.")
        method = getattr(self, "_" + action, None)
        if action not in ("settlement", "road", "city", "roll", "end", "buy", "play", "discard", "robber", "steal", "bank_trade", "offer", "respond", "choose", "skip_roads") or method is None:
            raise RuleError("Unknown action.")
        method(player, **data)
        self.check_win()

    def require(self, *phases):
        if self.phase not in phases:
            raise RuleError("Finish the current decision first.")

    def _settlement(self, p, vertex):
        self.require("setup_settlement", "main")
        setup = self.phase == "setup_settlement"
        if vertex not in self.settlement_sites(p, setup):
            raise RuleError("A settlement cannot be placed there.")
        if not setup:
            self.pay(p, "settlement")
        self.buildings[vertex] = [p, 1]
        self.note(f"{self.players[p].name} builds a settlement.")
        if setup:
            self.setup_vertex = vertex
            self.phase = "setup_road"
            if self.setup_index >= len(self.players):
                for i, vs in enumerate(self.board.hex_vertices):
                    r = self.board.hexes[i]["resource"]
                    if vertex in vs and r != "desert" and self.bank[r]:
                        self.bank[r] -= 1
                        self.players[p].hand[r] += 1
        else:
            self.awards()

    def _road(self, p, edge):
        self.require("setup_road", "main", "road_building")
        setup = self.phase == "setup_road"
        if edge not in self.road_sites(p, self.setup_vertex if setup else None):
            raise RuleError("A road cannot be placed there.")
        if self.phase == "main":
            self.pay(p, "road")
        self.roads[edge] = p
        self.note(f"{self.players[p].name} builds a road.")
        if setup:
            self.setup_index += 1
            if self.setup_index == len(self.setup_order):
                self.current = self.setup_order[0]
                self.phase = "roll"
                self.note("Setup complete. Roll the dice to begin.")
            else:
                self.current = self.setup_order[self.setup_index]
                self.phase = "setup_settlement"
        elif self.phase == "road_building":
            self.free_roads -= 1
            if not self.free_roads or not self.road_sites(p):
                self.phase = self.return_phase
        self.awards()

    def _skip_roads(self, p):
        self.require("road_building")
        self.free_roads = 0
        self.phase = self.return_phase

    def _city(self, p, vertex):
        self.require("main")
        if vertex not in self.city_sites(p):
            raise RuleError("Choose one of your settlements to upgrade.")
        self.pay(p, "city")
        self.buildings[vertex] = [p, 2]
        self.note(f"{self.players[p].name} builds a city.")

    def _roll(self, p):
        self.require("roll")
        self.dice = [self.rng.randint(1, 6), self.rng.randint(1, 6)]
        total = sum(self.dice)
        self.note(f"{self.players[p].name} rolls {total} ({self.dice[0]} + {self.dice[1]}).")
        if total == 7:
            self.discards = {i: sum(pl.hand.values()) // 2 for i, pl in enumerate(self.players) if sum(pl.hand.values()) > 7}
            self.phase = "discard" if self.discards else "robber"
            self.return_phase = "main"
            return
        gains = [Counter() for _ in self.players]
        for h, vs in enumerate(self.board.hex_vertices):
            tile = self.board.hexes[h]
            if tile["number"] == total and h != self.robber:
                for v in vs:
                    if v in self.buildings:
                        owner, size = self.buildings[v]
                        gains[owner][tile["resource"]] += size
        for r in RESOURCES:
            recipients = [i for i, g in enumerate(gains) if g[r]]
            needed = sum(g[r] for g in gains)
            if needed > self.bank[r] and len(recipients) > 1:
                self.note(f"The bank cannot supply {r}; no {r} is distributed.")
                continue
            for i in recipients:
                count = min(gains[i][r], self.bank[r])
                self.players[i].hand[r] += count
                self.bank[r] -= count
        self.phase = "main"

    def _discard(self, p, resources):
        self.require("discard")
        self.validate_bundle(resources)
        if sum(resources.values()) != self.discards[p] or any(n > self.players[p].hand[r] for r, n in resources.items()):
            raise RuleError(f"Choose exactly {self.discards[p]} cards from your hand.")
        for r, n in resources.items():
            self.players[p].hand[r] -= n
            self.bank[r] += n
        self.note(f"{self.players[p].name} discards {self.discards[p]} resources.")
        del self.discards[p]
        if not self.discards:
            self.phase = "robber"

    def _robber(self, p, hex):
        self.require("robber")
        if type(hex) is not int or not 0 <= hex < 19 or hex == self.robber:
            raise RuleError("Move the robber to a different hex.")
        self.robber = hex
        self.victims = sorted({self.buildings[v][0] for v in self.board.hex_vertices[hex] if v in self.buildings and self.buildings[v][0] != p and sum(self.players[self.buildings[v][0]].hand.values())})
        self.note(f"{self.players[p].name} moves the robber.")
        self.phase = "victim" if self.victims else self.return_phase

    def _steal(self, p, victim):
        self.require("victim")
        if victim not in self.victims:
            raise RuleError("Choose an eligible neighboring opponent.")
        hand = self.players[victim].hand
        cards = [r for r, n in hand.items() for _ in range(n)]
        r = self.rng.choice(cards)
        hand[r] -= 1
        self.players[p].hand[r] += 1
        # Resource identity is private; do not leak it through the public log.
        self.note(f"{self.players[p].name} steals one resource from {self.players[victim].name}.")
        self.victims = []
        self.phase = self.return_phase

    def _end(self, p):
        self.require("main")
        self.current = (p + 1) % len(self.players)
        self.turn += 1
        self.phase = "roll"
        self.played_card = False
        self.note(f"{self.players[self.current].name}'s turn.")

    def _buy(self, p):
        self.require("main")
        if not self.deck:
            raise RuleError("The development deck is empty.")
        self.pay(p, "development")
        self.players[p].cards.append([self.deck.pop(), self.turn])
        self.note(f"{self.players[p].name} buys a development card.")

    def playable(self, p):
        return sorted({c for c, bought in self.players[p].cards if c != "victory" and bought < self.turn}) if not self.played_card else []

    def _play(self, p, card):
        self.require("roll", "main")
        if card not in self.playable(p):
            raise RuleError("Play one development card per turn, starting the turn after purchase.")
        if card == "plenty" and not sum(self.bank.values()):
            raise RuleError("The bank has no resources for Year of Plenty.")
        if card == "roads" and not self.road_sites(p):
            raise RuleError("No road placement is available.")
        idx = next(i for i, (c, t) in enumerate(self.players[p].cards) if c == card and t < self.turn)
        self.players[p].cards.pop(idx)
        self.played_card = True
        self.return_phase = self.phase
        self.note(f"{self.players[p].name} plays {dict(knight='Knight', roads='Road Building', plenty='Year of Plenty', monopoly='Monopoly')[card]}.")
        if card == "knight":
            self.players[p].knights += 1
            self.phase = "robber"
            self.awards()
        elif card == "roads":
            self.free_roads = 2
            self.phase = "road_building"
        else:
            self.phase = card

    def _choose(self, p, resources):
        self.require("plenty", "monopoly")
        self.validate_bundle(resources)
        if self.phase == "plenty":
            if sum(resources.values()) != min(2, sum(self.bank.values())) or any(n > self.bank[r] for r, n in resources.items()):
                raise RuleError("Choose two available bank resources (or the last one if only one remains).")
            for r, n in resources.items():
                self.bank[r] -= n
                self.players[p].hand[r] += n
        else:
            selected = [r for r, n in resources.items() if n]
            if len(selected) != 1 or resources[selected[0]] != 1:
                raise RuleError("Choose one resource type.")
            r = selected[0]
            for i, player in enumerate(self.players):
                if i != p:
                    self.players[p].hand[r] += player.hand[r]
                    player.hand[r] = 0
        self.phase = self.return_phase

    @staticmethod
    def validate_bundle(resources):
        if not isinstance(resources, dict) or any(r not in RESOURCES or type(n) is not int or n < 0 for r, n in resources.items()):
            raise RuleError("Resource amounts must be nonnegative whole numbers.")

    def _bank_trade(self, p, give, receive):
        self.require("main")
        if give not in RESOURCES or receive not in RESOURCES or give == receive:
            raise RuleError("Choose two different resources.")
        ratio = self.ratio(p, give)
        if self.players[p].hand[give] < ratio or self.bank[receive] < 1:
            raise RuleError("That bank trade is not available.")
        self.players[p].hand[give] -= ratio
        self.bank[give] += ratio
        self.players[p].hand[receive] += 1
        self.bank[receive] -= 1
        self.note(f"{self.players[p].name} trades {ratio} {give} for 1 {receive} with the bank.")

    def _offer(self, p, target, give, want):
        self.require("main")
        self.validate_bundle(give)
        self.validate_bundle(want)
        give, want = {r: n for r, n in give.items() if n}, {r: n for r, n in want.items() if n}
        if type(target) is not int or target == p or not 0 <= target < len(self.players):
            raise RuleError("Choose another player.")
        if not give or not want or set(give) & set(want):
            raise RuleError("Both sides must exchange different resources.")
        if any(self.players[p].hand[r] < n for r, n in give.items()):
            raise RuleError("You cannot offer resources you do not have.")
        self.trade = dict(owner=p, target=target, give=give, want=want, countered=False)
        self.phase = "trade"
        self.note(f"{self.players[p].name} offers a trade to {self.players[target].name}.")

    def _respond(self, p, accept=False, counter=None):
        self.require("trade")
        t = self.trade
        if counter is not None:
            if t["countered"]:
                raise RuleError("Only one counteroffer per negotiation.")
            give, want = counter.get("give", {}), counter.get("want", {})
            self.validate_bundle(give)
            self.validate_bundle(want)
            give = {r: n for r, n in give.items() if n}
            want = {r: n for r, n in want.items() if n}
            if not give or not want or set(give) & set(want) or any(self.players[p].hand[r] < n for r, n in give.items()):
                raise RuleError("Choose a valid counteroffer from your hand.")
            self.trade = dict(owner=p, target=t["owner"], give=give, want=want, countered=True)
            self.note(f"{self.players[p].name} makes a counteroffer.")
            return
        if accept:
            if any(self.players[t["owner"]].hand[r] < n for r, n in t["give"].items()) or any(self.players[p].hand[r] < n for r, n in t["want"].items()):
                raise RuleError("The offered resources are not available.")
            for r, n in t["give"].items():
                self.players[t["owner"]].hand[r] -= n
                self.players[p].hand[r] += n
            for r, n in t["want"].items():
                self.players[p].hand[r] -= n
                self.players[t["owner"]].hand[r] += n
            self.note("Trade accepted.")
        else:
            self.note(f"{self.players[p].name} declines the trade.")
        self.trade = None
        self.phase = "main"

    def observation(self, p: int) -> dict:
        """A bot-facing snapshot, deliberately excluding opponents' private state and RNG."""
        return dict(player=p, current=self.current, phase=self.phase, turn=self.turn,
                    board=asdict(self.board), buildings={v: b.copy() for v, b in self.buildings.items()}, roads=self.roads.copy(), robber=self.robber,
                    hand=self.players[p].hand.copy(), cards=[c.copy() for c in self.players[p].cards],
                    players=[dict(name=pl.name, count=sum(pl.hand.values()), cards=len(pl.cards), points=self.points(i), knights=pl.knights) for i, pl in enumerate(self.players)],
                    bank=self.bank.copy(), deck_count=len(self.deck), playable=self.playable(p),
                    settlements=self.settlement_sites(p, self.phase == "setup_settlement"),
                    road_sites=self.road_sites(p, self.setup_vertex if self.phase == "setup_road" else None),
                    cities=self.city_sites(p), ratios={r: self.ratio(p, r) for r in RESOURCES},
                    discard=self.discards.get(p, 0), victims=self.victims.copy(),
                    trade=None if self.trade is None else {**self.trade, "give": self.trade["give"].copy(), "want": self.trade["want"].copy()},
                    longest=self.longest, army=self.army)

    def to_dict(self):
        state = {k: v for k, v in self.__dict__.items() if k not in ("rng", "board", "players")}
        return dict(version=1, state=deepcopy(state), board=asdict(self.board), players=[asdict(p) for p in self.players], rng=self.rng.getstate())

    @classmethod
    def from_dict(cls, data):
        if data.get("version") != 1:
            raise ValueError("This save version is not supported.")
        expected = {"seed", "bank", "deck", "buildings", "roads", "robber", "current", "setup_order", "setup_index", "setup_vertex", "phase", "turn", "dice", "played_card", "return_phase", "free_roads", "discards", "victims", "trade", "longest", "army", "winner", "log", "bot_memory"}
        if not isinstance(data.get("state"), dict) or set(data["state"]) != expected:
            raise ValueError("Invalid save fields.")
        game = cls.__new__(cls)
        game.__dict__.update(data["state"])
        board = data["board"]
        game.board = Board(board["hexes"], [tuple(v) for v in board["vertices"]], [tuple(e) for e in board["edges"]], board["hex_vertices"], {int(k): v for k, v in board["ports"].items()})
        game.players = [Player(**p) for p in data["players"]]
        for key in ("buildings", "roads", "discards"):
            setattr(game, key, {int(k): v for k, v in getattr(game, key).items()})
        def tuples(x):
            return tuple(tuples(v) for v in x) if isinstance(x, (list, tuple)) else x
        game.rng = random.Random()
        game.rng.setstate(tuples(data["rng"]))
        game.validate()
        return game

    def validate(self):
        """Reject damaged saves before they can become the active game."""
        n = len(self.players)
        if any(type(v) is not int for v in (self.current, self.turn, self.seed, self.robber, self.setup_index, self.free_roads)):
            raise ValueError("Invalid numeric game state.")
        if not isinstance(self.log, list) or len(self.log) > 200 or any(not isinstance(v, str) or len(v) > 2000 for v in self.log):
            raise ValueError("Invalid journal.")
        if not isinstance(self.bot_memory, dict) or any(not isinstance(k, str) or not isinstance(v, dict) for k, v in self.bot_memory.items()):
            raise ValueError("Invalid bot memory.")
        for memory in self.bot_memory.values():
            if memory and (set(memory) != {"turn", "offers", "bank_trades", "declined"} or not isinstance(memory["turn"], str) or any(type(memory[k]) is not int or memory[k] < 0 for k in ("offers", "bank_trades")) or not isinstance(memory["declined"], list) or any(type(v) is not int or v not in range(n) for v in memory["declined"])):
                raise ValueError("Invalid bot planning state.")
        if any(not isinstance(p.name, str) or len(p.name) > 80 or p.difficulty not in ("Human", "Easy", "Standard") or type(p.knights) is not int or p.knights < 0 for p in self.players):
            raise ValueError("Invalid player settings.")
        if not isinstance(self.dice, list) or len(self.dice) not in (0, 2) or any(type(v) is not int or v not in range(1, 7) for v in self.dice):
            raise ValueError("Invalid dice.")
        phases = {"setup_settlement", "setup_road", "roll", "main", "discard", "robber", "victim", "road_building", "plenty", "monopoly", "trade", "game_over"}
        if n not in (3, 4) or self.phase not in phases or not 0 <= self.current < n:
            raise ValueError("Invalid player or turn state.")
        if len(self.board.hexes) != 19 or len(self.board.vertices) != 54 or len(self.board.edges) != 72:
            raise ValueError("Invalid board geometry.")
        expected_board = Board.create(self.seed)
        if self.board.vertices != expected_board.vertices or self.board.edges != expected_board.edges or self.board.hex_vertices != expected_board.hex_vertices:
            raise ValueError("Invalid board connectivity.")
        if Counter(h["resource"] for h in self.board.hexes) != dict(wood=4, sheep=4, wheat=4, brick=3, ore=3, desert=1):
            raise ValueError("Invalid terrain distribution.")
        for h, expected in zip(self.board.hexes, expected_board.hexes):
            if (h["q"], h["r"]) != (expected["q"], expected["r"]) or type(h["number"]) is not int or (h["number"] == 0) != (h["resource"] == "desert"):
                raise ValueError("Invalid terrain or number token.")
        if Counter(h["number"] for h in self.board.hexes) != Counter([0, 2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12]):
            raise ValueError("Invalid number token distribution.")
        if len(self.board.ports) != 9 or Counter(self.board.ports.values()) != Counter(["any"] * 4 + list(RESOURCES)) or set(self.board.ports) != set(expected_board.ports):
            raise ValueError("Invalid harbors.")
        for hand in [self.bank] + [p.hand for p in self.players]:
            if set(hand) != set(RESOURCES) or any(type(v) is not int or v < 0 for v in hand.values()):
                raise ValueError("Invalid resource counts.")
        if any(self.bank[r] + sum(p.hand[r] for p in self.players) != 19 for r in RESOURCES):
            raise ValueError("Resource totals are inconsistent.")
        if any(not 0 <= v < 54 or len(b) != 2 or b[0] not in range(n) or b[1] not in (1, 2) for v, b in self.buildings.items()):
            raise ValueError("Invalid buildings.")
        if any(e not in range(72) or p not in range(n) for e, p in self.roads.items()):
            raise ValueError("Invalid roads.")
        if not 0 <= self.robber < 19 or self.turn < 0:
            raise ValueError("Invalid robber or turn.")
        if any(self.pieces(p, 1) > 5 or self.pieces(p, 2) > 4 or sum(owner == p for owner in self.roads.values()) > 15 for p in range(n)):
            raise ValueError("Invalid piece supply.")
        if any(len(c) != 2 or c[0] not in DECK or type(c[1]) is not int or not 0 <= c[1] <= self.turn for p in self.players for c in p.cards):
            raise ValueError("Invalid development card state.")
        if any(v is not None and (type(v) is not int or v not in range(n)) for v in (self.longest, self.army, self.winner)):
            raise ValueError("Invalid award holder.")
        cards = self.deck + [c for p in self.players for c, _ in p.cards]
        if any(c not in DECK for c in cards) or any(Counter(cards)[c] > Counter(DECK)[c] for c in set(cards)):
            raise ValueError("Invalid development cards.")
        if self.phase == "discard" and (not self.discards or any(p not in range(n) or type(k) is not int or k <= 0 or k > sum(self.players[p].hand.values()) for p, k in self.discards.items())):
            raise ValueError("Invalid discard decision.")
        if self.phase == "victim" and (not self.victims or any(v not in range(n) or v == self.current or not sum(self.players[v].hand.values()) for v in self.victims)):
            raise ValueError("Invalid theft decision.")
        if self.phase == "trade":
            t = self.trade
            if not isinstance(t, dict) or t["owner"] not in range(n) or t["target"] not in range(n) or t["owner"] == t["target"] or self.current not in (t["owner"], t["target"]):
                raise ValueError("Invalid trade decision.")
            self.validate_bundle(t["give"])
            self.validate_bundle(t["want"])
            if not t["give"] or not t["want"] or not sum(t["give"].values()) or not sum(t["want"].values()) or set(t["give"]) & set(t["want"]) or type(t["countered"]) is not bool or any(self.players[t["owner"]].hand[r] < amount for r, amount in t["give"].items()):
                raise ValueError("Invalid trade resources.")
        if sorted(self.setup_order[:n]) != list(range(n)) or self.setup_order[n:] != self.setup_order[:n][::-1]:
            raise ValueError("Invalid setup order.")
        if self.phase == "setup_road" and self.buildings.get(self.setup_vertex) != [self.current, 1]:
            raise ValueError("Invalid initial road decision.")
        if self.phase.startswith("setup") and (not 0 <= self.setup_index < n * 2 or self.setup_order[self.setup_index] != self.current):
            raise ValueError("Invalid setup decision.")
        if self.phase == "road_building" and self.free_roads not in (1, 2):
            raise ValueError("Invalid road-building decision.")
        if self.phase in ("robber", "victim", "plenty", "monopoly", "road_building") and self.return_phase not in ("roll", "main"):
            raise ValueError("Invalid return phase.")
        if self.phase == "game_over" and (self.winner not in range(n) or self.points(self.winner, True) < 10):
            raise ValueError("Invalid winner.")
