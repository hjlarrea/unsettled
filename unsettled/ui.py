"""Pygame presentation. The engine remains the sole authority for legal actions."""
from __future__ import annotations
import math
import os
import random
from pathlib import Path
import pygame as pg
from .engine import Game, RuleError, RESOURCES, COSTS
from . import bots, persistence

W, H = 1440, 960
INK = (18, 38, 46)
PANEL = (24, 46, 53)
LIGHT = (244, 235, 214)
MUTED = (162, 185, 181)
GOLD = (222, 180, 105)
COLORS = [(232, 137, 99), (113, 184, 165), (189, 163, 223), (111, 171, 210)]
TERRAIN = [(46, 108, 77), (164, 88, 62), (190, 156, 74), (111, 149, 84), (112, 126, 133), (206, 179, 127)]
TILE_ORDER = ["wood", "brick", "wheat", "sheep", "ore", "desert"]
CARD_NAMES = dict(knight="Knight", roads="Road Building", plenty="Year of Plenty", monopoly="Monopoly", victory="Victory Point")


class App:
    def __init__(self, seed=1, bots=3):
        pg.init()
        pg.display.set_caption("Unsettled • An island of your own")
        self.window = pg.display.set_mode((1280, 854), pg.RESIZABLE)
        self.canvas = pg.Surface((W, H))
        self.clock = pg.time.Clock()
        self.fonts = {}
        self.game = Game(bots=bots, seed=seed)
        self.menu = True
        self.started = False
        self.bot_count = bots
        self.difficulties = ["Standard"] * 3
        self.recommended = False
        self.seed_text = str(seed)
        self.edit_seed = False
        self.speed = 1
        self.buttons = []
        self.mode = None
        self.modal = None
        self.toast = ""
        self.toast_until = 0
        self.next_bot = 0
        self.running = True
        self.tile_cache = {}
        self.last_action = 0
        self.autosave_error = False
        asset = Path(__file__).parent / "assets" / "terrain.png"
        self.atlas = pg.image.load(str(asset)).convert() if asset.exists() else None
        self.seed_limit = 12

    def font(self, size, serif=False, bold=False):
        key = (size, serif, bold)
        if key not in self.fonts:
            self.fonts[key] = pg.font.SysFont("Georgia" if serif else "Helvetica", size, bold=bold)
        return self.fonts[key]

    def text(self, text, x, y, size=20, color=LIGHT, serif=False, bold=False, center=False):
        surface = self.font(size, serif, bold).render(str(text), True, color)
        self.canvas.blit(surface, surface.get_rect(center=(x, y)) if center else (x, y))

    def wrap(self, text, x, y, width, size=18, color=MUTED, max_lines=6):
        words, line, lines = str(text).split(), "", []
        for word in words:
            test = (line + " " + word).strip()
            if self.font(size).size(test)[0] > width and line:
                lines.append(line)
                line = word
            else:
                line = test
        if line:
            lines.append(line)
        for i, line in enumerate(lines[:max_lines]):
            self.text(line, x, y + i * (size + 5), size, color)
        return min(len(lines), max_lines) * (size + 5)

    def panel(self, rect, color=PANEL, radius=16, border=None):
        pg.draw.rect(self.canvas, color, rect, border_radius=radius)
        if border:
            pg.draw.rect(self.canvas, border, rect, 1, border_radius=radius)

    def button(self, label, rect, callback, active=True, accent=False, small=False):
        rect = pg.Rect(rect)
        mouse = self.mouse()
        hover = rect.collidepoint(mouse)
        color = GOLD if accent else (49, 77, 83) if hover and active else (34, 61, 68)
        if not active:
            color = (28, 46, 52)
        self.panel(rect, color, radius=8, border=(GOLD if hover and active else None))
        self.text(label, rect.centerx, rect.centery, 16 if small else 19,
                  INK if accent else LIGHT if active else (91, 116, 119), bold=accent, center=True)
        if active:
            self.buttons.append((rect, callback))

    def mouse(self, pos=None):
        pos = pos or pg.mouse.get_pos()
        width, height = self.window.get_size()
        scale = min(width / W, height / H)
        return ((pos[0] - (width - W * scale) / 2) / scale, (pos[1] - (height - H * scale) / 2) / scale)

    def notify(self, message, duration=5500):
        self.toast, self.toast_until = message, pg.time.get_ticks() + duration

    def autosave(self):
        try:
            persistence.save(self.game)
            self.autosave_error = False
        except OSError as exc:
            self.autosave_error = True
            self.notify(f"Autosave failed: {exc}. Use Save to retry.", 15000)

    def act(self, action, **data):
        try:
            self.game.command(0, action, **data)
        except RuleError as exc:
            self.notify(str(exc))
            return False
        self.mode = None
        self.modal = None
        self.last_action = pg.time.get_ticks()
        self.next_bot = self.last_action + self.delay()
        self.autosave()
        return True

    def delay(self):
        return (1100, 500, 80)[self.speed]

    def manual_save(self):
        try:
            persistence.save(self.game, persistence.save_dir() / "manual.json")
            self.autosave()
            self.notify("Game saved. You can close the window and resume later.")
        except OSError as exc:
            self.notify(f"Cannot save: {exc}", 10000)

    def load(self, manual=False):
        try:
            game = persistence.load(persistence.save_dir() / ("manual.json" if manual else "autosave.json"))
        except RuleError as exc:
            self.notify(str(exc), 10000)
            return
        self.game = game
        self.menu = False
        self.started = True
        self.mode = self.modal = None
        self.autosave_error = False
        self.next_bot = pg.time.get_ticks() + self.delay()
        self.notify("Welcome back. Your island is exactly where you left it.")

    def new_game(self):
        try:
            seed = int(self.seed_text) if self.seed_text.strip() else random.SystemRandom().randrange(1_000_000_000)
        except ValueError:
            self.notify("Enter a whole number for the island seed.")
            return
        self.game = Game(self.bot_count, seed, self.recommended, self.difficulties[:self.bot_count])
        self.menu = False
        self.started = True
        self.mode = self.modal = None
        self.tile_cache.clear()
        self.next_bot = pg.time.get_ticks() + self.delay()
        self.autosave()

    def toggle_menu(self):
        self.menu = not self.menu
        self.edit_seed = False
        self.mode = self.modal = None
        self.next_bot = pg.time.get_ticks() + self.delay()

    def screen_point(self, v):
        x, y = self.game.board.vertices[v]
        return (int(520 + x * 79), int(424 + y * 79))

    def hex_center(self, h):
        tile = self.game.board.hexes[h]
        return (int(520 + math.sqrt(3) * (tile["q"] + tile["r"] / 2) * 79), int(424 + 1.5 * tile["r"] * 79))

    def tile(self, resource):
        if resource in self.tile_cache:
            return self.tile_cache[resource]
        index = TILE_ORDER.index(resource)
        size = 162
        surface = pg.Surface((size, size), pg.SRCALPHA)
        if self.atlas:
            width, height = self.atlas.get_size()
            source = self.atlas.subsurface(pg.Rect(index % 3 * width // 3, index // 3 * height // 2, width // 3, height // 2))
            surface.blit(pg.transform.smoothscale(source, (size, size)), (0, 0))
        else:
            surface.fill(TERRAIN[index])
        mask = pg.Surface((size, size), pg.SRCALPHA)
        points = [(81 + 78 * math.cos(math.pi / 6 + i * math.pi / 3), 81 + 78 * math.sin(math.pi / 6 + i * math.pi / 3)) for i in range(6)]
        pg.draw.polygon(mask, (255, 255, 255, 255), points)
        surface.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        self.tile_cache[resource] = surface
        return surface

    def draw_board(self):
        g = self.game
        # Layered coast and subtle wave strokes behind the illustrated terrain.
        pg.draw.ellipse(self.canvas, (27, 65, 74), (108, 66, 824, 722))
        pg.draw.ellipse(self.canvas, (36, 81, 87), (143, 95, 755, 657), 2)
        for i in range(19):
            cx, cy = self.hex_center(i)
            points = [self.screen_point(v) for v in g.board.hex_vertices[i]]
            pg.draw.polygon(self.canvas, (211, 190, 145), [(int(cx + (x - cx) * 1.028), int(cy + (y - cy) * 1.028)) for x, y in points])
            self.canvas.blit(self.tile(g.board.hexes[i]["resource"]), (cx - 81, cy - 81))
            pg.draw.polygon(self.canvas, (112, 107, 78), points, 1)
        for edge, kind in g.board.ports.items():
            a, b = [self.screen_point(v) for v in g.board.edges[edge]]
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            dx, dy = mid[0] - 520, mid[1] - 424
            length = math.hypot(dx, dy)
            x, y = mid[0] + dx / length * 41, mid[1] + dy / length * 41
            for end in (a, b):
                pg.draw.line(self.canvas, (151, 153, 122), end, (x, y), 2)
            self.panel((x - 34, y - 14, 68, 29), INK, 7, (105, 137, 136))
            self.text("3:1" if kind == "any" else kind[:2].upper() + " 2:1", x, y + 1, 14, GOLD, center=True)
        for i, tile in enumerate(g.board.hexes):
            cx, cy = self.hex_center(i)
            n = tile["number"]
            if n:
                pg.draw.circle(self.canvas, (36, 44, 39), (cx + 1, cy + 3), 25)
                pg.draw.circle(self.canvas, (244, 227, 187), (cx, cy), 24)
                pg.draw.circle(self.canvas, (180, 153, 107), (cx, cy), 24, 2)
                self.text(n, cx, cy - 3, 27, (164, 66, 48) if n in (6, 8) else INK, bold=True, center=True)
                dots = 6 - abs(7 - n)
                for j in range(dots):
                    pg.draw.circle(self.canvas, (164, 66, 48) if n in (6, 8) else INK, (cx + int((j - (dots - 1) / 2) * 5), cy + 14), 1)
        for edge, owner in g.roads.items():
            a, b = [self.screen_point(v) for v in g.board.edges[edge]]
            pg.draw.line(self.canvas, INK, a, b, 12)
            pg.draw.line(self.canvas, COLORS[owner], a, b, 7)
        for v, (owner, size) in g.buildings.items():
            self.draw_piece(v, owner, size)
        cx, cy = self.hex_center(g.robber)
        cx += 35
        cy -= 21
        pg.draw.ellipse(self.canvas, (23, 35, 39), (cx - 11, cy + 10, 24, 10))
        pg.draw.polygon(self.canvas, (51, 56, 62), [(cx - 9, cy + 13), (cx - 5, cy - 8), (cx + 5, cy - 8), (cx + 10, cy + 13)])
        pg.draw.circle(self.canvas, (43, 49, 57), (cx, cy - 12), 8)
        pg.draw.circle(self.canvas, (137, 148, 145), (cx - 2, cy - 14), 2)
        if not self.menu and g.actor == 0 and g.phase != "game_over":
            mode = self.active_mode()
            pulse = 4 + int(math.sin(pg.time.get_ticks() / 230) * 2)
            if mode in ("settlement", "city"):
                sites = g.city_sites(0) if mode == "city" else g.settlement_sites(0, g.phase == "setup_settlement")
                for v in sites:
                    pg.draw.circle(self.canvas, LIGHT, self.screen_point(v), 10, 2)
                    pg.draw.circle(self.canvas, GOLD, self.screen_point(v), pulse)
            elif mode == "road":
                for e in g.road_sites(0, g.setup_vertex if g.phase == "setup_road" else None):
                    a, b = [self.screen_point(v) for v in g.board.edges[e]]
                    pg.draw.line(self.canvas, GOLD, a, b, 4)
            elif g.phase == "robber":
                for i in range(19):
                    if i != g.robber:
                        pg.draw.polygon(self.canvas, GOLD, [self.screen_point(v) for v in g.board.hex_vertices[i]], 3)

    def draw_piece(self, v, owner, size):
        x, y = self.screen_point(v)
        if size == 1:
            shape = [(x - 10, y + 8), (x - 10, y - 4), (x, y - 13), (x + 10, y - 4), (x + 10, y + 8)]
        else:
            shape = [(x - 15, y + 9), (x - 15, y - 5), (x - 8, y - 12), (x - 1, y - 5), (x - 1, y - 16), (x + 7, y - 21), (x + 15, y - 16), (x + 15, y + 9)]
        pg.draw.polygon(self.canvas, INK, shape)
        pg.draw.polygon(self.canvas, COLORS[owner], shape)
        pg.draw.polygon(self.canvas, INK, shape, 2)
        pg.draw.line(self.canvas, (246, 228, 196), (x - 7, y + 5), (x + 5, y + 5), 2)

    def active_mode(self):
        return {"setup_settlement": "settlement", "setup_road": "road", "road_building": "road"}.get(self.game.phase, self.mode)

    def set_mode(self, mode):
        self.mode = mode

    def draw_header(self):
        self.text("UNSETTLED", 40, 21, 38, LIGHT, serif=True)
        self.text("AN ISLAND OF YOUR OWN", 43, 65, 12, GOLD, bold=True)
        if not self.menu:
            self.button("Save", (942, 27, 78, 38), self.manual_save, small=True)
            self.button("Load", (1030, 27, 78, 38), lambda: self.load(True), small=True)
            self.button(["Slow", "Normal", "Fast"][self.speed], (1118, 27, 92, 38), self.cycle_speed, small=True)
            self.button("Menu", (1220, 27, 90, 38), self.toggle_menu, small=True)
            self.text(f"Island {self.game.seed}", 1329, 80, 12, MUTED, center=True)
        pg.draw.line(self.canvas, (57, 83, 85), (40, 97), (1400, 97))

    def cycle_speed(self):
        self.speed = (self.speed + 1) % 3

    def draw_players(self):
        g = self.game
        for i, p in enumerate(g.players):
            y = 117 + i * 66
            self.panel((1045, y, 355, 58), (38, 65, 70) if i == g.current else PANEL, 10, GOLD if i == g.current else None)
            pg.draw.circle(self.canvas, COLORS[i], (1065, y + 20), 5)
            self.text(p.name, 1080, y + 9, 20, LIGHT, bold=True)
            points = g.points(i, i == 0 or g.winner is not None)
            self.text(f"{points} VP", 1340, y + 9, 20, GOLD, bold=True)
            detail = f"{sum(p.hand.values())} resources   {len(p.cards)} cards   {p.knights} knights"
            self.text(detail, 1080, y + 35, 13, MUTED)
            badges = ("R" if g.longest == i else "") + ("A" if g.army == i else "")
            if badges:
                self.text(badges, 1360, y + 35, 13, GOLD)

    def draw_actions(self):
        g = self.game
        self.text("YOUR NEXT MOVE" if g.actor == 0 else "AT THE TABLE", 1060, 399, 13, GOLD, bold=True)
        human = g.actor == 0
        explanations = {
            "setup_settlement": "Choose a highlighted intersection for your settlement.",
            "setup_road": "Choose a highlighted edge for your starting road.",
            "roll": "Roll the dice. You may play an eligible development card first.",
            "main": "Trade, build, or play a card. End your turn when you are ready.",
            "discard": f"Choose {g.discards.get(0, 0)} resources to return to the bank.",
            "robber": "Click a different hex to move the robber.",
            "victim": "Choose a neighboring opponent to steal from.",
            "road_building": f"Place up to {g.free_roads} free roads on highlighted edges.",
            "plenty": "Choose up to two available resources from the bank.",
            "monopoly": "Choose the resource to collect from all opponents.",
            "trade": "A trade is waiting for your response.",
            "game_over": f"{g.players[g.winner if g.winner is not None else 0].name} wins! Start another island from the menu.",
        }
        message = explanations[g.phase] if human or g.phase == "game_over" else f"{g.players[g.actor].name} is considering their move…"
        self.wrap(message, 1060, 427, 320, 19, LIGHT, 3)
        y = 510
        if g.phase == "game_over":
            self.button("Back to menu", (1060, y, 320, 44), self.toggle_menu, accent=True)
        elif human:
            if g.phase == "roll":
                self.button("Roll dice", (1060, y, 320, 46), lambda: self.act("roll"), accent=True)
            elif g.phase == "main":
                for i, (label, kind) in enumerate((("Road", "road"), ("Settlement", "settlement"), ("City", "city"))):
                    sites = g.road_sites(0) if kind == "road" else g.settlement_sites(0) if kind == "settlement" else g.city_sites(0)
                    self.button(label, (1060 + (i % 2) * 165, y + (i // 2) * 45, 155, 37), lambda k=kind: self.set_mode(k), active=g.afford(0, kind) and bool(sites), accent=self.mode == kind, small=True)
                self.button("Buy card", (1225, y + 45, 155, 37), lambda: self.act("buy"), active=g.afford(0, "development") and bool(g.deck), small=True)
                self.button("Bank / ports", (1060, y + 90, 155, 37), lambda: self.open_modal("bank"), small=True)
                self.button("Player trade", (1225, y + 90, 155, 37), lambda: self.open_modal("offer"), small=True)
                self.button("End turn", (1060, y + 137, 320, 43), lambda: self.act("end"), accent=True)
            elif g.phase in ("discard", "plenty", "monopoly"):
                self.button("Choose resources", (1060, y, 320, 44), lambda: self.open_modal(g.phase), accent=True)
            elif g.phase == "trade":
                self.button("View trade offer", (1060, y, 320, 44), lambda: self.open_modal("trade"), accent=True)
            elif g.phase == "victim":
                for i, victim in enumerate(g.victims):
                    self.button(g.players[victim].name, (1060, y + i * 44, 320, 37), lambda v=victim: self.act("steal", victim=v))
            elif g.phase == "road_building":
                self.button("Finish free roads", (1060, y, 320, 42), lambda: self.act("skip_roads"))
        if g.dice:
            self.text(f"LAST ROLL   {g.dice[0]} + {g.dice[1]} = {sum(g.dice)}", 50, 751, 16, GOLD, bold=True)
        self.text(f"TURN {g.turn + 1}", 910, 751, 14, MUTED)

    def resource_icon(self, r, x, y):
        color = TERRAIN[TILE_ORDER.index(r)]
        pg.draw.circle(self.canvas, color, (x, y), 13)
        letter = {"wood": "W", "brick": "B", "wheat": "G", "sheep": "S", "ore": "O"}[r]
        self.text(letter, x, y, 14, LIGHT, bold=True, center=True)

    def draw_hand(self):
        g = self.game
        self.text("YOUR RESOURCES", 45, 795, 13, GOLD, bold=True)
        self.text("BUILDING COSTS", 1060, 805, 13, GOLD, bold=True)
        for i, (kind, cost) in enumerate(COSTS.items()):
            self.text(kind.title(), 1060, 831 + i * 27, 15, LIGHT)
            self.text("  ".join(f"{n}{r[:2]}" for r, n in cost.items()), 1168, 831 + i * 27, 14, MUTED)
        for i, r in enumerate(RESOURCES):
            x = 44 + i * 195
            self.panel((x, 818, 182, 65), (32, 56, 61), 10)
            self.resource_icon(r, x + 24, 844)
            self.text(r.title(), x + 45, 829, 19, LIGHT)
            self.text(g.players[0].hand[r], x + 154, 843, 29, GOLD, bold=True, center=True)
            self.text(f"Bank {g.bank[r]}  •  Port {g.ratio(0, r)}:1", x + 15, 861, 12, MUTED)
        counts = CounterCards(g.players[0].cards)
        x = 45
        if not counts:
            self.text("Development cards will appear here.", x, 912, 16, MUTED)
        for card, count in counts.items():
            label = f"{CARD_NAMES[card]} ×{count}"
            width = max(150, self.font(16).size(label)[0] + 28)
            self.button(label, (x, 900, width, 37), lambda c=card: self.act("play", card=c), active=g.actor == 0 and g.phase in ("roll", "main") and card in g.playable(0), small=True)
            x += width + 10

    def draw_log(self):
        self.text("TABLE JOURNAL", 1060, 710, 13, GOLD, bold=True)
        # Expanded journal opens on L; compact view keeps the board uncluttered.
        latest = self.game.log[-1]
        self.wrap(latest, 1060, 741, 320, 16, MUTED, 2)
        self.button("Journal", (1280, 702, 100, 29), lambda: self.open_modal("journal"), small=True)

    def draw_menu(self):
        shade = pg.Surface((W, H), pg.SRCALPHA)
        shade.fill((11, 28, 35, 175))
        self.canvas.blit(shade, (0, 98))
        self.text("A little island.", 80, 270, 65, LIGHT, serif=True)
        self.text("A whole evening.", 80, 345, 65, LIGHT, serif=True)
        self.wrap("Gather. Trade. Build. Settle in for a game at your own pace, with a table that is always ready.", 86, 455, 540, 24, LIGHT, 4)
        self.text("OFFLINE  /  NO TIMERS  /  JUST ONE MORE TURN", 86, 625, 14, GOLD, bold=True)
        self.panel((830, 153, 550, 742), INK, 24, (77, 109, 111))
        self.text("Your next island", 873, 188, 38, LIGHT, serif=True)
        self.text("THE TABLE", 875, 255, 13, GOLD, bold=True)
        for i, count in enumerate((2, 3)):
            self.button(f"You + {count} bots", (875 + i * 224, 281, 210, 44), lambda c=count: setattr(self, "bot_count", c), accent=self.bot_count == count)
        self.text("OPPONENTS", 875, 350, 13, GOLD, bold=True)
        for i in range(self.bot_count):
            y = 379 + i * 51
            self.text(("Juniper", "Flint", "Marina")[i], 875, y + 9, 20, COLORS[i + 1])
            self.button(self.difficulties[i], (1135, y, 175, 39), lambda j=i: self.toggle_difficulty(j), small=True)
        self.text("BOARD", 875, 557, 13, GOLD, bold=True)
        self.button("Recommended" if self.recommended else "Random island", (875, 582, 435, 39), lambda: setattr(self, "recommended", not self.recommended))
        self.text("Island seed (blank = random)", 875, 639, 15, MUTED)
        self.button(self.seed_text + ("|" if self.edit_seed else ""), (1121, 632, 189, 34), lambda: setattr(self, "edit_seed", True), small=True)
        self.button("Set sail", (875, 693, 435, 51), self.new_game, accent=True)
        self.button("Resume autosave", (875, 758, 435, 40), self.load)
        if self.started:
            self.button("Return to current game", (875, 811, 435, 39), self.toggle_menu)
        self.text("Base game • 3–4 players • First to 10 points", 875, 864, 14, MUTED)

    def toggle_difficulty(self, index):
        self.difficulties[index] = "Easy" if self.difficulties[index] == "Standard" else "Standard"

    def open_modal(self, kind):
        self.modal = dict(kind=kind, give=dict.fromkeys(RESOURCES, 0), want=dict.fromkeys(RESOURCES, 0), target=1, give_r=0, receive_r=1, offset=0)
        if kind == "trade":
            return
        if kind == "counter":
            t = self.game.trade
            self.modal["give"].update(t["want"])
            self.modal["want"].update(t["give"])

    def change(self, side, r, amount):
        m = self.modal
        limit = self.game.players[0].hand[r] if side == "give" else 19
        if m["kind"] == "plenty":
            limit = self.game.bank[r]
        if m["kind"] == "monopoly":
            m[side] = dict.fromkeys(RESOURCES, 0)
            limit = 1
        m[side][r] = max(0, min(limit, m[side][r] + amount))

    def draw_modal(self):
        m = self.modal
        shade = pg.Surface((W, H), pg.SRCALPHA)
        shade.fill((6, 18, 24, 210))
        self.canvas.blit(shade, (0, 0))
        # Remove underlying hit targets; modal owns input until dismissed.
        self.buttons = []
        self.panel((365, 152, 710, 650), INK, 22, (105, 133, 131))
        kind = m["kind"]
        titles = dict(bank="Trade with the bank", offer="Propose a trade", counter="Make a counteroffer", trade="At the trading table", discard="Return resources", plenty="Year of Plenty", monopoly="Monopoly", journal="Table journal")
        self.text(titles[kind], 408, 183, 34, LIGHT, serif=True)
        self.button("×", (1001, 180, 37, 37), lambda: setattr(self, "modal", None))
        if kind == "journal":
            lines = []
            for entry in self.game.log:
                words, line = entry.split(), ""
                for word in words:
                    if self.font(18).size((line + " " + word).strip())[0] > 615:
                        lines.append(line)
                        line = word
                    else:
                        line = (line + " " + word).strip()
                lines.append(line)
            end = max(1, len(lines) - m["offset"])
            for i, line in enumerate(lines[max(0, end - 16):end]):
                self.text(line, 410, 254 + i * 27, 18, MUTED)
            self.button("Older", (410, 734, 160, 36), lambda: m.update(offset=min(max(0, len(lines) - 1), m["offset"] + 8)))
            self.button("Newer", (590, 734, 160, 36), lambda: m.update(offset=max(0, m["offset"] - 8)))
            return
        if kind == "trade":
            t = self.game.trade
            name = self.game.players[t["owner"]].name
            self.text(f"{name} offers you", 410, 263, 22, GOLD)
            self.wrap(self.bundle_label(t["give"]), 410, 305, 610, 26, LIGHT)
            self.text("In exchange for", 410, 395, 22, GOLD)
            self.wrap(self.bundle_label(t["want"]), 410, 437, 610, 26, LIGHT)
            self.button("Accept trade", (410, 616, 290, 48), lambda: self.act("respond", accept=True), active=all(self.game.players[0].hand[r] >= n for r, n in t["want"].items()), accent=True)
            self.button("Decline", (724, 616, 300, 48), lambda: self.act("respond", accept=False))
            self.button("Counteroffer", (410, 685, 614, 42), lambda: self.open_modal("counter"), active=not t["countered"])
            return
        if kind == "bank":
            give, receive = RESOURCES[m["give_r"]], RESOURCES[m["receive_r"]]
            ratio = self.game.ratio(0, give)
            self.text("YOU GIVE", 410, 278, 15, GOLD, bold=True)
            self.text("YOU RECEIVE", 740, 278, 15, GOLD, bold=True)
            for i, r in enumerate(RESOURCES):
                y = 320 + i * 53
                self.button(f"{ratio if r == give else self.game.ratio(0, r)} {r.title()}", (410, y, 282, 43), lambda j=i: m.update(give_r=j), accent=give == r)
                self.button(f"1 {r.title()} ({self.game.bank[r]} left)", (740, y, 282, 43), lambda j=i: m.update(receive_r=j), accent=receive == r)
            self.wrap("Your ports are applied automatically. Click a resource in each column.", 410, 608, 610, 19)
            self.button("Trade", (410, 716, 612, 46), lambda: self.act("bank_trade", give=give, receive=receive), active=give != receive and self.game.players[0].hand[give] >= ratio and self.game.bank[receive] > 0, accent=True)
            return
        trading = kind in ("offer", "counter")
        if trading:
            if kind == "offer":
                self.button(f"With {self.game.players[m['target']].name}  ›", (410, 244, 612, 40), lambda: m.update(target=m["target"] % (len(self.game.players) - 1) + 1))
            self.text("YOU GIVE", 582, 305, 14, GOLD, bold=True)
            self.text("YOU REQUEST", 820, 305, 14, GOLD, bold=True)
        else:
            count = self.game.discards.get(0, 0) if kind == "discard" else min(2, sum(self.game.bank.values())) if kind == "plenty" else 1
            self.text(f"Select exactly {count} {'resource type' if kind == 'monopoly' else 'cards'}.", 410, 263, 21, MUTED)
        for i, r in enumerate(RESOURCES):
            y = 350 + i * 59
            self.resource_icon(r, 423, y + 18)
            self.text(r.title(), 448, y + 7, 20, LIGHT)
            for j, side in enumerate(("give", "want") if trading else ("give",)):
                x = 580 + j * 240
                self.button("−", (x, y, 38, 38), lambda s=side, r=r: self.change(s, r, -1))
                self.text(m[side][r], x + 77, y + 19, 23, GOLD, center=True)
                self.button("+", (x + 113, y, 38, 38), lambda s=side, r=r: self.change(s, r, 1))
            if not trading:
                n = self.game.bank[r] if kind == "plenty" else self.game.players[0].hand[r]
                self.text(f"{'Bank' if kind == 'plenty' else 'In hand'}: {n}", 820, y + 10, 17, MUTED)
        def submit():
            if kind == "offer":
                self.act("offer", target=m["target"], give=m["give"], want=m["want"])
            elif kind == "counter":
                self.act("respond", counter=dict(give=m["give"], want=m["want"]))
            else:
                self.act("discard" if kind == "discard" else "choose", resources=m["give"])
        selected = sum(m["give"].values())
        label = "Send offer" if trading else f"Confirm ({selected} selected)"
        self.button(label, (410, 716, 612, 46), submit, accent=True)

    @staticmethod
    def bundle_label(bundle):
        return ", ".join(f"{n} {r}" for r, n in bundle.items() if n)

    def render(self):
        self.buttons = []
        self.canvas.fill(INK)
        self.draw_board()
        self.draw_header()
        if self.menu:
            self.draw_menu()
        else:
            self.draw_players()
            self.draw_actions()
            self.draw_hand()
            self.draw_log()
        if self.modal:
            self.draw_modal()
        if self.toast and pg.time.get_ticks() < self.toast_until:
            self.panel((300, 103, 820, 48), (81, 62, 44), 10, GOLD)
            self.wrap(self.toast, 317, 116, 786, 16, LIGHT, 1)
        width, height = self.window.get_size()
        scale = min(width / W, height / H)
        scaled = pg.transform.smoothscale(self.canvas, (round(W * scale), round(H * scale)))
        self.window.fill((10, 23, 29))
        self.window.blit(scaled, ((width - scaled.get_width()) // 2, (height - scaled.get_height()) // 2))
        pg.display.flip()

    def board_click(self, pos):
        g = self.game
        if self.menu or self.modal or g.actor != 0 or g.phase == "game_over":
            return
        mode = self.active_mode()
        if mode in ("settlement", "city"):
            sites = g.city_sites(0) if mode == "city" else g.settlement_sites(0, g.phase == "setup_settlement")
            if sites:
                v = min(sites, key=lambda v: math.dist(pos, self.screen_point(v)))
                if math.dist(pos, self.screen_point(v)) < 25:
                    self.act(mode, vertex=v)
        elif mode == "road":
            sites = g.road_sites(0, g.setup_vertex if g.phase == "setup_road" else None)
            def midpoint(e):
                a, b = [self.screen_point(v) for v in g.board.edges[e]]
                return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if sites:
                e = min(sites, key=lambda e: math.dist(pos, midpoint(e)))
                if math.dist(pos, midpoint(e)) < 30:
                    self.act("road", edge=e)
        elif g.phase == "robber":
            h = min(range(19), key=lambda i: math.dist(pos, self.hex_center(i)))
            if math.dist(pos, self.hex_center(h)) < 68:
                self.act("robber", hex=h)

    def update(self):
        g = self.game
        if self.menu or g.winner is not None:
            return
        if g.actor == 0:
            if g.phase == "trade" and self.modal is None:
                self.open_modal("trade")
            return
        if self.modal is not None or self.autosave_error:
            return
        if pg.time.get_ticks() >= self.next_bot:
            try:
                bots.step(g)
                self.autosave()
            except (RuleError, ValueError) as exc:
                self.autosave_error = True
                self.notify(f"Bot paused: {exc}. Save and reload to retry.", 15000)
            self.next_bot = pg.time.get_ticks() + self.delay()
            self.last_action = pg.time.get_ticks()

    def run(self, screenshot=None):
        if screenshot:
            self.menu = False
            self.render()
            pg.image.save(self.canvas, screenshot)
            pg.quit()
            return
        while self.running:
            self.update()
            self.render()
            for event in pg.event.get():
                if event.type == pg.QUIT:
                    if self.started:
                        self.autosave()
                    self.running = False
                elif event.type == pg.VIDEORESIZE:
                    self.window = pg.display.set_mode((max(720, event.w), max(480, event.h)), pg.RESIZABLE)
                elif event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
                    pos = self.mouse(event.pos)
                    handled = False
                    for rect, callback in reversed(self.buttons):
                        if rect.collidepoint(pos):
                            callback()
                            handled = True
                            break
                    if not handled:
                        self.board_click(pos)
                elif event.type == pg.KEYDOWN:
                    if self.menu and self.edit_seed:
                        if event.key == pg.K_BACKSPACE:
                            self.seed_text = self.seed_text[:-1]
                        elif event.key in (pg.K_RETURN, pg.K_ESCAPE):
                            self.edit_seed = False
                        elif event.unicode.isascii() and event.unicode.isdigit() and len(self.seed_text) < self.seed_limit:
                            self.seed_text += event.unicode
                    elif event.key == pg.K_ESCAPE:
                        if self.modal:
                            self.modal = None
                        elif self.mode:
                            self.mode = None
                        else:
                            self.toggle_menu()
                    elif event.key == pg.K_l and not self.menu:
                        self.open_modal("journal")
                    elif event.key == pg.K_s and event.mod & (pg.KMOD_CTRL | pg.KMOD_META) and not self.menu:
                        self.manual_save()
            self.clock.tick(60)
        pg.quit()


def CounterCards(cards):
    counts = {}
    for card, _ in cards:
        counts[card] = counts.get(card, 0) + 1
    return counts
