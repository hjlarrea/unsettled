"""Pygame presentation. The engine remains the sole authority for legal actions."""
from __future__ import annotations
import math
from contextlib import contextmanager
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
WATER = (135, 198, 228)
WATER_RIM = (184, 224, 242)
WATER_LINE = (102, 169, 204)
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
        self.scale = 1.0
        self.offset = (0, 0)
        self.fullscreen = False
        self.windowed_size = self.window.get_size()
        self.sync_canvas()
        self.clock = pg.time.Clock()
        self.fonts = {}
        self.game = Game(bots=bots, seed=seed, play_seed=random.SystemRandom().getrandbits(128))
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
        asset = Path(__file__).parent / "assets" / "terrain-classic.png"
        self.atlas = pg.image.load(str(asset)).convert() if asset.exists() else None
        self.seed_limit = 12

    def font(self, size, serif=False, bold=False):
        key = (size, serif, bold)
        if key not in self.fonts:
            self.fonts[key] = pg.font.SysFont("Georgia" if serif else "Arial", size, bold=bold)
        return self.fonts[key]

    def text(self, text, x, y, size=20, color=LIGHT, serif=False, bold=False, center=False):
        # Rasterize glyphs once at their final size, never resize rendered text.
        surface = self.font(max(1, round(size * self.scale)), serif, bold).render(str(text), True, color)
        position = self.point((x, y))
        self.canvas.blit(surface, surface.get_rect(center=position) if center else position)

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

    def viewport(self):
        """One transform shared by native-pixel rendering and mouse hit testing."""
        width, height = self.window.get_size()
        scale = min(width / W, height / H)
        return scale, pg.Rect(0, 0, width, height)

    def sync_canvas(self):
        self.scale, viewport = self.viewport()
        self.width = viewport.width / self.scale
        self.height = viewport.height / self.scale
        if self.canvas.get_size() != viewport.size:
            self.canvas = pg.Surface(viewport.size)

    def point(self, point):
        return (round((point[0] + self.offset[0]) * self.scale),
                round((point[1] + self.offset[1]) * self.scale))

    @contextmanager
    def shifted(self, x=0, y=0):
        previous = self.offset
        self.offset = (previous[0] + x, previous[1] + y)
        try:
            yield
        finally:
            self.offset = previous

    def toggle_fullscreen(self):
        if self.fullscreen:
            self.window = pg.display.set_mode(self.windowed_size, pg.RESIZABLE)
        else:
            self.windowed_size = self.window.get_size()
            self.window = pg.display.set_mode((0, 0), pg.FULLSCREEN)
        self.fullscreen = not self.fullscreen
        self.sync_canvas()
        self.tile_cache.clear()

    def rect(self, rect):
        x, y, width, height = rect
        left, top = self.point((x, y))
        right, bottom = self.point((x + width, y + height))
        return pg.Rect(left, top, right - left, bottom - top)

    def stroke(self, width):
        return max(1, round(width * self.scale)) if width else 0

    def polygon(self, color, points, width=0):
        pg.draw.polygon(self.canvas, color, [self.point(p) for p in points], self.stroke(width))

    def line(self, color, start, end, width=1):
        pg.draw.line(self.canvas, color, self.point(start), self.point(end), self.stroke(width))

    def circle(self, color, center, radius, width=0):
        pg.draw.circle(self.canvas, color, self.point(center), max(1, round(radius * self.scale)), self.stroke(width))

    def ellipse(self, color, rect, width=0):
        pg.draw.ellipse(self.canvas, color, self.rect(rect), self.stroke(width))

    def panel(self, rect, color=PANEL, radius=16, border=None):
        native_rect = self.rect(rect)
        native_radius = max(0, round(radius * self.scale))
        pg.draw.rect(self.canvas, color, native_rect, border_radius=native_radius)
        if border:
            pg.draw.rect(self.canvas, border, native_rect, self.stroke(1), border_radius=native_radius)

    def button(self, label, rect, callback, active=True, accent=False, small=False):
        rect = pg.Rect(rect)
        mouse = self.mouse()
        hover = rect.move(self.offset).collidepoint(mouse)
        color = GOLD if accent else (49, 77, 83) if hover and active else (34, 61, 68)
        if not active:
            color = (28, 46, 52)
        self.panel(rect, color, radius=8, border=(GOLD if hover and active else None))
        self.text(label, rect.centerx, rect.centery, 16 if small else 19,
                  INK if accent else LIGHT if active else (91, 116, 119), bold=accent, center=True)
        if active:
            self.buttons.append((rect.move(self.offset), callback))

    def mouse(self, pos=None):
        pos = pos or pg.mouse.get_pos()
        scale, viewport = self.viewport()
        return ((pos[0] - viewport.x) / scale, (pos[1] - viewport.y) / scale)

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
        self.game = Game(self.bot_count, seed, self.recommended, self.difficulties[:self.bot_count],
                         play_seed=random.SystemRandom().getrandbits(128))
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
        return (int(520 + (self.width - W) / 2 + x * 79),
                int(490 + (self.height - H) / 2 + y * 79))

    def hex_center(self, h):
        tile = self.game.board.hexes[h]
        return (int(520 + (self.width - W) / 2 + math.sqrt(3) * (tile["q"] + tile["r"] / 2) * 79), int(490 + (self.height - H) / 2 + 1.5 * tile["r"] * 79))

    def tile(self, resource):
        key = (resource, self.scale)
        if key in self.tile_cache:
            return self.tile_cache[key]
        index = TILE_ORDER.index(resource)
        size = 162
        surface = pg.Surface((size, size), pg.SRCALPHA)
        if self.atlas:
            width, height = self.atlas.get_size()
            source = self.atlas.subsurface(pg.Rect(index % 3 * width // 3, index // 3 * height // 2, width // 3, height // 2))
            surface.blit(pg.transform.smoothscale(source, (size - 20, size - 20)), (10, 10))
        else:
            surface.fill(TERRAIN[index])
        mask = pg.Surface((size, size), pg.SRCALPHA)
        points = [(81 + 68 * math.cos(math.pi / 6 + i * math.pi / 3), 81 + 68 * math.sin(math.pi / 6 + i * math.pi / 3)) for i in range(6)]
        pg.draw.polygon(mask, (255, 255, 255, 255), points)
        surface.blit(mask, (0, 0), special_flags=pg.BLEND_RGBA_MULT)
        # Sandy shoulders give terrain its own space, like printed tabletop tiles.
        framed = pg.Surface((size, size), pg.SRCALPHA)
        outer = [(81 + 78 * math.cos(math.pi / 6 + i * math.pi / 3), 81 + 78 * math.sin(math.pi / 6 + i * math.pi / 3)) for i in range(6)]
        pg.draw.polygon(framed, (224, 185, 121), outer)
        framed.blit(surface, (0, 0))
        pg.draw.polygon(framed, (184, 148, 93), points, 1)
        native_size = max(1, round(size * self.scale))
        if native_size != size:
            framed = pg.transform.smoothscale(framed, (native_size, native_size))
        self.tile_cache[key] = framed
        return framed

    def water_outline(self, radius=414):
        return [(520 + (self.width - W) / 2 + radius * math.cos(i * math.pi / 3),
                 490 + (self.height - H) / 2 + radius * math.sin(i * math.pi / 3)) for i in range(6)]

    def draw_board(self):
        g = self.game
        # A regular six-sided sea frame surrounds the island and its ports.
        self.polygon(WATER_RIM, self.water_outline())
        self.polygon(WATER, self.water_outline(408))
        self.polygon(WATER_LINE, self.water_outline(395), 1)
        for i in range(19):
            cx, cy = self.hex_center(i)
            points = [self.screen_point(v) for v in g.board.hex_vertices[i]]
            self.polygon((211, 190, 145), [(int(cx + (x - cx) * 1.028), int(cy + (y - cy) * 1.028)) for x, y in points])
            self.canvas.blit(self.tile(g.board.hexes[i]["resource"]), self.point((cx - 81, cy - 81)))
            self.polygon((112, 107, 78), points, 1)
        for edge, kind in g.board.ports.items():
            a, b = [self.screen_point(v) for v in g.board.edges[edge]]
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            dx, dy = mid[0] - 520 - (self.width - W) / 2, mid[1] - 490 - (self.height - H) / 2
            length = math.hypot(dx, dy)
            x, y = mid[0] + dx / length * 41, mid[1] + dy / length * 41
            for end in (a, b):
                self.line((151, 153, 122), end, (x, y), 2)
            self.panel((x - 34, y - 14, 68, 29), INK, 7, (105, 137, 136))
            self.text("3:1" if kind == "any" else kind[:2].upper() + " 2:1", x, y + 1, 14, GOLD, center=True)
        for i, tile in enumerate(g.board.hexes):
            cx, cy = self.hex_center(i)
            n = tile["number"]
            if n:
                self.circle((36, 44, 39), (cx + 1, cy + 3), 25)
                self.circle((244, 227, 187), (cx, cy), 24)
                self.circle((180, 153, 107), (cx, cy), 24, 2)
                self.text(n, cx, cy - 3, 27, (164, 66, 48) if n in (6, 8) else INK, bold=True, center=True)
                dots = 6 - abs(7 - n)
                for j in range(dots):
                    self.circle((164, 66, 48) if n in (6, 8) else INK, (cx + int((j - (dots - 1) / 2) * 5), cy + 14), 1)
        for edge, owner in g.roads.items():
            self.draw_road(edge, owner)
        cx, cy = self.hex_center(g.robber)
        cx += 35
        cy -= 21
        self.ellipse((23, 35, 39), (cx - 11, cy + 10, 24, 10))
        self.polygon((51, 56, 62), [(cx - 9, cy + 13), (cx - 5, cy - 8), (cx + 5, cy - 8), (cx + 10, cy + 13)])
        self.circle((43, 49, 57), (cx, cy - 12), 8)
        self.circle((137, 148, 145), (cx - 2, cy - 14), 2)
        if not self.menu and g.actor == 0 and g.phase != "game_over":
            mode = self.active_mode()
            pulse = 4 + int(math.sin(pg.time.get_ticks() / 230) * 2)
            if mode in ("settlement", "city"):
                sites = g.city_sites(0) if mode == "city" else g.settlement_sites(0, g.phase == "setup_settlement")
                for v in sites:
                    self.circle(LIGHT, self.screen_point(v), 10, 2)
                    self.circle(GOLD, self.screen_point(v), pulse)
            elif mode == "road":
                for e in g.road_sites(0, g.setup_vertex if g.phase == "setup_road" else None):
                    a, b = [self.screen_point(v) for v in g.board.edges[e]]
                    self.line(GOLD, a, b, 4)
            elif g.phase == "robber":
                for i in range(19):
                    if i != g.robber:
                        self.polygon(GOLD, [self.screen_point(v) for v in g.board.hex_vertices[i]], 3)

        # Placed pieces sit above tile seams and all placement guides.
        for v, (owner, size) in g.buildings.items():
            self.draw_piece(v, owner, size)

    @staticmethod
    def piece_tone(owner, light=0):
        color = COLORS[owner]
        target = (255, 245, 221) if light > 0 else (28, 37, 40)
        return tuple(round(c + (t - c) * abs(light)) for c, t in zip(color, target))

    def draw_road(self, edge, owner):
        """A small beveled wooden beam, seated along the tile seam."""
        a, b = [self.screen_point(v) for v in self.game.board.edges[edge]]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        nx, ny = -dy / length, dx / length
        # Leave breathing room at intersections for the settlement pieces.
        a = (a[0] + dx * .10, a[1] + dy * .10)
        b = (b[0] - dx * .10, b[1] - dy * .10)
        top = [(x + nx * side, y + ny * side)
               for (x, y), side in ((a, -4), (b, -4), (b, 4), (a, 4))]
        self.polygon((45, 47, 39), [(x + 1, y + 4) for x, y in top])
        self.polygon(self.piece_tone(owner, -.44),
                     [top[3], top[2], (top[2][0], top[2][1] + 3),
                      (top[3][0], top[3][1] + 3)])
        self.polygon(self.piece_tone(owner), top)
        self.polygon(self.piece_tone(owner, -.35), top, 1)
        self.line(self.piece_tone(owner, .48), top[0], top[1], 2)
        self.line(self.piece_tone(owner, .18), a, b, 1)

    def draw_piece(self, v, owner, size):
        x, y = self.screen_point(v)
        self.ellipse((48, 47, 37), (x - 14, y - 5, 29, 18))
        if size == 2:
            y += 6
        base = self.piece_tone(owner)
        shade = self.piece_tone(owner, -.32)
        roof = self.piece_tone(owner, .28)
        edge = self.piece_tone(owner, -.57)

        def face(points, color):
            points = [(x + px, y + py) for px, py in points]
            self.polygon(color, points)
            self.polygon(edge, points, 1)

        if size == 1:
            # A compact 3D house, matching the city's painted wooden faces.
            y += 3
            face([(-10, 8), (-10, -3), (-2, -12), (7, -3), (7, 8)], base)
            face([(7, 8), (12, 4), (12, -7), (7, -3)], shade)
            face([(-2, -12), (3, -16), (12, -7), (7, -3)], roof)
            self.line(self.piece_tone(owner, .62), (x - 10, y - 3), (x - 2, y - 12), 2)
            self.panel((x - 4, y + 1, 5, 7), edge, 1)
        else:
            # A broad hall and taller keep distinguish cities at a glance.
            face([(-15, 9), (-15, -4), (-8, -11), (-1, -4), (-1, 9)], base)
            face([(-8, -11), (-4, -14), (3, -7), (-1, -4)], roof)
            face([(-1, 9), (-1, -14), (6, -21), (13, -14), (13, 9)], base)
            face([(13, 9), (17, 5), (17, -17), (13, -14)], shade)
            face([(6, -21), (10, -24), (17, -17), (13, -14)], roof)
            self.line(self.piece_tone(owner, .62), (x - 1, y - 14), (x + 6, y - 21), 2)
            self.panel((x + 3, y + 1, 6, 8), edge, 1)
            self.panel((x + 4, y - 11, 3, 5), edge, 1)
            self.panel((x - 11, y + 1, 4, 5), edge, 1)
            self.line(self.piece_tone(owner, .35), (x - 10, y + 9), (x + 10, y + 9), 1)

    def draw_die(self, value, x, y, size=40):
        """Draw a die at native resolution, including conventional pip positions."""
        self.panel((x + 1, y + 4, size, size), (10, 23, 28), 8)
        self.panel((x, y, size, size), (194, 177, 145), 8)
        self.panel((x, y, size, size - 3), (246, 234, 207), 8)
        self.line((255, 249, 231), (x + 9, y + 2), (x + size - 9, y + 2), 1)
        if value is None:
            self.line((156, 153, 138), (x + size * .4, y + size * .46),
                      (x + size * .6, y + size * .46), 2)
            return
        pips = []
        if value % 2:
            pips.append((.5, .46))
        if value >= 2:
            pips.extend(((.27, .24), (.73, .68)))
        if value >= 4:
            pips.extend(((.73, .24), (.27, .68)))
        if value == 6:
            pips.extend(((.27, .46), (.73, .46)))
        for px, py in pips:
            self.circle((161, 148, 123), (x + size * px, y + size * py + 1), 3.5)
            self.circle((48, 55, 54), (x + size * px, y + size * py), 3)

    def draw_dice(self):
        dice = self.game.dice
        self.text("LAST ROLL", 50, 706, 12, GOLD, bold=True)
        for i in range(2):
            self.draw_die(dice[i] if dice else None, 50 + i * 49, 727)
        if dice:
            self.text(sum(dice), 160, 723, 34, LIGHT, serif=True)
            self.text("total", 163, 761, 11, MUTED)
        else:
            self.text("Awaiting", 160, 735, 13, MUTED)
            self.text("first roll", 160, 752, 13, MUTED)

    def active_mode(self):
        return {"setup_settlement": "settlement", "setup_road": "road", "road_building": "road"}.get(self.game.phase, self.mode)

    def set_mode(self, mode):
        self.mode = mode

    def draw_header(self):
        self.text("UNSETTLED", 40, 21, 38, LIGHT, serif=True)
        self.text("AN ISLAND OF YOUR OWN", 43, 65, 12, GOLD, bold=True)
        with self.shifted(self.width - W):
            if not self.menu:
                self.button("Save", (942, 27, 78, 38), self.manual_save, small=True)
                self.button("Load", (1030, 27, 78, 38), lambda: self.load(True), small=True)
                self.button(["Slow", "Normal", "Fast"][self.speed], (1118, 27, 92, 38), self.cycle_speed, small=True)
                self.button("Menu", (1220, 27, 90, 38), self.toggle_menu, small=True)
                self.text(f"Island {self.game.seed}", 1329, 80, 12, MUTED, center=True)
            self.button("Window" if self.fullscreen else "Full screen", (1320, 27, 100, 38), self.toggle_fullscreen, small=True)
        self.line((57, 83, 85), (40, 97), (self.width - 40, 97))

    def cycle_speed(self):
        self.speed = (self.speed + 1) % 3

    def draw_players(self):
        g = self.game
        for i, p in enumerate(g.players):
            y = 117 + i * 66 + (80 if i else 0)
            self.panel((1045, y, 355, 138 if i == 0 else 58), (38, 65, 70) if i == g.current else PANEL, 10, GOLD if i == g.current else None)
            self.circle(COLORS[i], (1065, y + 20), 5)
            self.text(p.name, 1080, y + 9, 20, LIGHT, bold=True)
            points = g.points(i, i == 0 or g.winner is not None)
            self.text(f"{points} VP", 1340, y + 9, 20, GOLD, bold=True)
            detail = f"{sum(p.hand.values())} resources   {len(p.cards)} cards   {p.knights} knights"
            self.text(detail, 1080, y + 35, 13, MUTED)
            badges = ("R" if g.longest == i else "") + ("A" if g.army == i else "")
            if badges:
                self.text(badges, 1360, y + 35, 13, GOLD)

        # Keep private resource counts beside your own public player details.
        for i, r in enumerate(RESOURCES):
            x = 1055 + i * 68
            self.panel((x, 181, 64, 64), (32, 56, 61), 7)
            self.text(r.title(), x + 32, 193, 12, LIGHT, center=True)
            self.text(g.players[0].hand[r], x + 32, 216, 23, GOLD, bold=True, center=True)
            self.text(f"{g.bank[r]} · {g.ratio(0, r)}:1", x + 32, 236, 11, MUTED, center=True)

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

    def draw_board_status(self):
        self.draw_dice()
        self.text(f"TURN {self.game.turn + 1}", 910, 837, 14, MUTED)

    def resource_icon(self, r, x, y):
        color = TERRAIN[TILE_ORDER.index(r)]
        self.circle(color, (x, y), 13)
        letter = {"wood": "W", "brick": "B", "wheat": "G", "sheep": "S", "ore": "O"}[r]
        self.text(letter, x, y, 14, LIGHT, bold=True, center=True)

    def draw_hand(self):
        g = self.game
        with self.shifted(self.width - W):
            self.text("BUILDING COSTS", 1060, 878, 13, GOLD, bold=True)
            for i, (kind, cost) in enumerate(COSTS.items()):
                x, y = 1060 + (i % 2) * 165, 899 + (i // 2) * 28
                self.text(kind.title(), x, y, 13, LIGHT)
                self.text("  ".join(f"{n}{r[:2]}" for r, n in cost.items()), x, y + 14, 12, MUTED)
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
        shade = pg.Surface(self.canvas.get_size(), pg.SRCALPHA)
        shade.fill((11, 28, 35, 175))
        self.canvas.blit(shade, (0, round(98 * self.scale)))
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
        shade = pg.Surface(self.canvas.get_size(), pg.SRCALPHA)
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
        previous_scale = self.scale
        self.sync_canvas()
        if self.scale != previous_scale:
            self.tile_cache.clear()
        self.buttons = []
        self.canvas.fill(INK)
        self.draw_board()
        self.draw_header()
        if self.menu:
            with self.shifted((self.width - W) / 2, (self.height - H) / 2):
                self.draw_menu()
        else:
            with self.shifted(self.width - W):
                self.draw_players()
                with self.shifted(y=80):
                    self.draw_actions()
            with self.shifted((self.width - W) / 2, self.height - H):
                self.draw_board_status()
            with self.shifted(y=self.height - H):
                self.draw_hand()
            with self.shifted(self.width - W, self.height - H):
                with self.shifted(y=80):
                    self.draw_log()
        if self.modal:
            with self.shifted((self.width - W) / 2, (self.height - H) / 2):
                self.draw_modal()
        if self.toast and pg.time.get_ticks() < self.toast_until:
            self.panel((300, 103, 820, 48), (81, 62, 44), 10, GOLD)
            self.wrap(self.toast, 317, 116, 786, 16, LIGHT, 1)
        _, viewport = self.viewport()
        self.window.fill((10, 23, 29))
        self.window.blit(self.canvas, viewport.topleft)
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
                    if not self.fullscreen:
                        self.window = pg.display.set_mode((max(720, event.w), max(480, event.h)), pg.RESIZABLE)
                    self.sync_canvas()
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
                    if event.key == pg.K_F11 or (event.key == pg.K_f and event.mod & (pg.KMOD_CTRL | pg.KMOD_META)):
                        self.toggle_fullscreen()
                    elif self.menu and self.edit_seed:
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
                        elif self.fullscreen:
                            self.toggle_fullscreen()
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
