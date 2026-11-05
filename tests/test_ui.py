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
        # Exercise the skip control so full-game checks do not wait on wall time.
        if app.pacing.busy:
            app.skip_presentation()
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
    # The whole sea frame clears the title bar and leaves room for the footer.
    sea_y = [point[1] for point in app.water_outline()]
    assert min(sea_y) > 97 + 20
    assert max(sea_y) < app.height - 60
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
    for point in ((120, 490), (900, 515), (520, 164)):
        red, green, blue = app.canvas.get_at(point)[:3]
        assert blue > green > red
        assert red < WATER[0]
    assert app.canvas.get_at((200, 266))[:3] == INK
    assert app.canvas.get_at((840, 706))[:3] == INK
    # Isolate the sea from tiles and ports to check depth toward the frame.
    app.draw_sea_frame()
    brightness = [sum(app.canvas.get_at((x, 490))[:3]) for x in (120, 160, 200, 240)]
    assert all(outer < inner for outer, inner in zip(brightness, brightness[1:]))


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


def test_slower_default_and_speed_changes_restart_countdown(app, monkeypatch):
    ticks = [1000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks[0])
    app.menu = False
    app.game.current = 1
    assert app.speed == 1
    assert app.delay() == 2500
    app.schedule_bot()
    assert app.bot_progress() == 0
    ticks[0] += 1250
    assert app.bot_progress() == pytest.approx(.5)
    app.cycle_speed()
    assert app.delay() == 1200
    assert app.bot_progress() == 0
    ticks[0] += 1200
    assert app.bot_progress() == 1
    app.cycle_speed()
    assert app.delay() == 4000
    assert app.bot_progress() == 0


def test_bot_countdown_waits_for_deadline_and_pauses_in_dialog(app, monkeypatch):
    ticks = [1000]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks[0])
    monkeypatch.setattr(app, "autosave", lambda: None)
    steps = []
    monkeypatch.setattr(bots, "step", lambda game: steps.append(game.actor))
    app.menu = False
    app.game.current = 1
    app.schedule_bot()
    ticks[0] = 3499
    app.update()
    assert steps == []
    app.open_modal("journal")
    ticks[0] = 4000
    app.update()
    assert app.bot_progress() is None
    assert steps == []
    app.modal = None
    app.update()
    assert app.bot_progress() == 0
    ticks[0] += 2500
    app.update()
    assert steps == [1]
    assert app.bot_progress() == 0
    app.game.current = 0
    assert app.bot_progress() is None


def test_phase_banner_identifies_human_response_during_computer_turn(app, monkeypatch):
    app.menu = False
    g = app.game
    g.current, g.phase = 1, "main"
    g.players[1].hand["wood"] = 1
    g.bank["wood"] -= 1
    g.command(1, "offer", target=0, give={"wood": 1}, want={"ore": 1})
    labels = []
    monkeypatch.setattr(app, "text", lambda label, *args, **kwargs: labels.append(label))
    before = g.to_dict()
    app.draw_turn_banner()
    assert any("JUNIPER'S TURN" in label for label in labels)
    assert "Respond to trade" in labels
    assert "Your move · take your time" in labels
    assert app.bot_progress() is None
    assert g.to_dict() == before


@pytest.mark.parametrize("opponents", [2, 3])
@pytest.mark.parametrize("first", [0, 1, 2])
def test_sidebar_follows_turn_order_with_equal_sized_player_rows(app, monkeypatch, opponents, first):
    g = app.game = Game(bots=opponents, seed=1)
    order = [(first + offset) % len(g.players) for offset in range(len(g.players))]
    g.setup_order = order + order[::-1]
    labels, markers = [], []
    monkeypatch.setattr(app, "text", lambda label, x, y, *args, **kwargs: labels.append((label, x, y)))
    monkeypatch.setattr(app, "draw_turn_marker", lambda x, y: markers.append((x, y)))
    seats = {}
    y = 117
    for player in order:
        seats[player] = y
        y += 66
    for current in reversed(order):
        g.current = current
        before = g.to_dict()
        labels.clear()
        markers.clear()
        app.draw_players()
        names = [(label, y) for label, x, y in labels if label in {p.name for p in g.players}]
        assert names == [(g.players[player].name, seats[player] + 9) for player in order]
        assert markers == [(1037, seats[current] + 29)]
        assert g.to_dict() == before


@pytest.mark.parametrize("phase", ["trade", "discard", "game_over"])
def test_sidebar_marker_tracks_turn_owner_during_responses(app, monkeypatch, phase):
    g = app.game
    g.current, g.phase = 1, phase
    g.trade = {"target": 0}
    g.discards = {0: 1}
    g.winner = 1 if phase == "game_over" else None
    markers = []
    monkeypatch.setattr(app, "draw_turn_marker", lambda x, y: markers.append((x, y)))
    app.draw_players()
    assert len(markers) == (0 if g.winner is not None else 1)
    if markers:
        assert g.actor == 0
        order = g.setup_order[:len(g.players)]
        preceding = order[:order.index(g.current)]
        assert markers[0] == (1037, 117 + 66 * len(preceding) + 29)


@pytest.mark.parametrize("size", [(960, 640), (1440, 960), (2560, 1080)])
def test_turn_arrow_renders_beside_current_box_at_native_size(app, size):
    from unsettled.ui import GOLD, INK
    app.window = pg.display.set_mode(size)
    app.sync_canvas()
    app.canvas.fill(INK)
    g = app.game
    g.current = g.setup_order[0]
    with app.shifted(app.width - 1440):
        app.draw_players()
        assert app.canvas.get_at(app.point((1017, 146)))[:3] == GOLD
        assert app.canvas.get_at(app.point((1017, 212)))[:3] == INK


@pytest.mark.parametrize("phase,current,actor", [
    ("setup_settlement", 0, 0), ("roll", 0, 0), ("main", 0, 0),
    ("trade", 1, 0), ("discard", 1, 0), ("main", 1, 1),
])
def test_attention_breathes_only_for_human_input(app, monkeypatch, phase, current, actor):
    from unsettled.ui import GOLD
    app.menu = False
    g = app.game
    g.phase, g.current = phase, current
    g.trade = {"target": actor}
    g.discards = {actor: 1}
    before = g.to_dict()
    frames = []
    for ticks in (0, 1100, 2200):
        monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks)
        app.draw_turn_banner()
        app.draw_turn_marker(1037, 146)
        frames.append((app.canvas.get_at(app.point((620, 13)))[:3],
                       app.canvas.get_at(app.point((1017, 146)))[:3]))
    assert frames[0] == frames[2]
    if actor == 0:
        assert frames[0][0] != frames[1][0]
        assert frames[1][0] == GOLD
    else:
        assert frames[0] == frames[1]
    assert (frames[0][1] != frames[1][1]) == (current == actor == 0)
    assert g.to_dict() == before


@pytest.mark.parametrize("paused", ["menu", "autosave_error", "journal", "game_over"])
def test_attention_stays_still_when_no_action_is_available(app, monkeypatch, paused):
    app.menu = False
    app.game.current = 0
    if paused == "journal":
        app.modal = {"kind": "journal"}
    elif paused == "game_over":
        app.game.phase, app.game.winner = "game_over", 0
    else:
        setattr(app, paused, True)
    colors = []
    for ticks in (0, 1100):
        monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks)
        colors.append(app.human_attention_color())
    assert colors[0] == colors[1]


@pytest.mark.parametrize("size", [(720, 480), (1440, 960), (2560, 1080)])
def test_disabled_purchase_tooltip_hover_resize_and_modal(app, monkeypatch, size):
    app.window = pg.display.set_mode(size)
    app.menu = False
    app.game.phase, app.game.current = "main", 0
    ticks = [0]
    monkeypatch.setattr(pg.time, "get_ticks", lambda: ticks[0])
    app.render()
    rect, message = next((rect, text) for rect, text in app.tooltips
                         if text.startswith("Cost: 1 wheat, 1 sheep, 1 ore."))
    assert "You need 1 wheat, 1 sheep, 1 ore more." in message
    assert not any(button.collidepoint(rect.center) for button, _ in app.buttons)
    monkeypatch.setattr(app, "mouse", lambda pos=None: rect.center)
    before = app.game.to_dict()
    app.render()
    assert app.tooltip_rect is None
    ticks[0] = 400
    app.render()
    assert app.tooltip_rect is not None
    native = app.rect(app.tooltip_rect)
    assert app.canvas.get_rect().contains(native)
    assert app.game.to_dict() == before
    app.open_modal("journal")
    app.render()
    assert app.tooltip_rect is None
    assert not any(text.startswith("Cost:") for _, text in app.tooltips)


def test_purchase_tooltips_track_resources_deck_and_legal_sites(app):
    g = app.game
    g.phase, g.current = "main", 0
    g.players[0].hand.update(wheat=1, sheep=1, ore=1)
    assert "You need" not in app.purchase_tooltip("development")
    g.deck.clear()
    assert "deck is empty" in app.purchase_tooltip("development")
    assert "settlements to upgrade" in app.purchase_tooltip("city", g.city_sites(0))
    vertex = g.settlement_sites(0, True)[0]
    g.buildings[vertex] = [0, 1]
    assert "settlements to upgrade" not in app.purchase_tooltip("city", g.city_sites(0))
    assert "You need 1 wheat, 2 ore more." in app.purchase_tooltip("city", g.city_sites(0))


def test_development_card_tooltips_explain_play_restrictions(app):
    g = app.game
    g.current, g.phase, g.turn = 0, "main", 4
    g.players[0].cards = [["knight", 4], ["victory", 4]]
    assert "turn you bought it" in app.card_tooltip("knight")
    assert "Counted automatically" in app.card_tooltip("victory")
    g.players[0].cards.append(["knight", 3])
    assert "Play before or after rolling" in app.card_tooltip("knight")
    g.played_card = True
    assert "already played" in app.card_tooltip("knight")
    g.current = 1
    assert "Wait for your turn" in app.card_tooltip("knight")


def test_bank_trade_tooltip_explains_all_blockers(app):
    app.game.current, app.game.phase = 0, "main"
    app.open_modal("bank")
    app.modal["receive_r"] = app.modal["give_r"]
    app.game.bank["wood"] = 0
    app.draw_modal()
    rect, message = next((rect, text) for rect, text in app.tooltips
                         if text.startswith("Trade 4 wood for 1 wood."))
    assert "Choose different resources" in message
    assert "You need 4 more wood" in message
    assert "bank has no wood" in message
    assert not any(button.collidepoint(rect.center) for button, _ in app.buttons)


@pytest.mark.parametrize("size", [(720, 480), (1440, 960), (2560, 1080)])
def test_resource_strip_stays_visible_and_shows_only_human_hand(app, monkeypatch, size):
    from unsettled.engine import RESOURCES
    app.window = pg.display.set_mode(size)
    app.sync_canvas()
    g = app.game
    g.current = 1
    g.players[0].hand.update(dict(zip(RESOURCES, (1, 2, 3, 4, 5))))
    g.players[1].hand.update(dict.fromkeys(RESOURCES, 19))
    counts = []
    monkeypatch.setattr(app, "text", lambda label, *args, **kwargs: counts.append(label) if isinstance(label, int) else None)
    before = g.to_dict()
    with app.shifted((app.width - 1440) / 2, app.height - 960):
        app.draw_resource_bar()
    assert counts == [1, 2, 3, 4, 5]
    assert len(app.tooltips) == 5
    for (rect, message), resource in zip(app.tooltips, RESOURCES):
        assert app.canvas.get_rect().contains(app.rect(rect))
        assert message.startswith(f"{resource.title()}: {g.players[0].hand[resource]} in your hand.")
        assert f"{g.ratio(0, resource)}:1" in message
    assert g.to_dict() == before


@pytest.mark.parametrize("perspective", [False, True])
def test_settlement_placement_markers_are_white_in_both_views(app, perspective):
    from unsettled.ui import WHITE
    app.perspective = perspective
    app.menu = False
    g = app.game
    g.current = 0
    g.setup_order = [0, 1, 2, 3, 3, 2, 1, 0]
    app.render()
    vertex = min(g.settlement_sites(0, True), key=lambda v: abs(app.screen_point(v)[0] - 520))
    assert app.canvas.get_at(app.point(app.screen_point(vertex)))[:3] == WHITE
