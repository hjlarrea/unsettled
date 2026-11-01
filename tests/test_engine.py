from collections import Counter
import copy
import json
import random
import pytest
from unsettled.engine import Game, Board, RuleError, RESOURCES, DECK
from unsettled import bots, persistence
from unsettled.simulation import play


def main_game():
    g = Game(seed=4)
    g.phase = "main"
    g.current = 0
    g.turn = 10
    return g


def give(g, p, **resources):
    for r, n in resources.items():
        g.bank[r] -= n
        g.players[p].hand[r] += n


def card(g, kind, bought=0):
    g.deck.remove(kind)
    g.players[0].cards.append([kind, bought])


def chain(g, length, start=0):
    def find(v, used, vertices):
        if len(used) == length:
            return used, vertices
        for e, (a, b) in enumerate(g.board.edges):
            if v in (a, b) and e not in used:
                n = b if a == v else a
                if n not in vertices:
                    result = find(n, used + [e], vertices + [n])
                    if result:
                        return result
    return find(start, [], [start])


def test_board_geometry_and_random_boards():
    for seed in range(20):
        b = Board.create(seed)
        assert (len(b.hexes), len(b.vertices), len(b.edges), len(b.ports)) == (19, 54, 72, 9)
        assert Counter(h["resource"] for h in b.hexes) == dict(wood=4, sheep=4, wheat=4, brick=3, ore=3, desert=1)
        red = [i for i, h in enumerate(b.hexes) if h["number"] in (6, 8)]
        assert all(len(set(b.hex_vertices[a]) & set(b.hex_vertices[c])) < 2 for a in red for c in red if a != c)
        port_vertices = [v for e in b.ports for v in b.edges[e]]
        assert len(set(port_vertices)) == 18


def test_setup_snake_and_initial_resources():
    g = Game(bots=2, seed=7)
    order, second = [], []
    while g.phase.startswith("setup"):
        p = g.actor
        if g.phase == "setup_settlement":
            order.append(p)
            v = max(g.settlement_sites(p, True), key=lambda v: len([i for i, vs in enumerate(g.board.hex_vertices) if v in vs and g.board.hexes[i]["number"]]))
            if g.setup_index >= len(g.players):
                second.append((p, v))
            g.command(p, "settlement", vertex=v)
        else:
            g.command(p, "road", edge=g.road_sites(p, g.setup_vertex)[0])
    assert order == g.setup_order
    assert g.phase == "roll"
    assert g.current == order[0]
    for p, v in second:
        expected = Counter(g.board.hexes[i]["resource"] for i, vs in enumerate(g.board.hex_vertices) if v in vs and g.board.hexes[i]["number"])
        assert Counter({r: n for r, n in g.players[p].hand.items() if n}) == expected
    g.validate()


def test_rejected_command_does_not_mutate():
    g = main_game()
    before = copy.deepcopy(g.to_dict())
    with pytest.raises(RuleError):
        g.command(0, "settlement", vertex=0)
    assert g.to_dict() == before
    with pytest.raises(RuleError):
        g.command(1, "end")
    assert g.to_dict() == before


def test_distance_connectivity_and_enemy_block():
    g = main_game()
    edges, vs = chain(g, 5)
    g.roads[edges[0]] = 0
    assert edges[1] in g.road_sites(0)
    g.buildings[vs[1]] = [1, 1]
    assert edges[1] not in g.road_sites(0)
    assert vs[0] not in g.settlement_sites(0)
    g.buildings.clear()
    assert vs[0] in g.settlement_sites(0)
    g.buildings[vs[0]] = [0, 1]
    assert vs[1] not in g.settlement_sites(0, True)


def test_piece_limits_and_city_returns_settlement():
    g = main_game()
    g.buildings = {v: [0, 1] for v in range(5)}
    assert g.settlement_sites(0, True) == []
    give(g, 0, wheat=2, ore=3)
    g.command(0, "city", vertex=0)
    assert g.pieces(0, 1) == 4
    assert g.pieces(0, 2) == 1
    g.buildings = {v: [0, 2] for v in range(4)} | {4: [0, 1]}
    assert g.city_sites(0) == []
    g.roads = {e: 0 for e in range(15)}
    assert g.road_sites(0) == []


def force_roll(g, total):
    for seed in range(10000):
        rng = random.Random(seed)
        if rng.randint(1, 6) + rng.randint(1, 6) == total:
            g.rng = random.Random(seed)
            break
    g.phase = "roll"
    g.command(0, "roll")


def test_production_city_robber_and_bank_shortage():
    g = main_game()
    h = next(i for i, h in enumerate(g.board.hexes) if h["number"])
    tile = g.board.hexes[h]
    v = g.board.hex_vertices[h][0]
    r = tile["resource"]
    g.buildings[v] = [0, 2]
    force_roll(g, tile["number"])
    assert g.players[0].hand[r] >= 2
    g = main_game()
    g.buildings[v] = [0, 2]
    g.robber = h
    force_roll(g, tile["number"])
    # Only assert blocked tile; isolate any same-number neighbor.
    expected = sum(2 for i, vs in enumerate(g.board.hex_vertices) if v in vs and i != h and g.board.hexes[i]["resource"] == r and g.board.hexes[i]["number"] == tile["number"])
    assert g.players[0].hand[r] == expected
    g = main_game()
    g.buildings[v] = [0, 2]
    give(g, 2, **{r: 18})
    force_roll(g, tile["number"])
    assert g.players[0].hand[r] == 1  # One recipient gets remaining supply.
    g = main_game()
    g.buildings[v] = [0, 2]
    g.buildings[g.board.hex_vertices[h][2]] = [1, 1]
    give(g, 2, **{r: 18})
    force_roll(g, tile["number"])
    assert g.players[0].hand[r] == g.players[1].hand[r] == 0


def test_seven_discards_and_robber_theft_privacy():
    g = main_game()
    give(g, 0, wood=9)
    give(g, 1, brick=8)
    force_roll(g, 7)
    assert g.discards == {0: 4, 1: 4}
    before = copy.deepcopy(g.to_dict())
    with pytest.raises(RuleError):
        g.command(0, "discard", resources={"wood": 3})
    assert g.to_dict() == before
    g.command(0, "discard", resources={"wood": 4})
    g.command(1, "discard", resources={"brick": 4})
    assert g.phase == "robber"
    h = (g.robber + 1) % 19
    g.buildings[g.board.hex_vertices[h][0]] = [1, 1]
    g.command(0, "robber", hex=h)
    assert g.victims == [1]
    g.command(0, "steal", victim=1)
    assert g.players[0].hand["brick"] == 1
    assert "brick" not in g.log[-1]
    assert g.phase == "main"


def test_ports_bank_trade_and_trade_counter():
    g = main_game()
    edge = next(e for e, r in g.board.ports.items() if r == "wood")
    g.buildings[g.board.edges[edge][0]] = [0, 1]
    assert g.ratio(0, "wood") == 2
    give(g, 0, wood=4)
    g.command(0, "bank_trade", give="wood", receive="ore")
    assert g.players[0].hand["ore"] == 1
    give(g, 1, sheep=2)
    g.command(0, "offer", target=1, give={"wood": 1}, want={"sheep": 1})
    g.command(1, "respond", counter={"give": {"sheep": 1}, "want": {"wood": 2}})
    assert g.actor == 0
    g.command(0, "respond", accept=True)
    assert g.players[0].hand["sheep"] == 1
    assert g.players[1].hand["wood"] == 2
    assert g.phase == "main"
    g.validate()


def test_development_timing_and_plenty():
    g = main_game()
    card(g, "plenty", g.turn)
    before = copy.deepcopy(g.to_dict())
    with pytest.raises(RuleError):
        g.command(0, "play", card="plenty")
    assert g.to_dict() == before
    g.turn += 1
    g.phase = "roll"
    g.command(0, "play", card="plenty")
    g.command(0, "choose", resources={"ore": 2})
    assert g.phase == "roll"
    assert g.players[0].hand["ore"] == 2
    card(g, "knight")
    with pytest.raises(RuleError):
        g.command(0, "play", card="knight")


def test_monopoly_and_road_building():
    g = main_game()
    give(g, 1, wood=4)
    give(g, 2, wood=3)
    card(g, "monopoly")
    g.command(0, "play", card="monopoly")
    g.command(0, "choose", resources={"wood": 1})
    assert g.players[0].hand["wood"] == 7
    assert g.players[1].hand["wood"] == 0
    g.played_card = False
    card(g, "roads")
    g.buildings[0] = [0, 1]
    g.command(0, "play", card="roads")
    for _ in range(2):
        g.command(0, "road", edge=g.road_sites(0)[0])
    assert g.phase == "main"
    assert len(g.roads) == 2
    assert g.players[0].hand["wood"] == 7


def test_longest_road_blocks_ties_cycles_and_branches():
    g = main_game()
    edges, vs = chain(g, 6)
    g.roads = dict.fromkeys(edges, 0)
    assert g.road_length(0) == 6
    g.awards()
    assert g.longest == 0
    g.buildings[vs[3]] = [1, 1]
    assert g.road_length(0) == 3
    g.awards()
    assert g.longest is None
    g = main_game()
    vs = g.board.hex_vertices[9]
    ring = [g.board.edges.index(tuple(sorted((vs[i], vs[(i + 1) % 6])))) for i in range(6)]
    g.roads = dict.fromkeys(ring, 0)
    assert g.road_length(0) == 6
    branch = next(e for e, edge in enumerate(g.board.edges) if vs[0] in edge and e not in ring)
    g.roads[branch] = 0
    assert g.road_length(0) == 7
    # Two disjoint five-edge networks retain the incumbent on a tie.
    g = main_game()
    e0, _ = chain(g, 5)
    g.roads = dict.fromkeys(e0, 0)
    g.awards()
    for start in range(53, -1, -1):
        found = chain(g, 5, start)
        if found and not set(found[0]) & set(e0):
            g.roads.update(dict.fromkeys(found[0], 1))
            break
    g.awards()
    assert g.longest == 0
    g.longest = None
    g.awards()
    assert g.longest is None


def test_largest_army_and_hidden_victory_on_own_turn():
    g = main_game()
    g.players[1].knights = 3
    g.awards()
    assert g.army == 1
    g.players[0].knights = 3
    g.awards()
    assert g.army == 1
    g.players[0].knights = 4
    g.awards()
    assert g.army == 0
    g = main_game()
    g.buildings = {i: [1, 2] for i in range(4)}
    for _ in range(2):
        g.deck.remove("victory")
        g.players[1].cards.append(["victory", 0])
    assert g.points(1) == 8
    assert g.points(1, True) == 10
    g.check_win()
    assert g.winner is None
    g.command(0, "end")
    assert g.winner == 1


@pytest.mark.parametrize("phase", ["setup_settlement", "setup_road", "roll", "main", "discard", "robber", "victim", "plenty", "monopoly", "road_building", "trade"])
def test_save_roundtrip_pending_choices(tmp_path, phase):
    g = Game(seed=8) if phase.startswith("setup") else main_game()
    if phase == "setup_road":
        g.command(g.actor, "settlement", vertex=g.settlement_sites(g.actor, True)[0])
    elif phase == "discard":
        give(g, 0, wood=8)
        force_roll(g, 7)
    elif phase == "victim":
        g.phase = "robber"
        h = (g.robber + 1) % 19
        g.buildings[g.board.hex_vertices[h][0]] = [1, 1]
        give(g, 1, wood=1)
        g.command(0, "robber", hex=h)
    elif phase in ("plenty", "monopoly", "road_building"):
        g.buildings[0] = [0, 1]
        card(g, "roads" if phase == "road_building" else phase)
        g.command(0, "play", card="roads" if phase == "road_building" else phase)
    elif phase == "trade":
        give(g, 0, wood=1)
        g.command(0, "offer", target=1, give={"wood": 1}, want={"ore": 1})
    else:
        g.phase = phase
    path = tmp_path / "save.json"
    persistence.save(g, path)
    loaded = persistence.load(path)
    assert json.dumps(loaded.to_dict(), sort_keys=True) == json.dumps(g.to_dict(), sort_keys=True)
    assert [loaded.rng.randint(1, 6) for _ in range(20)] == [g.rng.randint(1, 6) for _ in range(20)]


def test_save_rejects_damage_and_preserves_old_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "save.json"
    g = main_game()
    persistence.save(g, path)
    previous = path.read_bytes()
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(persistence.os, "replace", fail)
    with pytest.raises(OSError):
        persistence.save(g, path)
    assert path.read_bytes() == previous
    damaged = g.to_dict()
    damaged["state"]["bank"]["wood"] = -1
    path.write_text(json.dumps(damaged))
    with pytest.raises(RuleError, match="Cannot load save"):
        persistence.load(path)
    path.write_text('{"version":99}')
    with pytest.raises(RuleError, match="version"):
        persistence.load(path)


def test_observations_and_decisions_do_not_leak_hidden_information():
    g = main_game()
    give(g, 0, wood=2)
    give(g, 1, ore=2)
    g.players[1].cards.append(["knight", 0])
    first = g.observation(0)
    g.players[1].hand["ore"] = 0
    g.players[1].hand["wheat"] = 2
    g.players[1].cards = [["victory", 0]]
    g.deck.reverse()
    assert g.observation(0) == first
    assert bots.decision(first, "Standard", {}) == bots.decision(g.observation(0), "Standard", {})
    first["hand"]["wood"] = 99
    assert g.players[0].hand["wood"] == 2


@pytest.mark.parametrize("seed,bots_count", [(1, 2), (2, 2), (1, 3), (4, 3)])
def test_complete_games(seed, bots_count):
    g, commands = play(seed, bots_count)
    assert g.winner is not None
    assert g.points(g.winner, True) >= 10
    assert commands < 16000
    g.validate()


def test_year_of_plenty_last_card_in_bank():
    g = main_game()
    for r in RESOURCES:
        give(g, 1, **{r: 18 if r == "ore" else 19})
    card(g, "plenty")
    g.command(0, "play", card="plenty")
    g.command(0, "choose", resources={"ore": 1})
    assert g.players[0].hand["ore"] == 1
    assert g.phase == "main"
    g.validate()


def test_resume_produces_identical_future_bot_actions(tmp_path):
    g = Game(seed=22)
    for _ in range(100):
        bots.step(g)
    path = tmp_path / "save.json"
    persistence.save(g, path)
    resumed = persistence.load(path)
    for _ in range(100):
        if g.winner is not None:
            break
        assert bots.step(g) == bots.step(resumed)
        assert g.to_dict() == resumed.to_dict()


def test_knight_before_roll_and_empty_deck():
    g = main_game()
    card(g, "knight")
    g.phase = "roll"
    g.command(0, "play", card="knight")
    assert g.players[0].knights == 1
    g.command(0, "robber", hex=(g.robber + 1) % 19)
    assert g.phase == "roll"
    force_roll(g, 6)
    assert g.phase == "main"
    give(g, 0, wheat=1, sheep=1, ore=1)
    g.deck.clear()
    before = g.to_dict()
    with pytest.raises(RuleError, match="empty"):
        g.command(0, "buy")
    assert g.to_dict() == before


@pytest.mark.parametrize("mutate", [
    lambda d: d["state"].update(command="shadow"),
    lambda d: d["state"].update(log=[22]),
    lambda d: d["board"]["edges"].__setitem__(0, [99, 99]),
    lambda d: d["state"].update(bot_memory={"0": {"turn": "10"}}),
    lambda d: d["state"].update(dice=[13, -1]),
])
def test_structurally_invalid_saves_are_clear_errors(tmp_path, mutate):
    data = main_game().to_dict()
    mutate(data)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data))
    with pytest.raises(RuleError, match="Cannot load save"):
        persistence.load(path)


def test_separate_play_seed_preserves_board_and_saved_random_sequence():
    a = Game(seed=1, play_seed=9876)
    b = Game(seed=1, play_seed=5432)
    assert a.board == b.board
    assert a.rng.getstate() != b.rng.getstate()
    loaded = Game.from_dict(json.loads(json.dumps(a.to_dict())))
    for game in (a, loaded):
        game.phase = "roll"
        game.command(game.current, "roll")
    assert a.to_dict() == loaded.to_dict()
    assert Game(seed=1).to_dict() == Game(seed=1).to_dict()
