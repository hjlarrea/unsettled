"""Pygame presentation. The engine remains the sole authority for legal actions."""
from __future__ import annotations
import math
from contextlib import contextmanager
from collections import Counter
import os
import random
from pathlib import Path
import pygame as pg
from .engine import Game, RuleError, RESOURCES, COSTS
from . import bots, persistence
from .perspective import Camera, Scene
from .presentation import TurnPresentation

W, H = 1440, 960
INK = (18, 38, 46)
PANEL = (24, 46, 53)
LIGHT = (244, 235, 214)
WHITE = (255, 255, 255)
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
    def __init__(self, seed=1, bots=3, perspective=False):
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
        self.pacing = TurnPresentation()
        self.buttons = []
        self.tooltips = []
        self.tooltip_target = None
        self.tooltip_since = 0
        self.tooltip_rect = None
        self.mode = None
        self.modal = None
        self.toast = ""
        self.toast_until = 0
        self.next_bot = 0
        self.running = True
        self.perspective = perspective
        self.camera = Camera()
        self.scene = Scene()
        self.camera_drag = None
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

    def button(self, label, rect, callback, active=True, accent=False, small=False, tooltip=None):
        rect = pg.Rect(rect)
        mouse = self.mouse()
        hover = rect.move(self.offset).collidepoint(mouse)
        color = GOLD if accent else (49, 77, 83) if hover and active else (34, 61, 68)
        if not active:
            color = (28, 46, 52)
        self.panel(rect, color, radius=8, border=(GOLD if hover and active else None))
        self.text(label, rect.centerx, rect.centery, 16 if small else 19,
                  INK if accent else LIGHT if active else (91, 116, 119), bold=accent, center=True)
        if tooltip:
            self.tooltips.append((rect.move(self.offset), tooltip))
        if active:
            self.buttons.append((rect.move(self.offset), callback))

    def draw_tooltip(self):
        mouse = self.mouse()
        target = next(((tuple(rect), text) for rect, text in reversed(self.tooltips)
                       if rect.collidepoint(mouse)), None)
        self.tooltip_rect = None
        if target != self.tooltip_target:
            self.tooltip_target = target
            self.tooltip_since = pg.time.get_ticks()
        if target is None or pg.time.get_ticks() - self.tooltip_since < 350:
            return
        # Measure at native resolution so text wraps correctly at every scale.
        font = self.font(max(1, round(16 * self.scale)))
        max_width = min(340, self.width - 48)
        lines = []
        for paragraph in target[1].split("\n"):
            line = ""
            for word in paragraph.split():
                candidate = (line + " " + word).strip()
                if line and font.size(candidate)[0] / self.scale > max_width:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
        width = max(font.size(line)[0] / self.scale for line in lines) + 24
        height = len(lines) * 22 + 20
        x = max(12, min(mouse[0] + 16, self.width - width - 12))
        y = mouse[1] + 22
        if y + height > self.height - 12:
            y = mouse[1] - height - 14
        y = max(12, min(y, self.height - height - 12))
        self.tooltip_rect = pg.Rect(round(x), round(y), math.ceil(width), math.ceil(height))
        self.panel((x + 3, y + 4, width, height), (10, 23, 29), 8)
        self.panel((x, y, width, height), PANEL, 8, GOLD)
        for i, line in enumerate(lines):
            self.text(line, x + 12, y + 10 + i * 22, 16, LIGHT)

    def purchase_tooltip(self, kind, sites=None):
        g = self.game
        cost = COSTS[kind]
        lines = ["Cost: " + self.bundle_label(cost) + "."]
        missing = {r: n - g.players[0].hand[r] for r, n in cost.items()
                   if g.players[0].hand[r] < n}
        if missing:
            lines.append("You need " + self.bundle_label(missing) + " more.")
        if kind == "development":
            if not g.deck:
                lines.append("The development card deck is empty.")
            else:
                lines.append("Draw a development card. Play action cards on a later turn.")
        elif not sites:
            exhausted = (sum(owner == 0 for owner in g.roads.values()) >= 15 if kind == "road"
                         else g.pieces(0, 1 if kind == "settlement" else 2) >= (5 if kind == "settlement" else 4))
            if exhausted:
                lines.append(f"No {kind} pieces left.")
            else:
                lines.append({"road": "No open edges connect to your roads or buildings.",
                              "settlement": "No legal sites. Connect a road to an empty intersection at least two edges from other buildings.",
                              "city": "You need one of your settlements to upgrade."}[kind])
        else:
            lines.append({"road": "Choose a highlighted edge to build a road.",
                          "settlement": "Choose a highlighted intersection to build a settlement.",
                          "city": "Upgrade one of your settlements to a city."}[kind])
        return "\n".join(lines)

    def card_tooltip(self, card):
        g = self.game
        effect = {"knight": "Move the robber and steal a resource from a neighbor.",
                  "roads": "Build up to two roads for free.",
                  "plenty": "Take two available resources from the bank.",
                  "monopoly": "Take all resources of one type from every opponent.",
                  "victory": "Worth 1 hidden victory point. Counted automatically; never played."}[card]
        if card == "victory":
            return effect
        if g.winner is not None:
            reason = "The game has ended."
        elif self.pacing.blocks_input:
            reason = "Wait for the roll presentation to finish, or press Space to skip."
        elif g.actor != 0 or g.current != 0:
            reason = "Wait for your turn to play this card."
        elif g.phase not in ("roll", "main"):
            reason = "Finish the current action before playing a development card."
        elif g.played_card:
            reason = "You have already played a development card this turn."
        elif not any(c == card and bought < g.turn for c, bought in g.players[0].cards):
            reason = "You cannot play a card on the turn you bought it."
        else:
            reason = "Play before or after rolling. Only one development card per turn."
        return effect + "\n" + reason

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
        before = self.pacing.snapshot(self.game)
        try:
            self.game.command(0, action, **data)
        except RuleError as exc:
            self.notify(str(exc))
            return False
        self.mode = None
        self.modal = None
        self.last_action = pg.time.get_ticks()
        self.pacing.observe(before, self.game, dict(action=action, **data), self.last_action, self.speed)
        self.schedule_bot()
        self.autosave()
        return True

    def delay(self):
        return (4000, 2500, 1200)[self.speed]

    def schedule_bot(self):
        self.bot_wait_started = max(pg.time.get_ticks(), self.pacing.ends_at if self.pacing.busy else 0)
        self.bot_wait_duration = self.delay()
        self.next_bot = self.bot_wait_started + self.bot_wait_duration

    def bot_progress(self):
        if self.menu or self.modal or self.autosave_error or self.game.actor == 0 or self.pacing.busy:
            return None
        duration = getattr(self, "bot_wait_duration", self.delay())
        return max(0.0, min(1.0, 1 - (self.next_bot - pg.time.get_ticks()) / duration))

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
        self.pacing.clear()
        self.menu = False
        self.started = True
        self.mode = self.modal = None
        self.autosave_error = False
        self.schedule_bot()
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
        self.pacing.announce(self.game, pg.time.get_ticks(), self.speed)
        self.schedule_bot()
        self.autosave()

    def toggle_menu(self):
        self.menu = not self.menu
        self.edit_seed = False
        self.mode = self.modal = None
        self.schedule_bot()

    def screen_point(self, v):
        x, y = self.game.board.vertices[v]
        if self.perspective:
            return self.project_world((x * 79, y * 79, 0))
        return (int(520 + (self.width - W) / 2 + x * 79),
                int(490 + (self.height - H) / 2 + y * 79))

    def hex_center(self, h):
        tile = self.game.board.hexes[h]
        if self.perspective:
            return self.project_world((*self.scene.center(tile), 0))
        return (int(520 + (self.width - W) / 2 + math.sqrt(3) * (tile["q"] + tile["r"] / 2) * 79), int(490 + (self.height - H) / 2 + 1.5 * tile["r"] * 79))

    def camera_center(self):
        return (520 + (self.width - W) / 2, 460 + (self.height - H) / 2)

    def project_world(self, point):
        x, y, _ = self.camera.project(point, self.camera_center())
        return (x, y)

    def board_viewport(self):
        return pg.Rect(20, 105, self.width - 460, self.height - 220)

    def set_perspective(self, enabled):
        self.perspective = enabled
        self.camera_drag = None

    def toggle_perspective(self):
        self.set_perspective(not self.perspective)

    def reset_camera(self):
        self.camera = Camera()
        self.camera_drag = None

    def draw_view_controls(self):
        self.button("View: 3D" if self.perspective else "View: Classic", (40, 110, 140, 30),
                    self.toggle_perspective, small=True,
                    tooltip="Switch between the classic board and the 3D experiment. Shortcut: P.")
        if self.perspective:
            self.button("Reset view", (190, 110, 108, 30), self.reset_camera, small=True,
                        tooltip="Reset rotation, pan, and zoom. Shortcut: Home.")
            self.text("Middle drag: orbit  /  Shift: pan  /  Scroll: zoom", 40, 149, 12, MUTED)

    def camera_event(self, event):
        # Always release a drag, including when a dialog opened while dragging.
        if event.type == pg.MOUSEBUTTONUP and event.button == 2:
            dragging = self.camera_drag is not None
            self.camera_drag = None
            return dragging
        if self.menu or self.modal:
            self.camera_drag = None
            return False
        if event.type == pg.KEYDOWN:
            if event.key == pg.K_p:
                self.toggle_perspective()
                return True
            if event.key == pg.K_HOME and self.perspective:
                self.reset_camera()
                return True
        if not self.perspective:
            return False
        if event.type == pg.MOUSEMOTION and self.camera_drag is not None:
            dx, dy = (delta / self.scale for delta in event.rel)
            dx = -dx
            if self.camera_drag == "pan":
                self.camera.pan[0] = max(-550, min(550, self.camera.pan[0] + dx))
                self.camera.pan[1] = max(-350, min(350, self.camera.pan[1] + dy))
            else:
                self.camera.orbit(dx, dy)
            return True
        if event.type not in (pg.MOUSEBUTTONDOWN, pg.MOUSEWHEEL):
            return False
        pos = self.mouse(event.pos) if hasattr(event, "pos") else self.mouse()
        if not self.board_viewport().collidepoint(pos) or any(rect.collidepoint(pos) for rect, _ in self.buttons):
            return False
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 2:
            self.camera_drag = "pan" if pg.key.get_mods() & pg.KMOD_SHIFT else "orbit"
            return True
        if event.type == pg.MOUSEWHEEL:
            self.camera.magnify(-event.y if getattr(event, "flipped", False) else event.y)
            return True
        return False

    def perspective_board_click(self, pos):
        if not self.board_viewport().collidepoint(pos):
            return
        g = self.game
        mode = self.active_mode()
        if mode in ("settlement", "city"):
            sites = g.city_sites(0) if mode == "city" else g.settlement_sites(0, g.phase == "setup_settlement")
            if sites:
                vertex = min(sites, key=lambda v: math.dist(pos, self.screen_point(v)))
                if math.dist(pos, self.screen_point(vertex)) < 18:
                    self.act(mode, vertex=vertex)
        elif mode == "road":
            sites = g.road_sites(0, g.setup_vertex if g.phase == "setup_road" else None)

            def distance(edge):
                a, b = [self.screen_point(v) for v in g.board.edges[edge]]
                dx, dy = b[0] - a[0], b[1] - a[1]
                t = max(0, min(1, ((pos[0] - a[0]) * dx + (pos[1] - a[1]) * dy) / (dx * dx + dy * dy)))
                return math.dist(pos, (a[0] + dx * t, a[1] + dy * t))

            if sites:
                edge = min(sites, key=distance)
                if distance(edge) < 12:
                    self.act("road", edge=edge)
        elif g.phase == "robber":
            world = self.camera.unproject(pos, self.camera_center())
            if world is None:
                return
            for i, tile in enumerate(g.board.hexes):
                cx, cy = self.scene.center(tile)
                x, y = world[0] - cx, world[1] - cy
                if max(x * math.cos(j * math.pi / 3) + y * math.sin(j * math.pi / 3)
                       for j in range(6)) <= 79 * math.cos(math.pi / 6):
                    self.act("robber", hex=i)
                    break

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
        # Fixed local randomness keeps the grain still and leaves game RNG alone.
        grain = random.Random(410 + index)
        normals = [(math.cos(i * math.pi / 3), math.sin(i * math.pi / 3))
                   for i in range(6)]
        for _ in range(1100):
            x, y = grain.uniform(-78, 78), grain.uniform(-78, 78)
            distance = max(x * nx + y * ny for nx, ny in normals)
            if 68 * math.cos(math.pi / 6) < distance < 78 * math.cos(math.pi / 6) - 1:
                color = grain.choice([(193, 154, 97), (239, 206, 149),
                                      (210, 169, 108), (247, 218, 165)])
                pg.draw.line(framed, color, (round(81 + x), round(81 + y)),
                             (round(81 + x + grain.choice((0, 1))), round(81 + y)))
        # Short, broken dune contours follow each sandy shoulder.
        for side in range(6):
            angle = side * math.pi / 3
            nx, ny = math.cos(angle), math.sin(angle)
            tx, ty = -ny, nx
            for j in range(4):
                along = -24 + j * 15 + grain.uniform(-2, 2)
                distance = grain.uniform(62, 65)
                ripple = [(81 + nx * (distance + .5 * math.sin(k)) + tx * (along + k),
                           81 + ny * (distance + .5 * math.sin(k)) + ty * (along + k))
                          for k in range(8)]
                pg.draw.lines(framed, (236, 201, 143), False, ripple, 1)
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

    def draw_sea_frame(self):
        # Raised gold molding, with a chased vine between two fine bead rails.
        shadow, bronze = (67, 49, 32), (130, 85, 37)
        highlight = (255, 230, 169)
        self.polygon(shadow, self.water_outline(435))
        self.polygon(bronze, self.water_outline(432))
        self.polygon(GOLD, self.water_outline(429))
        self.polygon(highlight, self.water_outline(428), 2)
        self.polygon(bronze, self.water_outline(411), 2)
        self.polygon(highlight, self.water_outline(409), 1)
        self.polygon((44, 94, 137), self.water_outline(408))
        # Nested hexes keep the depth gradient parallel to the outer frame.
        deep = (42, 100, 146)
        for radius in range(403, 277, -2):
            blend = (403 - radius) / 125
            blend = blend * blend * (3 - 2 * blend)
            color = tuple(round(a + (b - a) * blend) for a, b in zip(deep, WATER))
            self.polygon(color, self.water_outline(radius))
        outer = self.water_outline(420)
        for i, (x, y) in enumerate(outer):
            following = outer[(i + 1) % 6]
            dx, dy = following[0] - x, following[1] - y
            length = math.hypot(dx, dy)
            tx, ty = dx / length, dy / length
            nx, ny = -ty, tx

            def at(t, across=0):
                return (x + dx * t + nx * across,
                        y + dy * t + ny * across)

            # Continuous curling stem and paired embossed laurel leaves.
            stem = [at(j / 120, 2 * math.sin(j / 120 * math.tau * 10))
                    for j in range(121)]
            for start, end in zip(stem, stem[1:]):
                self.line(bronze, start, end, 1)
            for j in range(1, 20):
                t = j / 20
                for side in (-1, 1):
                    points = [at(t - .012), at(t - .008, side * 4),
                              at(t + .011, side * 6), at(t + .006, side * 1)]
                    self.polygon(bronze, points)
                    self.line(highlight, at(t - .008, side),
                              at(t + .008, side * 4), 1)
            for j in range(1, 41):
                self.circle(highlight, at(j / 41, -6), 1)
                self.circle(bronze, at(j / 41, 7), 1)
            # Engraved lozenge at each side's midpoint.
            self.polygon(bronze, [at(.48), at(.5, -7), at(.52), at(.5, 7)])
            self.polygon(highlight, [at(.486), at(.5, -5), at(.514), at(.5, 5)], 1)
            self.circle((105, 139, 125), at(.5), 2)
            # Six petalled corner rosettes, set into a dark gold bezel.
            self.circle(bronze, (x, y), 11)
            self.circle(highlight, (x, y), 9, 1)
            for petal in range(6):
                angle = petal * math.pi / 3
                center = (x + 5 * math.cos(angle), y + 5 * math.sin(angle))
                self.circle(GOLD, center, 3)
                self.circle(highlight, (center[0] - 1, center[1] - 1), 1)
            self.circle(bronze, (x, y), 4)
            self.circle((121, 162, 143), (x, y), 2)

    def draw_shoreline(self):
        board = self.game.board
        counts = Counter(tuple(sorted((vs[i], vs[(i + 1) % 6])))
                         for vs in board.hex_vertices for i in range(6))
        for tile, vertices in enumerate(board.hex_vertices):
            cx, cy = self.hex_center(tile)
            for i, vertex in enumerate(vertices):
                following = vertices[(i + 1) % 6]
                if counts[tuple(sorted((vertex, following)))] != 1:
                    continue
                a, b = self.screen_point(vertex), self.screen_point(following)
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = math.hypot(dx, dy)
                nx, ny = dy / length, -dx / length
                if nx * ((a[0] + b[0]) / 2 - cx) + ny * ((a[1] + b[1]) / 2 - cy) < 0:
                    nx, ny = -nx, -ny

                def at(t, outward):
                    return (a[0] + dx * t + nx * outward,
                            a[1] + dy * t + ny * outward)

                # A narrow damp beach, then translucent-looking shallow water.
                self.polygon((115, 190, 206), [at(0, 2), at(1, 2), at(1, 10), at(0, 10)])
                self.polygon((192, 163, 111), [at(0, -1), at(1, -1), at(1, 3), at(0, 3)])
                self.line((237, 207, 154), at(.03, -1), at(.97, -1))
                # Two irregular, broken breakers; ports and pieces render above them.
                phase = vertex * 1.7
                for band, color, width in ((7, (233, 246, 231), 2),
                                           (18, (186, 226, 226), 1)):
                    previous = None
                    for step in range(41):
                        t = step / 40
                        point = at(t, band + 1.6 * math.sin(t * math.tau * 2 + phase)
                                   + .6 * math.sin(t * math.tau * 5 + phase))
                        if previous is not None and math.sin(t * 27 + phase + band) > -.55:
                            self.line(color, previous, point, width)
                        previous = point
                foam = random.Random(vertex * 97 + following)
                for _ in range(15):
                    t = foam.uniform(.04, .96)
                    distance = foam.uniform(4, 13)
                    self.circle((220, 240, 229), at(t, distance), foam.choice((.5, .7, 1)))

    def draw_port(self, edge, kind):
        a, b = [self.screen_point(v) for v in self.game.board.edges[edge]]
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        cx = 520 + (self.width - W) / 2
        cy = 490 + (self.height - H) / 2
        length = math.hypot(mx - cx, my - cy)
        nx, ny = (mx - cx) / length, (my - cy) / length
        tx, ty = -ny, nx

        def at(outward, sideways=0):
            return (mx + nx * outward + tx * sideways,
                    my + ny * outward + ty * sideways)

        # Planked access walks connect each eligible shore intersection.
        shore = sorted((a, b), key=lambda v: (v[0] - mx) * tx + (v[1] - my) * ty)
        for vertex, side in zip(shore, (-12, 12)):
            end = at(25, side)
            vx, vy = end[0] - vertex[0], end[1] - vertex[1]
            span = math.hypot(vx, vy)
            ux, uy = -vy / span, vx / span
            corners = [(point[0] + ux * width, point[1] + uy * width)
                       for point, width in ((vertex, -4), (end, -4), (end, 4), (vertex, 4))]
            self.polygon((66, 51, 37), [(x + 1, y + 3) for x, y in corners])
            self.polygon((158, 109, 64), corners)
            for plank in range(max(1, int(span / 5))):
                fraction = plank * 5 / span
                px, py = vertex[0] + vx * fraction, vertex[1] + vy * fraction
                self.line((224, 175, 109), (px - ux * 3, py - uy * 3),
                          (px + ux * 3, py + uy * 3), 2)

        # A slim landing joins the two walks without a broad dock platform.
        deck = [at(22, -14), at(32, -14), at(32, 14), at(22, 14)]
        self.polygon(WATER_LINE, [(x + 2, y + 4) for x, y in deck])
        self.polygon((79, 52, 33), [(x, y + 2) for x, y in deck])
        self.polygon((105, 68, 39), deck)
        for distance, color in ((23, (175, 123, 71)), (28, (190, 139, 82))):
            self.polygon(color, [at(distance, -13), at(distance + 4, -13),
                                 at(distance + 4, 13), at(distance, 13)])
            self.line((235, 188, 120), at(distance, -12), at(distance, 12), 1)
            self.line((120, 78, 44), at(distance + 2, -7), at(distance + 2, 6), 1)
            for side in (-10, 10):
                self.circle((70, 61, 51), at(distance + 2, side), 1)
        for side in (-15, 15):
            x, y = at(27, side)
            self.line((83, 54, 34), (x, y + 3), (x, y - 2), 4)
            self.circle((111, 73, 41), (x, y - 2), 3)
            self.circle((229, 184, 117), (x, y - 3), 2)
            self.circle((140, 93, 50), (x, y - 3), 1)
        # A tiny moored merchant vessel, drawn upright for legibility.
        x, y = at(52)
        self.ellipse(WATER_LINE, (x - 21, y + 11, 44, 9), 1)
        self.polygon((88, 61, 42), [(x - 20, y + 6), (x + 20, y + 6),
                                             (x + 12, y + 16), (x - 11, y + 16)])
        self.line(GOLD, (x - 16, y + 8), (x + 15, y + 8), 2)
        self.line((91, 70, 46), (x, y - 25), (x, y + 5), 2)
        sail = LIGHT if kind == "any" else TERRAIN[TILE_ORDER.index(kind)]
        self.polygon(sail, [(x - 2, y - 25), (x - 2, y + 2), (x - 18, y + 2)])
        self.polygon((255, 240, 200), [(x + 3, y - 20), (x + 16, y + 1), (x + 3, y + 1)])
        self.line((181, 152, 104), (x - 2, y - 25), (x - 18, y + 2))
        x, y = at(40, 68)
        self.panel((x - 37, y - 12, 74, 24), INK, 7, GOLD)
        label = "3:1" if kind == "any" else kind[:2].upper() + " 2:1"
        self.text(label, x, y, 13, GOLD, bold=True, center=True)

    def draw_board(self):
        if self.perspective:
            clip = self.canvas.get_clip()
            self.canvas.set_clip(self.rect(self.board_viewport()))
            try:
                self.scene.draw(self)
            finally:
                self.canvas.set_clip(clip)
            return
        g = self.game
        self.draw_sea_frame()
        for i in range(19):
            cx, cy = self.hex_center(i)
            points = [self.screen_point(v) for v in g.board.hex_vertices[i]]
            self.polygon((211, 190, 145), [(int(cx + (x - cx) * 1.028), int(cy + (y - cy) * 1.028)) for x, y in points])
            self.canvas.blit(self.tile(g.board.hexes[i]["resource"]), self.point((cx - 81, cy - 81)))
            self.polygon((112, 107, 78), points, 1)
        self.draw_shoreline()
        for edge, kind in g.board.ports.items():
            self.draw_port(edge, kind)
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
            if mode in ("settlement", "city"):
                sites = g.city_sites(0) if mode == "city" else g.settlement_sites(0, g.phase == "setup_settlement")
                for v in sites:
                    self.draw_placement_marker(self.screen_point(v))
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

    def draw_placement_marker(self, position, compact=False):
        radius = (8 if compact else 10) + 1.5 * math.sin(pg.time.get_ticks() / 350)
        self.circle(WHITE, position, radius, 2)
        self.circle(WHITE, position, 3)

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
        dice = self.pacing.dice_for(self.game)
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
        if not self.menu:
            with self.shifted((self.width - W) / 2):
                self.draw_turn_banner()
        self.line((57, 83, 85), (40, 97), (self.width - 40, 97))

    def human_attention_color(self):
        """Breathe gently while waiting for human input; keep text steady."""
        if (self.menu or self.autosave_error or self.pacing.blocks_input or self.game.winner is not None
                or self.game.actor != 0
                or (self.modal and self.modal["kind"] == "journal")):
            return GOLD
        # A smooth 2.2-second cycle, with a visible border even at its dimmest.
        strength = .8 - .2 * math.cos(pg.time.get_ticks() * math.tau / 2200)
        return tuple(round(base + (gold - base) * strength)
                     for base, gold in zip(PANEL, GOLD))

    def draw_turn_banner(self):
        g = self.game
        human = g.actor == 0
        phases = {
            "setup_settlement": "Place a settlement", "setup_road": "Place a road",
            "roll": "Roll dice", "main": "Trade & build", "discard": "Discard resources",
            "robber": "Move the robber", "victim": "Choose a victim",
            "road_building": "Road Building", "plenty": "Year of Plenty",
            "monopoly": "Monopoly", "trade": "Respond to trade", "game_over": "Game over",
        }
        color = GOLD if human else COLORS[g.actor]
        self.panel((320, 13, 600, 74), PANEL, 10, self.human_attention_color() if human else color)
        if g.winner is not None:
            heading = f"{g.players[g.winner].name.upper()} WINS"
        else:
            owner = "YOUR TURN" if g.current == 0 else f"{g.players[g.current].name.upper()}'S TURN"
            heading = f"TURN {g.turn + 1}  /  {owner}"
        self.text(heading, 336, 21, 12, color, bold=True)
        phase_label = phases[g.phase]
        if self.pacing.blocks_input:
            phase_label = {"dice": "Dice roll", "harvest": "Production", "transfer": "Distribute resources", "phase": phase_label}[self.pacing.effects[0].kind]
        self.text(phase_label, 336, 39, 23, LIGHT, bold=True)
        if g.winner is None:
            if self.autosave_error:
                detail = "Paused · save to retry"
            elif self.modal:
                detail = "Paused"
            elif self.pacing.blocks_input:
                detail = "Turn unfolding · Space to skip"
            elif human:
                detail = "Your move · take your time"
            else:
                detail = f"{g.players[g.actor].name} · next action"
            # Right-align supporting text without changing the shared text helper.
            width = self.font(max(1, round(13 * self.scale))).size(detail)[0] / self.scale
            self.text(detail, 903 - width, 50, 13, MUTED)
            progress = self.bot_progress()
            if progress is not None:
                self.panel((336, 75, 568, 4), INK, 2)
                if progress > 0:
                    self.panel((336, 75, max(2, 568 * progress), 4), color, 2)

    def cycle_speed(self):
        self.speed = (self.speed + 1) % 3
        self.schedule_bot()

    def draw_players(self):
        g = self.game
        # Keep seats fixed in first-round order, including during snake setup.
        y = 117
        for i in g.setup_order[:len(g.players)]:
            p = g.players[i]
            self.panel((1045, y, 355, 58), (38, 65, 70) if i == g.current else PANEL, 10, GOLD if i == g.current else None)
            if i == g.current and g.winner is None:
                self.draw_turn_marker(1037, y + 29)
            self.circle(COLORS[i], (1065, y + 20), 5)
            self.text(p.name, 1080, y + 9, 20, LIGHT, bold=True)
            points = g.points(i, i == 0 or g.winner is not None)
            self.text(f"{points} VP", 1340, y + 9, 20, GOLD, bold=True)
            detail = f"{sum(self.pacing.hand_for(i, g).values())} resources   {len(p.cards)} cards   {p.knights} knights"
            self.text(detail, 1080, y + 35, 13, MUTED)
            badges = ("R" if g.longest == i else "") + ("A" if g.army == i else "")
            if badges:
                self.text(badges, 1360, y + 35, 13, GOLD)

            y += 66

    def draw_turn_marker(self, x, y):
        """A gold, compass-like arrow pointing into the current player's box."""
        color = self.human_attention_color() if self.game.current == 0 else GOLD
        self.line(color, (x - 28, y), (x - 7, y), 2)
        self.polygon(color, [(x, y), (x - 12, y - 8), (x - 9, y), (x - 12, y + 8)])
        self.polygon(color, [(x - 32, y), (x - 28, y - 4), (x - 24, y), (x - 28, y + 4)])
        self.line(color, (x - 21, y - 5), (x - 17, y), 1)
        self.line(color, (x - 21, y + 5), (x - 17, y), 1)

    def draw_actions(self):
        g = self.game
        title = "TURN EVENTS" if self.pacing.blocks_input else "YOUR NEXT MOVE" if g.actor == 0 else "AT THE TABLE"
        self.text(title, 1060, 399, 13, GOLD, bold=True)
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
        if self.pacing.blocks_input:
            message = {"dice": "Revealing the dice roll.", "harvest": "Matching tiles produce resources.",
                       "transfer": "Resources are arriving in each player's hand.", "phase": message}[self.pacing.effects[0].kind]
        self.wrap(message, 1060, 427, 320, 19, LIGHT, 3)
        y = 510
        if self.pacing.blocks_input:
            self.wrap("Watching the turn unfold…", 1060, y, 320, 18, MUTED, 2)
            self.text("Space to skip", 1060, y + 45, 14, MUTED)
            return
        if g.phase == "game_over":
            self.button("Back to menu", (1060, y, 320, 44), self.toggle_menu, accent=True)
        elif human:
            if g.phase == "roll":
                self.button("Roll dice", (1060, y, 320, 46), lambda: self.act("roll"), accent=True, tooltip="Roll both dice to produce resources. A seven activates the robber.")
            elif g.phase == "main":
                for i, (label, kind) in enumerate((("Road", "road"), ("Settlement", "settlement"), ("City", "city"))):
                    sites = g.road_sites(0) if kind == "road" else g.settlement_sites(0) if kind == "settlement" else g.city_sites(0)
                    self.button(label, (1060 + (i % 2) * 165, y + (i // 2) * 45, 155, 37), lambda k=kind: self.set_mode(k), active=g.afford(0, kind) and bool(sites), accent=self.mode == kind, small=True, tooltip=self.purchase_tooltip(kind, sites))
                self.button("Buy card", (1225, y + 45, 155, 37), lambda: self.act("buy"), active=g.afford(0, "development") and bool(g.deck), small=True, tooltip=self.purchase_tooltip("development"))
                self.button("Bank / ports", (1060, y + 90, 155, 37), lambda: self.open_modal("bank"), small=True, tooltip="Trade resources with the bank. Your best port rate applies automatically.")
                self.button("Player trade", (1225, y + 90, 155, 37), lambda: self.open_modal("offer"), small=True, tooltip="Offer resources to an opponent in exchange for resources you need.")
                self.button("End turn", (1060, y + 137, 320, 43), lambda: self.act("end"), accent=True, tooltip="Finish your turn and pass play to the next player.")
            elif g.phase in ("discard", "plenty", "monopoly"):
                self.button("Choose resources", (1060, y, 320, 44), lambda: self.open_modal(g.phase), accent=True, tooltip={"discard": "Choose the required number of resources to return to the bank.", "plenty": "Choose up to two available resources from the bank.", "monopoly": "Choose the resource type to collect from all opponents."}[g.phase])
            elif g.phase == "trade":
                self.button("View trade offer", (1060, y, 320, 44), lambda: self.open_modal("trade"), accent=True, tooltip="Review the offer, then accept, decline, or make a counteroffer.")
            elif g.phase == "victim":
                for i, victim in enumerate(g.victims):
                    self.button(g.players[victim].name, (1060, y + i * 44, 320, 37), lambda v=victim: self.act("steal", victim=v), tooltip="Steal one random resource from this opponent.")
            elif g.phase == "road_building":
                self.button("Finish free roads", (1060, y, 320, 42), lambda: self.act("skip_roads"), tooltip="Finish Road Building without placing the remaining free roads.")

    def draw_board_status(self):
        self.draw_dice()
        self.text(f"TURN {self.game.turn + 1}", 910, 837, 14, MUTED)

    def resource_icon(self, r, x, y):
        """Small silhouettes stay recognizable without relying on color or letters."""
        def polygon(color, points):
            self.polygon(color, [(x + px, y + py) for px, py in points])

        if r == "wood":
            self.line((119, 86, 50), (x, y + 2), (x, y + 11), 4)
            for top, width in ((-12, 7), (-7, 10), (-1, 12)):
                polygon((78, 157, 104), [(0, top), (-width, top + 10), (width, top + 10)])
                self.line((119, 187, 122), (x, y + top + 2), (x - width + 3, y + top + 8))
        elif r == "brick":
            for left, top in ((-11, -1), (1, -1), (-5, -9)):
                polygon((195, 106, 76), [(left, top), (left + 10, top), (left + 10, top + 8), (left, top + 8)])
                self.line((239, 155, 107), (x + left, y + top), (x + left + 9, y + top))
                self.line((128, 67, 52), (x + left, y + top + 7), (x + left + 10, y + top + 7))
        elif r == "wheat":
            self.line((211, 170, 77), (x - 1, y + 12), (x + 1, y - 12), 2)
            for height in (-8, -3, 2, 7):
                for side in (-1, 1):
                    polygon((235, 196, 100), [(0, height + 3), (side * 7, height), (side * 6, height - 4), (0, height - 1)])
        elif r == "sheep":
            for leg in (-6, 5):
                self.line((120, 123, 110), (x + leg, y + 4), (x + leg, y + 10), 2)
            for dx, dy, radius in ((-5, -1, 6), (1, -3, 7), (6, 1, 5), (-1, 3, 6)):
                self.circle((235, 236, 223), (x + dx, y + dy), radius)
            self.ellipse((105, 112, 107), (x + 6, y - 3, 7, 9))
            self.circle(WHITE, (x + 10, y - 1), 1)
        elif r == "ore":
            polygon((161, 179, 200), [(-12, 8), (-7, -5), (1, -11), (10, -4), (13, 8)])
            polygon((204, 218, 229), [(-7, -5), (1, -11), (1, 5), (-12, 8)])
            polygon((102, 127, 153), [(1, -11), (10, -4), (13, 8), (1, 5)])

    def resource_target(self, resource):
        column = RESOURCES.index(resource)
        return (218 + column * 154 + (self.width - W) / 2, 890 + self.height - H)

    def player_target(self, owner):
        order = self.game.setup_order[:len(self.game.players)]
        return (1065 + self.width - W, 146 + order.index(owner) * 66)

    def toggle_motion(self):
        self.pacing.reduced_motion = not self.pacing.reduced_motion
        self.skip_presentation()

    def skip_presentation(self):
        self.pacing.clear()
        self.pacing.advance(pg.time.get_ticks())
        self.schedule_bot()

    def draw_resource_bar(self):
        self.panel((45, 873, 950, 35), PANEL, 8)
        self.text("YOUR RESOURCES", 61, 884, 11, MUTED, bold=True)
        hand = self.pacing.hand_for(0, self.game)
        for column, resource in enumerate(RESOURCES):
            x = 195 + column * 154
            rect = pg.Rect(x, 875, 144, 31)
            hover = rect.move(self.offset).collidepoint(self.mouse())
            if hover:
                self.panel(rect, (38, 65, 70), 6)
            self.resource_icon(resource, x + 23, 890)
            self.text(hand[resource], x + 48, 878, 22, WHITE, bold=True)
            self.tooltips.append((rect.move(self.offset),
                f"{resource.title()}: {hand[resource]} in your hand.\n"
                f"Bank: {self.game.bank[resource]} available. Your bank/port rate: {self.game.ratio(0, resource)}:1."))

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
            self.text("Development cards will appear here.", x, 925, 15, MUTED)
        for card, count in counts.items():
            label = f"{CARD_NAMES[card]} ×{count}"
            width = max(150, self.font(16).size(label)[0] + 28)
            self.button(label, (x, 917, width, 32), lambda c=card: self.act("play", card=c), active=not self.pacing.blocks_input and g.actor == 0 and g.phase in ("roll", "main") and card in g.playable(0), small=True, tooltip=self.card_tooltip(card))
            x += width + 10

    def draw_log(self):
        self.text("TABLE JOURNAL", 1060, 710, 13, GOLD, bold=True)
        # Expanded journal opens on L; compact view keeps the board uncluttered.
        latest = self.pacing.log_for(self.game)
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
        self.button("2D board", (875, 582, 210, 34), lambda: self.set_perspective(False),
                    accent=not self.perspective, small=True,
                    tooltip="Use the classic illustrated board. Your current game is preserved.")
        self.button("3D board", (1100, 582, 210, 34), lambda: self.set_perspective(True),
                    accent=self.perspective, small=True,
                    tooltip="Use the perspective board with orbit, pan, and zoom. Your current game is preserved.")
        self.text("Island layout", 875, 625, 12, MUTED)
        self.button("Recommended" if self.recommended else "Random island", (875, 643, 225, 34), lambda: setattr(self, "recommended", not self.recommended), small=True)
        self.text("Island seed (blank = random)", 1121, 625, 11, MUTED)
        self.button(self.seed_text + ("|" if self.edit_seed else ""), (1121, 643, 189, 34), lambda: setattr(self, "edit_seed", True), small=True)
        self.button("Set sail", (875, 693, 435, 51), self.new_game, accent=True)
        self.button("Resume autosave", (875, 758, 435, 40), self.load)
        if self.started:
            self.button("Return to game", (875, 811, 210, 39), self.toggle_menu)
        self.button("Motion: Reduced" if self.pacing.reduced_motion else "Motion: Full",
                    (1100, 811, 210, 39), self.toggle_motion, small=True,
                    tooltip="Reduced motion uses short, static cues instead of rolling dice and flying resources.")
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
        self.tooltips = []
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
            self.button("Accept trade", (410, 616, 290, 48), lambda: self.act("respond", accept=True), active=all(self.game.players[0].hand[r] >= n for r, n in t["want"].items()), accent=True, tooltip="Exchange the offered resources." if all(self.game.players[0].hand[r] >= n for r, n in t["want"].items()) else "You do not have the resources requested by this trade.")
            self.button("Decline", (724, 616, 300, 48), lambda: self.act("respond", accept=False))
            self.button("Counteroffer", (410, 685, 614, 42), lambda: self.open_modal("counter"), active=not t["countered"], tooltip="Propose different terms." if not t["countered"] else "Only one counteroffer is allowed per negotiation.")
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
            reasons = []
            if give == receive:
                reasons.append("Choose different resources to give and receive.")
            if self.game.players[0].hand[give] < ratio:
                reasons.append(f"You need {ratio - self.game.players[0].hand[give]} more {give}.")
            if not self.game.bank[receive]:
                reasons.append(f"The bank has no {receive} left.")
            trade_tooltip = f"Trade {ratio} {give} for 1 {receive}." + ("\n" + "\n".join(reasons) if reasons else "")
            self.button("Trade", (410, 716, 612, 46), lambda: self.act("bank_trade", give=give, receive=receive), active=give != receive and self.game.players[0].hand[give] >= ratio and self.game.bank[receive] > 0, accent=True, tooltip=trade_tooltip)
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
        self.tooltips = []
        self.pacing.advance(pg.time.get_ticks(), paused=self.menu or self.modal is not None)
        self.canvas.fill(INK)
        if self.started or not self.menu:
            self.draw_board()
            if not self.menu:
                self.pacing.draw_board(self)
        self.draw_header()
        if not self.menu:
            self.draw_view_controls()
        if self.menu:
            with self.shifted((self.width - W) / 2, (self.height - H) / 2):
                self.draw_menu()
        else:
            with self.shifted(self.width - W):
                self.draw_players()
                self.draw_actions()
            with self.shifted((self.width - W) / 2, self.height - H):
                self.draw_board_status()
                self.draw_resource_bar()
            with self.shifted(y=self.height - H):
                self.draw_hand()
            with self.shifted(self.width - W, self.height - H):
                self.draw_log()
        if not self.menu:
            self.pacing.draw_overlay(self)
        if self.modal:
            with self.shifted((self.width - W) / 2, (self.height - H) / 2):
                self.draw_modal()
        if self.toast and pg.time.get_ticks() < self.toast_until:
            self.panel((300, 103, 820, 48), (81, 62, 44), 10, GOLD)
            self.wrap(self.toast, 317, 116, 786, 16, LIGHT, 1)
        self.draw_tooltip()
        _, viewport = self.viewport()
        self.window.fill((10, 23, 29))
        self.window.blit(self.canvas, viewport.topleft)
        pg.display.flip()

    def board_click(self, pos):
        g = self.game
        if self.menu or self.modal or self.pacing.blocks_input or g.actor != 0 or g.phase == "game_over":
            return
        if self.perspective:
            self.perspective_board_click(pos)
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
        self.pacing.advance(pg.time.get_ticks(), paused=self.menu or self.modal is not None)
        if self.menu or g.winner is not None:
            return
        if self.pacing.busy:
            self.schedule_bot()
            return
        if g.actor == 0:
            if g.phase == "trade" and self.modal is None:
                self.open_modal("trade")
            return
        if self.modal is not None or self.autosave_error:
            self.schedule_bot()
            return
        if pg.time.get_ticks() >= self.next_bot:
            try:
                before = self.pacing.snapshot(g)
                command = bots.step(g)
                self.pacing.observe(before, g, command or {}, pg.time.get_ticks(), self.speed)
                self.autosave()
            except (RuleError, ValueError) as exc:
                self.autosave_error = True
                self.notify(f"Bot paused: {exc}. Save and reload to retry.", 15000)
            self.schedule_bot()
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
                elif event.type == pg.KEYDOWN and event.key == pg.K_SPACE and self.pacing.busy and not self.menu and not self.modal:
                    self.skip_presentation()
                elif self.camera_event(event):
                    pass
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
