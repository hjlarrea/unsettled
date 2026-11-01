"""Bounded heuristic opponents operating exclusively on player observations."""
from __future__ import annotations
import random
from collections import Counter, deque
from .engine import RESOURCES, COSTS


def decision(o: dict, difficulty: str, memory: dict) -> dict:
    """Return one command; memory is public serializable per-turn planning state."""
    p, hand, phase = o["player"], o["hand"], o["phase"]
    key = str(o["turn"])
    if memory.get("turn") != key:
        memory.clear()
        memory.update(turn=key, offers=0, bank_trades=0, declined=[])
    rng = random.Random(o["turn"] * 107 + p * 71 + sum(hand.values()) * 13 + len(o["roads"]))
    easy = difficulty == "Easy"
    persona = (p % 3)
    board, buildings = o["board"], o["buildings"]
    edges, hvs, hexes = board["edges"], board["hex_vertices"], board["hexes"]
    neighbors = {v: [] for v in range(len(board["vertices"]))}
    for a, b in edges:
        neighbors[a].append(b)
        neighbors[b].append(a)
    production = Counter()
    for i, vs in enumerate(hvs):
        for v in vs:
            if v in buildings and buildings[v][0] == p:
                production[hexes[i]["resource"]] += (6 - abs(7 - hexes[i]["number"])) * buildings[v][1] if hexes[i]["number"] else 0

    def site_score(v):
        score = 0
        diversity = set()
        for i, vs in enumerate(hvs):
            if v in vs and hexes[i]["number"]:
                r = hexes[i]["resource"]
                weight = (6 - abs(7 - hexes[i]["number"]))
                score += weight * (1.0 + 2.0 / (2 + production[r]))
                diversity.add(r)
                if r in ("ore", "wheat"):
                    score += weight * (0.30 if persona == 1 else 0.15)
        score += len(diversity) * 1.2
        for e, kind in board["ports"].items():
            if v in edges[int(e)]:
                score += 1.2 if kind == "any" else min(3, production[kind] / 4)
        if easy:
            score += rng.uniform(-8, 8)
        return score

    def cmd(action, **data):
        return dict(action=action, **data)

    if phase == "setup_settlement":
        return cmd("settlement", vertex=max(o["settlements"], key=site_score))

    # Distance to promising legal future settlement sites through available edges.
    candidates = {v for v in neighbors if v not in buildings and all(n not in buildings for n in neighbors[v])}
    def road_score(e):
        a, b = edges[e]
        best = -100
        for root in (a, b):
            queue, seen = deque([(root, 0)]), {root}
            while queue:
                v, distance = queue.popleft()
                if v in candidates:
                    best = max(best, site_score(v) - distance * 6)
                if distance == 4 or v in buildings and buildings[v][0] != p:
                    continue
                for j, (x, y) in enumerate(edges):
                    if v not in (x, y) or j in o["roads"] and o["roads"][j] != p:
                        continue
                    n = y if x == v else x
                    if n not in seen:
                        seen.add(n)
                        queue.append((n, distance + (0 if o["roads"].get(j) == p else 1)))
        own_degree = sum(owner == p and bool(set(edges[j]) & set((a, b))) for j, owner in o["roads"].items())
        return best + (own_degree * 0.3 if persona == 0 else 0)

    if phase in ("setup_road", "road_building"):
        return cmd("road", edge=max(o["road_sites"], key=road_score)) if o["road_sites"] else cmd("skip_roads")
    if phase == "discard":
        counts = hand.copy()
        discarded = Counter()
        for _ in range(o["discard"]):
            r = max(RESOURCES, key=lambda r: counts[r] - (0.5 if r in ("ore", "wheat") else 0))
            counts[r] -= 1
            discarded[r] += 1
        return cmd("discard", resources=dict(discarded))
    if phase == "robber":
        def damage(i):
            tile = hexes[i]
            weight = 6 - abs(7 - tile["number"]) if tile["number"] else 0
            return sum(((-3 if owner == p else 1 + o["players"][owner]["points"] / 8) * size * weight) for v in hvs[i] if v in buildings for owner, size in [buildings[v]])
        return cmd("robber", hex=max((i for i in range(19) if i != o["robber"]), key=damage))
    if phase == "victim":
        return cmd("steal", victim=max(o["victims"], key=lambda v: o["players"][v]["points"] + o["players"][v]["count"] / 10))

    def value(r):
        return (2.2 if hand[r] == 0 else 1.5 if hand[r] < 3 else 0.8) + 1.5 / (1 + production[r])

    if phase == "trade":
        t = o["trade"]
        can = all(hand[r] >= n for r, n in t["want"].items())
        gain = sum(value(r) * n for r, n in t["give"].items())
        loss = sum(value(r) * n for r, n in t["want"].items())
        dangerous = o["players"][t["owner"]]["points"] >= 8
        if can and gain >= loss * (0.8 if easy else 1.08) and not dangerous:
            return cmd("respond", accept=True)
        if can and not t["countered"] and not dangerous and gain > loss * 0.65:
            extra = max(t["give"], key=value)
            wanted = t["give"].copy()
            wanted[extra] += 1
            return cmd("respond", counter=dict(give=t["want"], want=wanted))
        return cmd("respond", accept=False)
    if phase == "plenty":
        bank = o["bank"].copy()
        picked = Counter()
        for _ in range(min(2, sum(bank.values()))):
            r = max((r for r in RESOURCES if bank[r]), key=lambda r: value(r) - picked[r])
            picked[r] += 1
            bank[r] -= 1
        return cmd("choose", resources=dict(picked))
    if phase == "monopoly":
        # Infer from public production, never inspect opponents' hands.
        estimates = Counter()
        for i, vs in enumerate(hvs):
            h = hexes[i]
            for v in vs:
                if v in buildings and buildings[v][0] != p and h["number"]:
                    estimates[h["resource"]] += (6 - abs(7 - h["number"])) * buildings[v][1]
        r = max(RESOURCES, key=lambda r: estimates[r] * value(r))
        return cmd("choose", resources={r: 1})
    if phase == "roll":
        blocked = any(v in buildings and buildings[v][0] == p for v in hvs[o["robber"]])
        if "knight" in o["playable"] and blocked:
            return cmd("play", card="knight")
        return cmd("roll")
    if phase != "main":
        raise ValueError(f"No bot handler for {phase}")

    for card in ("knight", "plenty", "monopoly", "roads"):
        if card in o["playable"] and (card != "roads" or o["road_sites"]) and (card != "plenty" or sum(o["bank"].values()) >= 1):
            return cmd("play", card=card)

    goals = []
    if o["cities"]:
        goals.append(("city", 10 + (2 if persona == 1 else 0), dict(vertex=max(o["cities"], key=site_score))))
    if o["settlements"]:
        goals.append(("settlement", 12 + (2 if persona == 2 else 0), dict(vertex=max(o["settlements"], key=site_score))))
    if o["road_sites"]:
        goals.append(("road", 5 + (1 if persona == 0 else 0), dict(edge=max(o["road_sites"], key=road_score))))
    if o["deck_count"]:
        goals.append(("development", 6 + (2 if persona == 1 else 0), {}))
    if not goals:
        return cmd("end")
    affordable = [g for g in goals if all(hand[r] >= n for r, n in COSTS[g[0]].items())]
    if affordable:
        kind, _, args = max(affordable, key=lambda g: g[1] + (rng.uniform(-4, 4) if easy else 0))
        return cmd("buy" if kind == "development" else kind, **args)
    def goal_score(g):
        missing = sum(max(0, n - hand[r]) for r, n in COSTS[g[0]].items())
        return g[1] / (missing + 0.6)
    goal = max(goals, key=goal_score)
    cost = COSTS[goal[0]]
    needs = [r for r, n in cost.items() if hand[r] < n]
    if needs:
        need = max(needs, key=value)
        surplus = [r for r in RESOURCES if hand[r] > cost.get(r, 0) and r not in needs]
        for give in sorted(surplus, key=lambda r: hand[r], reverse=True):
            if hand[give] - cost.get(give, 0) >= o["ratios"][give] and o["bank"][need] and memory["bank_trades"] < 6:
                memory["bank_trades"] += 1
                return cmd("bank_trade", give=give, receive=need)
        if surplus and memory["offers"] < 2:
            targets = [i for i, other in enumerate(o["players"]) if i != p and other["count"] > 0 and i not in memory["declined"]]
            if targets:
                target = targets[(o["turn"] + p) % len(targets)]
                memory["offers"] += 1
                memory["declined"].append(target)
                give = max(surplus, key=lambda r: hand[r] - cost.get(r, 0))
                return cmd("offer", target=target, give={give: 1}, want={need: 1})
    return cmd("end")


def step(game, player=None):
    """Apply exactly one bot action, including mandatory off-turn choices."""
    p = game.actor if player is None else player
    memory = game.bot_memory.setdefault(str(p), {})
    command = decision(game.observation(p), game.players[p].difficulty, memory)
    game.command(p, **command)
    return command
