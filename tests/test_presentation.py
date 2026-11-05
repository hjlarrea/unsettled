"""Turn presentation tracks real payouts without changing game state or RNG."""
import os
import random

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import pygame as pg
import pytest

from unsettled.engine import Game, RESOURCES
from unsettled.presentation import TurnPresentation
from unsettled.ui import App


def rolled_game(bank=None, recipients=2):
    game = Game(seed=1, play_seed=1)
    game.current, game.phase = 0, 'roll'
    game.rng = random.Random(0)  # A reproducible 4 + 4.
    tile = next(i for i, t in enumerate(game.board.hexes) if t['number'] == 8 and i != game.robber)
    resource = game.board.hexes[tile]['resource']
    vertices = game.board.hex_vertices[tile]
    game.buildings[vertices[0]] = [0, 2]
    if recipients == 2:
        game.buildings[vertices[3]] = [1, 1]
    if bank is not None:
        game.players[2].hand[resource] = 19 - bank
        game.bank[resource] = bank
    pacing = TurnPresentation()
    before = pacing.snapshot(game)
    game.command(0, 'roll')
    pacing.observe(before, game, {'action': 'roll'}, 1000, 1)
    return game, pacing, before, resource


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setattr('unsettled.persistence.save_dir', lambda: tmp_path)
    instance = App(seed=1)
    instance.menu = False
    yield instance
    pg.quit()


def test_production_flights_and_displayed_counts_match_real_payouts():
    game, pacing, before, _ = rolled_game()
    state = game.to_dict()
    rng = game.rng.getstate()
    data = pacing.effects[0].data
    assert [e.kind for e in pacing.effects] == ['dice', 'harvest', 'transfer', 'phase']
    for owner in range(len(game.players)):
        for resource in RESOURCES:
            paid = sum(t['count'] for t in data['transfers'] if t['owner'] == owner and t['resource'] == resource)
            assert paid == game.players[owner].hand[resource] - before['hands'][owner][resource]
    assert pacing.hand_for(0, game) == before['hands'][0]
    pacing.advance(2550)  # Dice and tile highlight have finished.
    assert pacing.effects[0].kind == 'transfer'
    assert pacing.hand_for(0, game) == before['hands'][0]
    pacing.advance(3540)
    assert pacing.hand_for(0, game) == game.players[0].hand
    pacing.advance(pacing.ends_at)
    assert not pacing.busy
    assert game.to_dict() == state
    assert game.rng.getstate() == rng


@pytest.mark.parametrize('recipients,expected', [(1, 1), (2, 0)])
def test_bank_shortage_never_animates_unpaid_resources(recipients, expected):
    game, pacing, before, resource = rolled_game(bank=1, recipients=recipients)
    data = pacing.effects[0].data
    assert data['shortage']
    assert sum(t['count'] for t in data['transfers'] if t['resource'] == resource) == expected
    assert game.players[0].hand[resource] - before['hands'][0][resource] == expected


def test_seven_reveals_dice_then_robber_without_production():
    game = Game(seed=1, play_seed=1)
    game.current, game.phase = 0, 'roll'
    game.rng = random.Random(1)  # 2 + 5.
    pacing = TurnPresentation()
    before = pacing.snapshot(game)
    game.command(0, 'roll')
    pacing.observe(before, game, {'action': 'roll'}, 1000, 1)
    assert [e.kind for e in pacing.effects] == ['dice', 'phase']
    assert pacing.effects[0].data['total'] == 7
    assert pacing.effects[0].data['phase'] == 'robber'
    assert pacing.effects[0].data['transfers'] == []


def test_pause_freezes_progress_and_preserves_remaining_duration():
    game, pacing, _, _ = rolled_game()
    pacing.advance(1300)
    pacing.advance(1400, paused=True)
    frozen = pacing.progress
    remaining = pacing.ends_at - 1400
    pacing.advance(5000, paused=True)
    assert pacing.progress == frozen
    pacing.advance(6000)
    assert pacing.progress == pytest.approx(frozen)
    assert pacing.ends_at - 6000 == remaining
    pacing.advance(pacing.ends_at)
    assert not pacing.busy


def test_repeated_identical_rolls_still_get_presented():
    game, pacing, _, _ = rolled_game()
    game.phase = 'roll'
    game.rng = random.Random(0)
    before = pacing.snapshot(game)
    game.command(0, 'roll')
    pacing.observe(before, game, {'action': 'roll'}, 5000, 1)
    assert pacing.effects[0].kind == 'dice'
    assert pacing.effects[0].data['dice'] == (4, 4)


def test_end_turn_announces_the_actual_next_player():
    game = Game(seed=1, play_seed=1)
    game.current, game.phase = 0, 'main'
    pacing = TurnPresentation()
    before = pacing.snapshot(game)
    game.command(0, 'end')
    pacing.observe(before, game, {'action': 'end'}, 1000, 1)
    assert pacing.effects[0].kind == 'turn'
    assert pacing.effects[0].data['owner'] == 1
    assert pacing.effects[0].data['turn'] == 1


def test_bot_waits_until_announcement_and_action_delay_finish(app, monkeypatch):
    ticks = [1000]
    monkeypatch.setattr(pg.time, 'get_ticks', lambda: ticks[0])
    monkeypatch.setattr(app, 'autosave', lambda: None)
    calls = []
    monkeypatch.setattr('unsettled.bots.step', lambda game: calls.append(game.actor))
    app.game.current = 1
    app.pacing.announce(app.game, 1000, app.speed)
    app.next_bot = 0
    app.update()
    assert calls == []
    assert app.bot_progress() is None
    ticks[0] = 1850
    app.update()
    assert calls == []
    ticks[0] = 4350
    app.update()
    assert calls == [1]


def test_skip_and_reduced_motion_do_not_change_rules(app, monkeypatch):
    game, pacing, _, _ = rolled_game()
    app.game, app.pacing = game, pacing
    state = game.to_dict()
    monkeypatch.setattr(pg.time, 'get_ticks', lambda: 1100)
    app.skip_presentation()
    assert not app.pacing.busy
    assert game.to_dict() == state
    app.toggle_motion()
    assert app.pacing.reduced_motion
    app.pacing.announce(game, 1100, app.speed)
    assert app.pacing.effects[0].duration <= 320
    assert app.pacing.hand_for(0, game) == game.players[0].hand
    assert game.to_dict() == state


@pytest.mark.parametrize('perspective,size', [(False, (960, 640)), (True, (1440, 960))])
def test_every_roll_stage_renders_without_mutating_the_game(app, monkeypatch, perspective, size):
    game, pacing, _, _ = rolled_game()
    app.game, app.pacing = game, pacing
    app.perspective = perspective
    app.window = pg.display.set_mode(size)
    state = game.to_dict()
    for effect in list(pacing.effects):
        ticks = pacing.started + round(effect.duration * .6)
        monkeypatch.setattr(pg.time, 'get_ticks', lambda: ticks)
        app.render()
        assert pacing.effects[0].kind == effect.kind
        assert app.canvas.get_size() == size
        pacing.advance(pacing.started + effect.duration)
    assert game.to_dict() == state


def test_dice_and_journal_wait_for_the_central_reveal():
    game, pacing, before, _ = rolled_game()
    assert pacing.revealing_dice
    assert pacing.dice_for(game) == before['dice']
    assert pacing.log_for(game) == before['last_log']
    pacing.advance(1600)
    assert not pacing.revealing_dice
    assert tuple(pacing.dice_for(game)) == (4, 4)
    assert pacing.log_for(game) == game.log[-1]
