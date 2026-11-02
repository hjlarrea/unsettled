"""Camera and real UI placement checks for the optional 3D board."""
import math
import os

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import pygame as pg
import pytest

from unsettled.perspective import Camera, hexagon
from unsettled.ui import App


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr('unsettled.persistence.save_dir', lambda: tmp_path)
    instance = App(seed=1, perspective=True)
    instance.menu = False
    yield instance
    pg.quit()


@pytest.mark.parametrize('yaw,pitch,zoom', [(0, .48, .55), (1.2, .8, 1), (3.5, 1.4, 2.2)])
def test_camera_ray_intersects_projected_ground(yaw, pitch, zoom):
    camera = Camera(yaw=yaw, pitch=pitch, zoom=zoom, pan=[23, -41])
    for x, y in ((0, 0), (-310, 170), (250, -270), (110, 330)):
        for z in (0, -8):
            screen = camera.project((x, y, z), (520, 460))
            assert camera.unproject(screen[:2], (520, 460), z) == pytest.approx((x, y))
    low = camera.project((0, 0, 0), (520, 460))
    high = camera.project((0, 0, 50), (520, 460))
    assert high[1] < low[1]


@pytest.mark.parametrize('yaw,pitch,zoom', [(0, .7, .65), (1.5, 1.2, 1), (3.2, .9, 1.4)])
def test_setup_placement_after_orbit_zoom_and_pan(app, yaw, pitch, zoom):
    app.camera = Camera(yaw=yaw, pitch=pitch, zoom=zoom, pan=[-20, 15])
    g = app.game
    g.current = 0
    g.setup_order = [0, 1, 2, 3, 3, 2, 1, 0]
    vertex = min(g.settlement_sites(0, True), key=lambda v: math.dist(app.screen_point(v), app.camera_center()))
    app.board_click(app.screen_point(vertex))
    assert g.buildings[vertex] == [0, 1]
    assert g.phase == 'setup_road'
    edge = g.road_sites(0, vertex)[0]
    a, b = [g.board.vertices[v] for v in g.board.edges[edge]]
    midpoint = ((a[0] + b[0]) * 79 / 2, (a[1] + b[1]) * 79 / 2, 0)
    app.board_click(app.project_world(midpoint))
    assert g.roads[edge] == 0


def test_robber_pick_and_view_switch_preserve_rules(app):
    g = app.game
    g.current, g.phase = 0, 'robber'
    app.camera.yaw = 2.5
    app.camera.zoom = 1.2
    target = next(i for i in (9, 8, 10) if i != g.robber)
    app.board_click(app.hex_center(target))
    assert g.robber == target
    before = g.to_dict()
    app.toggle_perspective()
    app.render()
    app.toggle_perspective()
    app.render()
    assert g.to_dict() == before


def test_camera_events_and_overlay_isolation(app, monkeypatch):
    app.render()
    monkeypatch.setattr(app, 'mouse', lambda pos=None: (500, 450) if pos is None else pos)
    before = app.game.to_dict()
    down = pg.event.Event(pg.MOUSEBUTTONDOWN, button=2, pos=(500, 450))
    monkeypatch.setattr(pg.key, 'get_mods', lambda: 0)
    yaw = app.camera.yaw
    assert app.camera_event(down)
    assert app.camera_event(pg.event.Event(pg.MOUSEMOTION, rel=(30, -20)))
    assert app.camera.yaw == pytest.approx((yaw - 30 / app.scale * .008) % math.tau)
    assert app.camera_event(pg.event.Event(pg.MOUSEBUTTONUP, button=2))
    monkeypatch.setattr(pg.key, 'get_mods', lambda: pg.KMOD_SHIFT)
    app.camera_event(down)
    app.camera_event(pg.event.Event(pg.MOUSEMOTION, rel=(25, 10)))
    assert app.camera.pan == pytest.approx([-25 / app.scale, 10 / app.scale])
    app.camera_event(pg.event.Event(pg.MOUSEBUTTONUP, button=2))
    zoom = app.camera.zoom
    wheel = pg.event.Event(pg.MOUSEWHEEL, y=1, flipped=False)
    assert app.camera_event(wheel)
    assert app.camera.zoom > zoom
    app.camera_event(pg.event.Event(pg.KEYDOWN, key=pg.K_HOME))
    assert app.camera == Camera()
    monkeypatch.setattr(app, 'mouse', lambda pos=None: (app.width - 100, 500))
    assert not app.camera_event(wheel)
    assert app.camera == Camera()
    app.open_modal('journal')
    assert not app.camera_event(down)
    assert not app.camera_event(wheel)
    assert app.camera == Camera()
    assert app.game.to_dict() == before


@pytest.mark.parametrize('size', [(720, 480), (1440, 960), (2560, 1080), (1280, 1024)])
def test_3d_render_framing_and_resize_preserve_game(app, size):
    app.window = pg.display.set_mode(size)
    app.sync_canvas()
    g = app.game
    g.buildings[0] = [0, 2]
    g.roads[0] = 0
    before = g.to_dict()
    app.render()
    rect = app.board_viewport()
    for point in hexagon(0, 0, 435, -30, 0):
        assert rect.collidepoint(app.project_world(point))
    first = pg.image.tobytes(app.canvas, 'RGB')
    app.camera.orbit(90, -30)
    app.render()
    assert pg.image.tobytes(app.canvas, 'RGB') != first
    assert app.canvas.get_clip() == app.canvas.get_rect()
    assert g.to_dict() == before


@pytest.mark.parametrize('yaw', [0, 1.1, 3.7])
def test_ground_texture_tracks_world_positions_during_orbit(app, monkeypatch, yaw):
    from unsettled.ui import TILE_ORDER
    app.window = pg.display.set_mode((1440, 960))
    app.sync_canvas()
    colors = {kind: (35 + i * 30, 85 + i * 12, 180 - i * 20)
              for i, kind in enumerate(TILE_ORDER)}

    def painted_tile(kind):
        surface = pg.Surface((162, 162), pg.SRCALPHA)
        pg.draw.polygon(surface, colors[kind],
                        [(81 + 78 * math.cos(math.pi / 6 + i * math.pi / 3),
                          81 + 78 * math.sin(math.pi / 6 + i * math.pi / 3)) for i in range(6)])
        return surface

    monkeypatch.setattr(app, 'tile', painted_tile)
    app.camera.yaw = yaw
    app.camera.zoom = 1.1
    app.camera.pan = [15, -8]
    app.scene.draw_ground_texture(app)
    for i, tile in enumerate(app.game.board.hexes):
        assert app.canvas.get_at(app.point(app.hex_center(i)))[:3] == colors[tile['resource']]


def test_scenery_cache_updates_after_building_and_camera_changes(app):
    app.game.current, app.game.phase = 0, 'main'
    app.render()
    first = app.scene.scenery
    app.render()
    assert app.scene.scenery is first
    app.game.buildings[0] = [0, 1]
    app.render()
    built = app.scene.scenery
    assert built is not first
    assert pg.image.tobytes(built, 'RGBA') != pg.image.tobytes(first, 'RGBA')
    app.camera.orbit(30, 0)
    app.render()
    assert pg.image.tobytes(app.scene.scenery, 'RGBA') != pg.image.tobytes(built, 'RGBA')
