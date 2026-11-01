"""Real Pygame rendering/input paths under SDL's offscreen driver."""
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
import pygame as pg
import pytest
from unsettled.ui import App
from unsettled.engine import Game
from unsettled import bots


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr("unsettled.persistence.save_dir", lambda: tmp_path)
    a = App(seed=1)
    yield a
    pg.quit()


def test_menu_new_game_and_resizing_coordinates(app):
    app.render()
    assert len(app.buttons) > 5
    app.bot_count = 2
    app.difficulties = ["Easy", "Standard", "Standard"]
    app.new_game()
    assert not app.menu
    assert len(app.game.players) == 3
    assert app.game.players[1].difficulty == "Easy"
    assert app.game.players[2].difficulty == "Standard"
    app.render()
    for size in ((720, 480), (1200, 800), (1440, 960)):
        app.window = pg.display.set_mode(size)
        scale = min(size[0] / 1440, size[1] / 960)
        point = (520 * scale + (size[0] - 1440 * scale) / 2, 424 * scale + (size[1] - 960 * scale) / 2)
        assert app.mouse(point) == pytest.approx((520, 424))


def test_board_click_setup(app):
    app.menu = False
    g = app.game
    g.current = g.setup_order[0] = g.setup_order[-1] = 0
    # Preserve a valid snake order with the human first.
    g.setup_order = [0, 1, 2, 3, 3, 2, 1, 0]
    v = g.settlement_sites(0, True)[0]
    app.board_click(app.screen_point(v))
    assert g.buildings[v] == [0, 1]
    assert g.phase == "setup_road"
    e = g.road_sites(0, v)[0]
    a, b = [app.screen_point(v) for v in g.board.edges[e]]
    app.board_click(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    assert g.roads[e] == 0


def test_bot_offers_always_pause_for_human(app):
    app.menu = False
    g = app.game
    g.phase, g.current, g.turn = "main", 1, 5
    g.players[1].hand["wood"] = 2
    g.bank["wood"] -= 2
    g.command(1, "offer", target=0, give={"wood": 1}, want={"ore": 1})
    before = g.to_dict()
    for _ in range(5):
        app.update()
    assert g.to_dict() == before
    assert app.modal["kind"] == "trade"
    app.render()
    assert app.act("respond", accept=False)
    assert g.phase == "main"
    assert app.modal is None


def test_resource_controls_and_trade_errors(app):
    app.menu = False
    app.game.current = 0
    app.game.phase = "main"
    app.open_modal("offer")
    app.change("give", "wood", 1)
    assert app.modal["give"]["wood"] == 0
    assert not app.act("offer", target=1, give={"wood": 1}, want={"ore": 1})
    assert app.modal is not None
    assert "cannot offer" in app.toast
    for kind in ("offer", "bank", "discard", "plenty", "monopoly", "journal"):
        app.open_modal(kind)
        app.render()
        assert app.buttons


def test_manual_save_load_and_invalid_load_keep_game(app, tmp_path):
    app.new_game()
    app.manual_save()
    old = app.game.to_dict()
    app.game.note("This should disappear on load.")
    app.load(True)
    assert app.game.to_dict() == old
    current = app.game
    (tmp_path / "manual.json").write_text("not json")
    app.load(True)
    assert app.game is current
    assert "Cannot load save" in app.toast


@pytest.mark.parametrize("opponents", [2, 3])
def test_full_game_through_ui_action_paths(app, monkeypatch, opponents):
    app.game = Game(bots=opponents, seed=3)
    app.menu = False
    app.started = True
    monkeypatch.setattr(app, "autosave", lambda: None)
    rendered = set()
    for _ in range(16000):
        g = app.game
        if g.phase not in rendered:
            app.render()
            rendered.add(g.phase)
        if g.winner is not None:
            break
        if g.actor == 0:
            action = bots.decision(g.observation(0), "Standard", g.bot_memory.setdefault("0", {}))
            assert app.act(**action), (g.phase, action, app.toast)
        else:
            app.next_bot = 0
            app.update()
            assert not app.autosave_error, app.toast
    assert app.game.winner is not None
    assert {"setup_settlement", "setup_road", "roll", "main", "trade", "robber", "victim", "game_over"} <= rendered


@pytest.mark.parametrize("size", [(960, 640), (1280, 854), (1440, 960), (1920, 1080), (2560, 1080), (1280, 1024)])
def test_native_rendering_and_input_survive_resize(app, monkeypatch, size):
    app.window = pg.display.set_mode(size)
    app.menu = False
    original_scale = pg.transform.smoothscale
    def scale_art_only(surface, *args, **kwargs):
        # Scaling a completed interface reintroduces blurry text. Terrain art
        # may still be resampled to fit its hexes.
        assert surface is not app.canvas
        return original_scale(surface, *args, **kwargs)
    monkeypatch.setattr(pg.transform, "smoothscale", scale_art_only)
    app.render()
    scale, viewport = app.viewport()
    assert app.canvas.get_size() == size
    assert viewport == pg.Rect(0, 0, *size)
    # The sidebar follows the right edge at every aspect ratio.
    sidebar = app.rect((1045 + app.width - 1440, 117, 355, 58))
    assert app.canvas.get_at(sidebar.center)[:3] != (18, 38, 46)
    assert size[0] - sidebar.right == pytest.approx(40 * scale, abs=1)
    g = app.game
    g.current = 0
    g.setup_order = [0, 1, 2, 3, 3, 2, 1, 0]
    vertex = g.settlement_sites(0, True)[0]
    native = app.point(app.screen_point(vertex))
    mouse = (native[0] + viewport.x, native[1] + viewport.y)
    app.board_click(app.mouse(mouse))
    assert g.buildings[vertex] == [0, 1]
    assert g.phase == "setup_road"
    for kind in ("offer", "bank", "journal"):
        app.open_modal(kind)
        app.render()
        assert app.buttons
        # A modal's close button must map to its visible native position.
        close = app.buttons[0][0]
        screen = app.point(close.center)
        logical = app.mouse((screen[0] + viewport.x, screen[1] + viewport.y))
        assert close.collidepoint(logical)
    app.modal = None
    app.menu = True
    app.render()


def test_water_has_blue_hexagonal_outline(app):
    from unsettled.ui import WATER, INK
    app.window = pg.display.set_mode((1440, 960))
    app.menu = False
    app.render()
    # Water reaches the six-sided frame's tips; its cutaway corners reveal the
    # surrounding tabletop rather than filling an oval or rectangle.
    assert app.canvas.get_at((120, 424))[:3] == WATER
    assert app.canvas.get_at((900, 424))[:3] == WATER
    assert app.canvas.get_at((520, 80))[:3] == WATER
    assert app.canvas.get_at((200, 200))[:3] == INK
    assert app.canvas.get_at((840, 640))[:3] == INK


def test_fullscreen_restores_window_and_preserves_game(app, monkeypatch):
    # SDL's dummy driver cannot restore a window after a fullscreen switch.
    # Verify our mode requests and state using an explicit desktop surface.
    requests = []
    def set_mode(size, flags):
        requests.append((size, flags))
        return pg.Surface((1920, 1080) if flags & pg.FULLSCREEN else size)
    monkeypatch.setattr(pg.display, "set_mode", set_mode)
    monkeypatch.setattr(pg.display, "flip", lambda: None)
    before = app.game.to_dict()
    size = app.window.get_size()
    app.toggle_fullscreen()
    app.render()
    assert app.fullscreen
    assert requests[-1] == ((0, 0), pg.FULLSCREEN)
    assert app.canvas.get_size() == app.window.get_size()
    app.toggle_fullscreen()
    app.render()
    assert not app.fullscreen
    assert app.window.get_size() == size
    assert requests[-1] == (size, pg.RESIZABLE)
    assert app.game.to_dict() == before


def test_translated_controls_dispatch_at_visible_position(app):
    app.window = pg.display.set_mode((1920, 1080))
    app.menu = False
    app.render()
    # Click the relocated Menu button through the same hit targets as run().
    logical = (1265 + app.width - 1440, 46)
    pos = app.mouse(app.point(logical))
    matches = [callback for rect, callback in app.buttons if rect.collidepoint(pos)]
    assert len(matches) == 1
    matches[0]()
    assert app.menu
    app.open_modal("journal")
    app.render()
    close, callback = app.buttons[0]
    assert close.collidepoint(app.mouse(app.point(close.center)))
    callback()
    assert app.modal is None


@pytest.mark.parametrize("value,occupied", [
    (1, {(1, 1)}),
    (2, {(0, 0), (2, 2)}),
    (3, {(0, 0), (1, 1), (2, 2)}),
    (4, {(0, 0), (2, 0), (0, 2), (2, 2)}),
    (5, {(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)}),
    (6, {(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)}),
])
def test_graphical_die_faces(app, value, occupied):
    # Check actual visible pips, including empty positions, for every roll value.
    app.canvas.fill((0, 0, 0))
    app.draw_die(value, 100, 100)
    for col, x in enumerate((.27, .5, .73)):
        for row, y in enumerate((.24, .46, .68)):
            pixel = app.canvas.get_at(app.point((100 + 40 * x, 100 + 40 * y)))[:3]
            assert (pixel == (48, 55, 54)) == ((col, row) in occupied)


def test_roll_display_uses_saved_results_without_changing_game(app, monkeypatch):
    app.menu = False
    app.game.dice = [2, 6]
    before = app.game.to_dict()
    shown = []
    original = app.draw_die
    def record(value, *args, **kwargs):
        shown.append(value)
        return original(value, *args, **kwargs)
    monkeypatch.setattr(app, "draw_die", record)
    app.render()
    app.render()
    assert shown == [2, 6, 2, 6]
    assert app.game.to_dict() == before


def test_new_games_repeat_island_without_repeating_first_roll(app, monkeypatch):
    # Supply distinct entropy deterministically, avoiding probabilistic tests.
    seeds = iter((1, 2))
    class Entropy:
        def getrandbits(self, bits):
            return next(seeds)
    monkeypatch.setattr("unsettled.ui.random.SystemRandom", Entropy)
    app.seed_text = "1"
    boards, rolls = [], []
    for _ in range(2):
        app.new_game()
        g = app.game
        boards.append(g.board)
        while g.phase != "roll":
            bots.step(g)
        g.command(g.current, "roll")
        rolls.append(g.dice)
    assert boards[0] == boards[1]
    assert rolls == [[1, 6], [4, 4]]  # Seven remains a valid first roll.


def test_settlement_covers_intersection_and_road_guides(app):
    app.menu = False
    g = app.game
    g.current = 0
    g.setup_order = [0, 1, 2, 3, 3, 2, 1, 0]
    vertex = g.settlement_sites(0, True)[0]
    app.board_click(app.screen_point(vertex))
    assert g.phase == "setup_road"
    app.render()
    center = app.point(app.screen_point(vertex))
    actual = app.canvas.get_at(center)
    app.canvas.fill((0, 0, 0))
    app.draw_piece(vertex, 0, 1)
    expected = app.canvas.get_at(center)
    assert expected[:3] != (0, 0, 0)
    assert actual == expected
