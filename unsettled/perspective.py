"""Software-rendered 3D board experiment; no graphics-driver dependency.

Coordinates stay in board units. Camera projection is shared by geometry,
labels, and picking so orbiting never changes a legal placement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from functools import lru_cache

import pygame as pg


@dataclass
class Camera:
    yaw: float = -.18
    pitch: float = .92
    zoom: float = .9
    pan: list[float] = field(default_factory=lambda: [0., 0.])

    def projector(self, center):
        # Prepare once per mesh pass instead of recomputing trigonometry per vertex.
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        ox, oy = center[0] + self.pan[0], center[1] + self.pan[1]
        focal = 1190 * self.zoom

        def project(point):
            x, y, z = point
            x, y = x * c - y * s, x * s + y * c
            depth = 1250 - y * cp - z * sp
            factor = focal / max(100, depth)
            return (ox + x * factor, oy + (y * sp - z * cp) * factor, depth)

        return project

    def project(self, point, center):
        return self.projector(center)(point)

    def unproject(self, point, center, z=0):
        """Intersect a screen ray with a horizontal plane for accurate picking."""
        u = (point[0] - center[0] - self.pan[0]) / (1190 * self.zoom)
        v = (point[1] - center[1] - self.pan[1]) / (1190 * self.zoom)
        c, s = math.cos(self.pitch), math.sin(self.pitch)
        denominator = s + v * c
        if denominator <= 1e-6:
            return None  # This ray points above the ground-plane horizon.
        y = (v * (1250 - z * s) + z * c) / denominator
        x = u * (1250 - y * c - z * s)
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return (x * c + y * s, -x * s + y * c)

    def orbit(self, dx, dy):
        self.yaw = (self.yaw + dx * .008) % math.tau
        self.pitch = max(.48, min(1.4, self.pitch + dy * .006))

    def magnify(self, steps):
        self.zoom = max(.55, min(2.2, self.zoom * 1.12 ** max(-20, min(20, steps))))


def hexagon(x, y, radius, z=0, angle=math.pi / 6):
    return [(x + radius * math.cos(angle + i * math.pi / 3),
             y + radius * math.sin(angle + i * math.pi / 3), z) for i in range(6)]


def tone(color, amount):
    target = 255 if amount > 0 else 0
    return tuple(round(c + (target - c) * abs(amount)) for c in color)


@dataclass(frozen=True)
class Crown:
    """An organic ellipsoid, shaded as a sphere rather than flat triangle faces."""
    center: tuple
    radius: float
    color: tuple
    seed: int
    stretch: float = 1.0
    texture: str = "leaves"


@lru_cache(maxsize=512)
def shaded_crown(color, seed, light_x, light_y, texture):
    size = 64
    surface = pg.Surface((size, size), pg.SRCALPHA)
    rng = random.Random(seed)
    # Sphere normals create continuous lighting, with fine material variation.
    light_z = math.sqrt(max(.05, 1 - light_x * light_x - light_y * light_y))
    for py in range(size):
        y = (py + .5 - size / 2) / (size / 2)
        for px in range(size):
            x = (px + .5 - size / 2) / (size / 2)
            squared = x * x + y * y
            if squared >= 1:
                continue
            z = math.sqrt(1 - squared)
            diffuse = max(0, x * light_x + y * light_y + z * light_z)
            noise = rng.uniform(-.12, .12) if texture == "leaves" else rng.uniform(-.04, .04)
            mottling = .06 * math.sin(x * 31 + seed) * math.sin(y * 37)
            strength = .46 + .62 * diffuse + noise + mottling
            alpha = min(255, round((1 - squared) * 2400))
            surface.set_at((px, py), (*[max(0, min(255, round(c * strength))) for c in color], alpha))
    if texture == "leaves":
        for _ in range(140):
            x, y = rng.randrange(7, 57), rng.randrange(7, 57)
            if (x - 32) ** 2 + (y - 32) ** 2 < 26 ** 2:
                base = surface.get_at((x, y))
                tint = tuple(min(255, c + rng.randrange(7, 23)) for c in base[:3])
                pg.draw.ellipse(surface, (*tint, 220), (x, y, 2, 1))
    return surface


class Scene:
    def __init__(self):
        self.key = None
        self.terrain = []
        self.texture_key = None
        self.ground_texture = None
        self.rotated_key = None
        self.rotated_texture = None
        self.projected_key = None
        self.projected_texture = None
        self.scenery_key = None
        self.scenery = None

    @staticmethod
    def center(tile):
        return (math.sqrt(3) * (tile['q'] + tile['r'] / 2) * 79, 1.5 * tile['r'] * 79)

    @staticmethod
    def box(faces, x, y, z, width, length, height, color):
        top = [(x - width / 2, y - length / 2, z + height),
               (x + width / 2, y - length / 2, z + height),
               (x + width / 2, y + length / 2, z + height),
               (x - width / 2, y + length / 2, z + height)]
        for i in range(4):
            a, b = top[i], top[(i + 1) % 4]
            faces.append(([(*a[:2], z), (*b[:2], z), b, a], tone(color, (-.24, -.1, .05, -.32)[i])))
        faces.append((top, tone(color, .18)))

    @staticmethod
    def peak(faces, x, y, z, radius, height, color, sides=6, snow=False):
        ring = [(x + radius * math.cos(i * math.tau / sides),
                 y + radius * math.sin(i * math.tau / sides), z) for i in range(sides)]
        tip = (x - radius * .15, y, z + height)
        for i, a in enumerate(ring):
            b = ring[(i + 1) % sides]
            shade = (-.22, -.1, .1, .22, -.08, -.3)[i % 6]
            color_i = tone(color, shade)
            if snow:
                aa = tuple(tip[j] + (a[j] - tip[j]) * .32 for j in range(3))
                bb = tuple(tip[j] + (b[j] - tip[j]) * .32 for j in range(3))
                faces.append(([a, b, bb, aa], color_i))
                faces.append(([aa, bb, tip], tone((229, 234, 226), shade)))
            else:
                faces.append(([a, b, tip], color_i))

    @staticmethod
    def mountain(faces, cx, cy, rng, desert=False, clay=False):
        """A continuous height field with irregular ridges and weathered lighting."""
        peaks = [(rng.uniform(-34, 34), rng.uniform(-34, 22),
                  rng.uniform(18, 25), rng.uniform(28, 57)) for _ in range(4)]
        if desert:
            peaks = [(-24, -12, 26, 9), (19, 16, 30, 13), (28, -28, 20, 7)]
        elif clay:
            peaks = [(x, y, width, height * .48) for x, y, width, height in peaks]

        def height(x, y):
            distance = max(x * math.cos(i * math.pi / 3) + y * math.sin(i * math.pi / 3)
                           for i in range(6))
            fade = max(0, min(1, (56 - distance) / 13))
            bumps = [h * math.exp(-((x - px) ** 2 + (y - py) ** 2) / (width * width * .7))
                     for px, py, width, h in peaks]
            ripple = (math.sin(x * .23 + y * .14) + math.sin(x * .11 - y * .29)) * (.4 if desert else .8)
            return max(.4, (max(bumps) + ripple) * fade)

        vertices = {}
        step = 5
        for row, y in enumerate(range(-56, 57, step)):
            for col, x in enumerate(range(-56, 57, step)):
                if max(x * math.cos(i * math.pi / 3) + y * math.sin(i * math.pi / 3)
                       for i in range(6)) > 57:
                    continue
                z = height(x, y)
                gx = (height(x + 1, y) - height(x - 1, y)) / 2
                gy = (height(x, y + 1) - height(x, y - 1)) / 2
                light = max(.25, (-gx * -.48 - gy * -.45 + .76) / math.sqrt(1 + gx * gx + gy * gy))
                stone = (139, 145, 145)
                if desert:
                    stone = (220, 184, 119)
                elif clay:
                    strata = math.sin(z * 1.4) * 9
                    stone = (179 + strata, 111 + strata, 73 + strata)
                elif z > 27 + math.sin(x * .17) * 4 + math.sin(y * .21) * 3:
                    stone = (231, 235, 227)
                elif z < 4:
                    stone = (142, 146, 116)
                grain = rng.uniform(-.012, .012)
                color = tuple(max(0, min(255, round(c * (.60 + light * .48 + grain)))) for c in stone)
                vertices[row, col] = ((cx + x, cy + y, z), color)
        for (row, col), a in vertices.items():
            b, c, d = (vertices.get(k) for k in ((row, col + 1), (row + 1, col), (row + 1, col + 1)))
            for triangle in ((a, b, c), (b, d, c)):
                if all(triangle):
                    points = [v[0] for v in triangle]
                    color = tuple(round(sum(v[1][i] for v in triangle) / 3) for i in range(3))
                    faces.append((points, color))

    def terrain_faces(self, board):
        key = tuple((t['q'], t['r'], t['resource']) for t in board.hexes)
        if self.key == key:
            return self.terrain
        faces = []
        for index, tile in enumerate(board.hexes):
            cx, cy = self.center(tile)
            rng = random.Random(771 + index * 31)
            kind = tile['resource']
            if kind in ('ore', 'brick', 'desert'):
                self.mountain(faces, cx, cy, rng, desert=kind == 'desert', clay=kind == 'brick')
                continue
            count = 20 if kind == 'wood' else 11
            for i in range(count):
                # Scatter vegetation over the tile instead of a regular ring.
                while True:
                    x, y = rng.uniform(-47, 47), rng.uniform(-47, 47)
                    edge = max(x * math.cos(j * math.pi / 3) + y * math.sin(j * math.pi / 3) for j in range(6))
                    if edge < 48 and x * x + y * y > 23 ** 2:
                        break
                x, y = cx + x, cy + y
                if kind == 'wood':
                    height = rng.uniform(18, 33)
                    self.box(faces, x, y, 1, 2, 2, height * .65, (95, 76, 49))
                    palette = [(61, 108, 53), (68, 122, 62), (48, 100, 66), (91, 127, 61)]
                    color = palette[i % len(palette)]
                    for j in range(3):
                        angle = j * math.tau / 3 + rng.uniform(-.4, .4)
                        center = (x + math.cos(angle) * 4, y + math.sin(angle) * 4,
                                  height * .65 + rng.uniform(-2, 4))
                        faces.append(Crown(center, rng.uniform(7, 10), color, i % 4, 1.15))
                    faces.append(Crown((x, y, height), 7, tone(color, .06), i % 4))
                elif kind == 'sheep':
                    # Rounded wool, dark heads and small legs rather than blocks.
                    for dx in (-2, 2):
                        self.box(faces, x + dx, y, 1, 1, 3, 2.5, (91, 82, 65))
                    faces.append(Crown((x, y, 5), 4.3, (233, 227, 209), i % 4, .8, 'wool'))
                    faces.append(Crown((x, y - 4, 4.5), 2, (69, 67, 56), 0, 1, 'wool'))
                elif kind == 'wheat':
                    # Slim stalks and seed heads rise above the painted crop rows.
                    for j in range(7):
                        sx, sy = x + rng.uniform(-5, 5), y + rng.uniform(-6, 6)
                        h = rng.uniform(4, 8)
                        faces.append(([(sx, sy, 1), (sx + .45, sy, h), (sx + 1, sy, 1)], (177, 137 + i % 3 * 8, 58)))
                        faces.append(Crown((sx, sy, h), .9, (224, 186, 101), j % 2, 1.8, 'wool'))
        self.key, self.terrain = key, faces
        return faces

    def draw_ground_texture(self, app):
        """Project the illustrated ground through horizontal perspective scanlines.

        The yaw rotation happens in world space. Each scanline then uses its
        actual camera depth, keeping texture, models, and picking aligned.
        """
        key = (tuple((t['q'], t['r'], t['resource']) for t in app.game.board.hexes), id(app.atlas))
        if self.texture_key != key:
            texture = pg.Surface((1800, 1800), pg.SRCALPHA)
            for tile in app.game.board.hexes:
                x, y = self.center(tile)
                art = pg.transform.smoothscale(app.tile(tile['resource']), (324, 324))
                texture.blit(art, (round((x + 450 - 81) * 2), round((y + 450 - 81) * 2)))
            self.texture_key, self.ground_texture = key, texture
            self.rotated_key = None
        angle = app.camera.yaw
        if self.rotated_key != (key, angle):
            self.rotated_texture = pg.transform.rotate(self.ground_texture, -math.degrees(angle))
            self.rotated_key = (key, angle)
        camera = app.camera
        projection_key = (self.rotated_key, camera.pitch, camera.zoom, tuple(camera.pan),
                          app.scale, app.width, app.height)
        if self.projected_key != projection_key:
            surface = pg.Surface(app.canvas.get_size(), pg.SRCALPHA)
            source = self.rotated_texture
            sw, sh = source.get_size()
            center = app.camera_center()
            ox = (center[0] + camera.pan[0]) * app.scale
            oy = (center[1] + camera.pan[1]) * app.scale
            focal = 1190 * camera.zoom * app.scale
            cp, sp = math.cos(camera.pitch), math.sin(camera.pitch)
            clip = app.rect(app.board_viewport())
            surface.set_clip(clip)
            for row in range(max(0, clip.top), min(surface.get_height(), clip.bottom)):
                v = (row + .5 - oy) / focal
                denominator = sp + v * cp
                if denominator <= 1e-6:
                    continue
                world_y = v * 1250 / denominator
                source_y = round(world_y * 2 + sh / 2)
                if not 0 <= source_y < sh:
                    continue
                factor = focal / (1250 - world_y * cp)
                width = max(1, round(sw / 2 * factor))
                strip = source.subsurface((0, source_y, sw, 1))
                surface.blit(pg.transform.scale(strip, (width, 1)), (round(ox - width / 2), row))
            surface.set_clip(None)
            self.projected_key, self.projected_texture = projection_key, surface
        app.canvas.blit(self.projected_texture, (0, 0))

    def draw_faces(self, app, faces):
        projected = []
        camera = app.camera
        project = camera.projector(app.camera_center())
        native_point = app.point
        for face in faces:
            if isinstance(face, Crown):
                vertex = project(face.center)
                projected.append((vertex[2], face, vertex))
            else:
                points, color = face
                vertices = [project(p) for p in points]
                projected.append((sum(p[2] for p in vertices) / len(vertices),
                                  [native_point(p[:2]) for p in vertices], color))
        lx = -.48 * math.cos(camera.yaw) + .45 * math.sin(camera.yaw)
        ly = (-.48 * math.sin(camera.yaw) - .45 * math.cos(camera.yaw)) * math.sin(camera.pitch) - .76 * math.cos(camera.pitch)
        # Quantization shares shaded materials between trees while orbiting.
        lx, ly = round(lx * 8) / 8, max(-.9, min(.9, round(ly * 8) / 8))
        for _, points, color in sorted(projected, key=lambda item: item[0], reverse=True):
            if isinstance(points, Crown):
                vertex, crown = color, points
                factor = 1190 * camera.zoom * app.scale / vertex[2]
                radius = crown.radius * factor
                vertical = math.sqrt(math.sin(camera.pitch) ** 2 + (crown.stretch * math.cos(camera.pitch)) ** 2)
                size = (max(2, round(radius * 2)), max(2, round(radius * 2 * vertical)))
                sprite = shaded_crown(crown.color, crown.seed, lx, ly, crown.texture)
                sprite = pg.transform.smoothscale(sprite, size)
                app.canvas.blit(sprite, sprite.get_rect(center=native_point(vertex[:2])))
            else:
                pg.draw.polygon(app.canvas, color, points)

    def draw(self, app):
        # Cache scenery independently of animated legal-placement guides and UI.
        # Orbiting changes the key; an idle board needs only one image blit.
        board = app.game.board
        camera = app.camera
        key = (tuple((t['q'], t['r'], t['resource'], t['number']) for t in board.hexes),
               tuple(sorted(board.ports.items())), tuple(sorted(app.game.roads.items())),
               tuple((v, tuple(piece)) for v, piece in sorted(app.game.buildings.items())),
               app.game.robber, camera.yaw, camera.pitch, camera.zoom, tuple(camera.pan),
               app.scale, app.canvas.get_size(), id(app.atlas))
        if key != self.scenery_key:
            original = app.canvas
            app.canvas = pg.Surface(original.get_size(), pg.SRCALPHA)
            app.canvas.set_clip(original.get_clip())
            try:
                self.draw_scenery(app)
                self.scenery = app.canvas
                self.scenery_key = key
            finally:
                app.canvas = original
        app.canvas.blit(self.scenery, (0, 0))
        self.draw_guides(app)

    def draw_scenery(self, app):
        from .ui import COLORS, GOLD, INK, LIGHT, TERRAIN, TILE_ORDER
        board = app.game.board
        # Draw the tabletop base first; all relief geometry stands above it.
        base = []
        ring = hexagon(0, 0, 435, -12, 0)
        for i, a in enumerate(ring):
            b = ring[(i + 1) % 6]
            base.append(([a, b, (b[0], b[1], -30), (a[0], a[1], -30)], (91, 68, 41)))
        self.draw_faces(app, base)
        for radius, color in ((435, (151, 104, 51)), (431, GOLD), (420, (94, 68, 38)),
                              (414, (222, 183, 111)), (407, (40, 89, 132))):
            app.polygon(color, [app.project_world(p) for p in hexagon(0, 0, radius, -10, 0)])
        for radius in range(403, 273, -3):
            t = (403 - radius) / 130
            color = tuple(round(a + (b - a) * t) for a, b in zip((42, 100, 146), (135, 198, 228)))
            app.polygon(color, [app.project_world(p) for p in hexagon(0, 0, radius, -9, 0)])
        ground = []
        for tile in board.hexes:
            x, y = self.center(tile)
            outer = hexagon(x, y, 78, 0)
            for i, a in enumerate(outer):
                b = outer[(i + 1) % 6]
                ground.append(([a, b, (b[0], b[1], -7), (a[0], a[1], -7)], (151, 119, 76)))
            ground.append((outer, (223, 189, 132)))
            ground.append((hexagon(x, y, 68, .2), tone(TERRAIN[TILE_ORDER.index(tile['resource'])], .2)))
        self.draw_faces(app, ground)
        self.draw_ground_texture(app)
        # Foam follows only the exterior edges, on the sea plane below the beach.
        from collections import Counter
        counts = Counter(tuple(sorted((vs[i], vs[(i + 1) % 6]))) for vs in board.hex_vertices for i in range(6))
        for vs in board.hex_vertices:
            for i, v in enumerate(vs):
                w = vs[(i + 1) % 6]
                if counts[tuple(sorted((v, w)))] != 1:
                    continue
                a, b = [tuple(c * 79 for c in board.vertices[k]) for k in (v, w)]
                dx, dy = b[0] - a[0], b[1] - a[1]
                nx, ny = dy / 79, -dx / 79
                for distance in (5, 12):
                    for j in range(20):
                        if (j + v) % 7 == 0:
                            continue
                        points = []
                        for t in (j / 20, (j + 1) / 20):
                            d = distance + math.sin(t * 20 + v) * 1.5
                            points.append(app.project_world((a[0] + dx * t + nx * d, a[1] + dy * t + ny * d, -8)))
                        app.line((219, 238, 224), *points, 1)
        faces = list(self.terrain_faces(board))
        for edge, owner in app.game.roads.items():
            a, b = [tuple(c * 79 for c in board.vertices[v]) for v in board.edges[edge]]
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            nx, ny = -dy / length * 3.5, dx / length * 3.5
            top = [(a[0] + dx * .1 + nx, a[1] + dy * .1 + ny, 5),
                   (b[0] - dx * .1 + nx, b[1] - dy * .1 + ny, 5),
                   (b[0] - dx * .1 - nx, b[1] - dy * .1 - ny, 5),
                   (a[0] + dx * .1 - nx, a[1] + dy * .1 - ny, 5)]
            faces.append((top, COLORS[owner]))
            for i, a3 in enumerate(top):
                b3 = top[(i + 1) % 4]
                faces.append(([a3, b3, (b3[0], b3[1], 0), (a3[0], a3[1], 0)], tone(COLORS[owner], -.3)))
        for vertex, (owner, size) in app.game.buildings.items():
            x, y = (c * 79 for c in board.vertices[vertex])
            self.box(faces, x, y, 0, 15, 16, 11, COLORS[owner])
            # A pitched roof is world geometry, so it turns with the camera.
            faces.extend([([(x - 9, y - 10, 11), (x + 9, y - 10, 11), (x, y - 10, 21)], tone(COLORS[owner], .15)),
                          ([(x - 9, y + 10, 11), (x + 9, y + 10, 11), (x, y + 10, 21)], tone(COLORS[owner], -.15)),
                          ([(x - 9, y - 10, 11), (x - 9, y + 10, 11), (x, y + 10, 21), (x, y - 10, 21)], tone(COLORS[owner], .3)),
                          ([(x + 9, y - 10, 11), (x + 9, y + 10, 11), (x, y + 10, 21), (x, y - 10, 21)], tone(COLORS[owner], -.2))])
            if size == 2:
                self.box(faces, x + 9, y + 3, 0, 10, 13, 27, COLORS[owner])
                self.peak(faces, x + 9, y + 3, 27, 9, 9, tone(COLORS[owner], .25), sides=4)
        for edge in board.ports:
            a, b = [tuple(c * 79 for c in board.vertices[v]) for v in board.edges[edge]]
            x, y = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            length = math.hypot(x, y)
            nx, ny = x / length, y / length
            tx, ty = -ny, nx
            for distance in range(0, 36, 5):
                plank = [(x + nx * d + tx * side, y + ny * d + ty * side, 1)
                         for d, side in ((distance, -9), (distance + 4, -9), (distance + 4, 9), (distance, 9))]
                faces.append((plank, (185, 133 + distance % 3 * 8, 78)))
            x, y = x + nx * 51, y + ny * 51
            self.box(faces, x, y, -6, 12, 25, 6, (119, 79, 47))
            self.box(faces, x, y, 0, 1.5, 1.5, 25, (133, 103, 63))
            faces.append(([(x - tx * 11, y - ty * 11, 2), (x + tx * 10, y + ty * 10, 2), (x, y, 25)], (246, 232, 193)))
        rx, ry = self.center(board.hexes[app.game.robber])
        self.box(faces, rx + 24, ry - 10, 1, 10, 10, 16, (49, 53, 60))
        self.peak(faces, rx + 24, ry - 10, 17, 7, 8, (67, 70, 76))
        self.draw_faces(app, faces)
        # Screen-facing tokens preserve legibility during orbit and zoom.
        for i, tile in enumerate(board.hexes):
            if not tile['number']:
                continue
            x, y = app.hex_center(i)
            factor = app.camera.project((*self.center(tile), 0), app.camera_center())[2]
            radius = max(12, min(24, 20 * app.camera.zoom * 1250 / factor))
            app.circle((112, 93, 62), (x, y + 2), radius + 1)
            app.circle((244, 227, 187), (x, y), radius)
            app.text(tile['number'], x, y - 2, max(15, radius * 1.15), (164, 66, 48) if tile['number'] in (6, 8) else INK, bold=True, center=True)
            dots = 6 - abs(7 - tile['number'])
            for j in range(dots):
                app.circle((164, 66, 48) if tile['number'] in (6, 8) else INK, (x + (j - (dots - 1) / 2) * 4, y + radius * .57), .8)
        for edge, kind in board.ports.items():
            a, b = [tuple(c * 79 for c in board.vertices[v]) for v in board.edges[edge]]
            x, y = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            d = math.hypot(x, y)
            x, y = app.project_world((x * (1 + 78 / d), y * (1 + 78 / d), 0))
            app.panel((x - 29, y - 9, 58, 19), INK, 5, GOLD)
            app.text('3:1' if kind == 'any' else kind[:2].upper() + ' 2:1', x, y, 11, GOLD, center=True)
    def draw_guides(self, app):
        from .ui import GOLD, LIGHT
        board = app.game.board
        if app.menu or app.game.actor != 0 or app.game.phase == 'game_over':
            return
        mode = app.active_mode()
        if mode in ('settlement', 'city'):
            sites = app.game.city_sites(0) if mode == 'city' else app.game.settlement_sites(0, app.game.phase == 'setup_settlement')
            for v in sites:
                app.draw_placement_marker(app.screen_point(v), compact=True)
        elif mode == 'road':
            for edge in app.game.road_sites(0, app.game.setup_vertex if app.game.phase == 'setup_road' else None):
                a, b = [app.screen_point(v) for v in board.edges[edge]]
                app.line(GOLD, a, b, 3)
        elif app.game.phase == 'robber':
            for i, vertices in enumerate(board.hex_vertices):
                if i != app.game.robber:
                    app.polygon(GOLD, [app.screen_point(v) for v in vertices], 2)
