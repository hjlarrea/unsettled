"""Transient turn presentation. Effects never change rules, hands, or game RNG."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .engine import RESOURCES


@dataclass
class Effect:
    kind: str
    duration: int
    data: dict


class TurnPresentation:
    def __init__(self):
        self.reduced_motion = False
        self.effects = []
        self.started = 0
        self.now = 0
        self.paused_at = None

    def clear(self):
        self.effects.clear()
        self.paused_at = None

    @property
    def busy(self):
        return bool(self.effects)

    @property
    def blocks_input(self):
        return bool(self.effects and self.effects[0].kind in ('dice', 'harvest', 'transfer', 'phase'))

    @property
    def ends_at(self):
        return self.started + sum(effect.duration for effect in self.effects) if self.effects else self.now

    @property
    def progress(self):
        if not self.effects:
            return 0
        return max(0., min(1., (self.now - self.started) / self.effects[0].duration))

    def advance(self, now, paused=False):
        if paused:
            if self.paused_at is None:
                self.advance(now)
                self.paused_at = now
            return
        if self.paused_at is not None:
            self.started += now - self.paused_at
            self.paused_at = None
        self.now = now
        while self.effects and now >= self.started + self.effects[0].duration:
            self.started += self.effects.pop(0).duration

    @staticmethod
    def snapshot(game):
        return dict(current=game.current, turn=game.turn, phase=game.phase,
                    dice=tuple(game.dice), last_log=game.log[-1],
                    hands=[dict(p.hand) for p in game.players])

    def add(self, kind, duration, data, speed):
        factor = (1.2, 1., .65)[speed]
        duration = min(duration, 320) if self.reduced_motion else duration
        self.effects.append(Effect(kind, max(100, round(duration * factor)), data))

    def announce(self, game, now, speed):
        self.clear()
        self.now = self.started = now
        self.add('turn', 850, dict(owner=game.current, turn=game.turn, phase=game.phase), speed)

    def observe(self, before, game, command, now, speed):
        self.clear()
        self.now = self.started = now
        action = command.get('action')
        if action == 'roll':
            total = sum(game.dice)
            remaining = [{r: max(0, p.hand[r] - before['hands'][i][r]) for r in RESOURCES}
                         for i, p in enumerate(game.players)]
            transfers, tiles, blocked = [], [], []
            if total != 7:
                for h, vertices in enumerate(game.board.hex_vertices):
                    tile = game.board.hexes[h]
                    if tile['number'] != total:
                        continue
                    if h == game.robber:
                        blocked.append(h)
                        continue
                    tiles.append(h)
                    resource = tile['resource']
                    for v in vertices:
                        if v not in game.buildings:
                            continue
                        owner, size = game.buildings[v]
                        paid = min(size, remaining[owner][resource])
                        if paid:
                            transfers.append(dict(tile=h, owner=owner, resource=resource, count=paid))
                            remaining[owner][resource] -= paid
            data = dict(owner=before['current'], dice=tuple(game.dice), total=total,
                        before=before['hands'], transfers=transfers, tiles=tiles, blocked=blocked,
                        phase=game.phase, shortage=False, previous_dice=before['dice'], previous_log=before['last_log'])
            # A bank shortage is determined from public demand and actual payouts,
            # not log text or assumptions about each settlement receiving a card.
            expected = {r: 0 for r in RESOURCES}
            for h in tiles:
                resource = game.board.hexes[h]['resource']
                expected[resource] += sum(game.buildings[v][1] for v in game.board.hex_vertices[h] if v in game.buildings)
            paid = {r: sum(t['count'] for t in transfers if t['resource'] == r) for r in RESOURCES}
            data['shortage'] = any(expected[r] > paid[r] for r in RESOURCES)
            self.add('dice', 1050, data, speed)
            if total != 7:
                self.add('harvest', 500, data, speed)
                if transfers:
                    self.add('transfer', 1000, data, speed)
            self.add('phase', 550, data, speed)
        elif action in ('road', 'settlement', 'city'):
            self.add('build', 550, dict(owner=before['current'], action=action,
                                      vertex=command.get('vertex'), edge=command.get('edge')), speed)
        if game.winner is None and (game.current != before['current'] or game.turn != before['turn'] or (game.phase == 'roll' and before['phase'].startswith('setup'))):
            self.add('turn', 850, dict(owner=game.current, turn=game.turn, phase=game.phase), speed)
        if action != 'roll':
            changes = {r: game.players[0].hand[r] - before['hands'][0][r] for r in RESOURCES}
            changes = {r: n for r, n in changes.items() if n}
            if changes:
                self.add('change', 600, dict(changes=changes), speed)

    @staticmethod
    def flight_progress(index, count, progress):
        return max(0., min(1., (progress - index / max(1, count - 1) * .28) / .68))

    @property
    def revealing_dice(self):
        return bool(self.effects and self.effects[0].kind == 'dice'
                    and not self.reduced_motion and self.progress < .45)

    def dice_for(self, game):
        return self.effects[0].data['previous_dice'] if self.revealing_dice else game.dice

    def log_for(self, game):
        return self.effects[0].data['previous_log'] if self.revealing_dice else game.log[-1]

    def hand_for(self, owner, game):
        if not self.effects or self.effects[0].kind not in ('dice', 'harvest', 'transfer'):
            return game.players[owner].hand
        effect = self.effects[0]
        hand = dict(effect.data['before'][owner])
        if effect.kind == 'transfer':
            transfers = effect.data['transfers']
            for index, transfer in enumerate(transfers):
                arrived = self.progress >= .5 if self.reduced_motion else self.flight_progress(index, len(transfers), self.progress) >= 1
                if transfer['owner'] == owner and arrived:
                    hand[transfer['resource']] += transfer['count']
        return hand

    def draw_board(self, app):
        if not self.effects:
            return
        from .ui import GOLD, WHITE
        effect = self.effects[0]
        data, p = effect.data, self.progress
        if effect.kind in ('harvest', 'transfer'):
            for h in data['tiles']:
                points = [app.screen_point(v) for v in app.game.board.hex_vertices[h]]
                app.polygon(GOLD, points, 3)
                app.circle(WHITE, app.hex_center(h), 29 + (0 if self.reduced_motion else math.sin(p * math.pi) * 4), 2)
            for h in data['blocked']:
                app.polygon((192, 105, 87), [app.screen_point(v) for v in app.game.board.hex_vertices[h]], 3)
        elif effect.kind == 'build':
            if data['vertex'] is not None:
                app.circle(WHITE, app.screen_point(data['vertex']), 19 + 6 * p, 2)
            elif data['edge'] is not None:
                a, b = [app.screen_point(v) for v in app.game.board.edges[data['edge']]]
                app.line(WHITE, a, b, 2)

    def draw_overlay(self, app):
        if not self.effects:
            return
        from .ui import COLORS, GOLD, INK, LIGHT, MUTED, PANEL, WHITE
        effect = self.effects[0]
        data, p = effect.data, self.progress
        cx, cy = app.camera_center() if app.perspective else (520 + (app.width - 1440) / 2, 490 + (app.height - 960) / 2)
        if effect.kind == 'turn':
            owner = data['owner']
            width, height = 410, 100
            x, y = cx - width / 2, cy - height / 2
            app.panel((x + 3, y + 5, width, height), INK, 14)
            app.panel((x, y, width, height), PANEL, 14, COLORS[owner])
            title = 'YOUR TURN' if owner == 0 else app.game.players[owner].name.upper() + "'S TURN"
            app.text(title, cx, y + 32, 28, COLORS[owner], bold=True, center=True)
            detail = 'Place your starting pieces' if data['phase'].startswith('setup') else f"Turn {data['turn'] + 1} · Roll the dice"
            app.text(detail, cx, y + 69, 17, LIGHT, center=True)
        elif effect.kind == 'dice':
            x, y = cx - 178, cy - 105
            app.panel((x + 3, y + 5, 356, 210), INK, 16)
            app.panel((x, y, 356, 210), PANEL, 16, GOLD)
            name = 'You' if data['owner'] == 0 else app.game.players[data['owner']].name
            app.text(f"{name} {'roll' if data['owner'] == 0 else 'rolls'}", cx, y + 24, 18, LIGHT, center=True)
            reveal = self.reduced_motion or p >= .45
            dice = data['dice'] if reveal else (1 + int(p * 57) % 6, 1 + int(p * 83 + 2) % 6)
            offset = 0 if reveal else math.sin(p * 70) * 3
            for i, value in enumerate(dice):
                app.draw_die(value, x + 94 + i * 92, y + 56 + offset, 76)
            app.text(str(data['total']) if reveal else 'Rolling…', cx, y + 168, 31 if reveal else 20, WHITE, bold=True, center=True)
        elif effect.kind in ('harvest', 'transfer'):
            if effect.kind == 'transfer' and not self.reduced_motion:
                transfers = data['transfers']
                for i, transfer in enumerate(transfers):
                    t = self.flight_progress(i, len(transfers), p)
                    if t <= 0 or t >= 1:
                        continue
                    start = app.hex_center(transfer['tile'])
                    end = app.resource_target(transfer['resource']) if transfer['owner'] == 0 else app.player_target(transfer['owner'])
                    eased = t * t * (3 - 2 * t)
                    x = start[0] + (end[0] - start[0]) * eased
                    y = start[1] + (end[1] - start[1]) * eased - math.sin(math.pi * t) * 45
                    app.circle(INK, (x, y), 19)
                    app.resource_icon(transfer['resource'], x, y)
                    if transfer['count'] > 1:
                        app.text(f"+{transfer['count']}", x + 17, y - 17, 15, WHITE, bold=True)
            text = 'Distributing resources' if data['transfers'] else 'No resources produced'
            if data['shortage']:
                text = 'Bank shortage · available resources only'
            elif data['blocked']:
                text += ' · robber blocks a tile'
            self.ribbon(app, cx, text)
        elif effect.kind == 'phase':
            text = {'main': 'TRADE & BUILD', 'discard': 'SEVEN · DISCARD RESOURCES', 'robber': 'SEVEN · MOVE THE ROBBER', 'game_over': 'GAME COMPLETE'}[data['phase']]
            self.ribbon(app, cx, text)
        elif effect.kind == 'build':
            name = 'You' if data['owner'] == 0 else app.game.players[data['owner']].name
            action = {'road': 'road', 'settlement': 'settlement', 'city': 'city'}[data['action']]
            self.ribbon(app, cx, f"{name} {'built' if data['action'] != 'city' else 'upgraded to'} a {action}")
        elif effect.kind == 'change':
            for resource, count in data['changes'].items():
                x, y = app.resource_target(resource)
                lift = 0 if self.reduced_motion else 16 * p
                app.text(f'{count:+d}', x + 48, y - 23 - lift, 19, (125, 214, 161) if count > 0 else (239, 151, 125), bold=True, center=True)
        if effect.kind in ('transfer', 'phase'):
            gains = {}
            transfers = data['transfers']
            for i, transfer in enumerate(transfers):
                arrived = effect.kind == 'phase' or (p >= .5 if self.reduced_motion else self.flight_progress(i, len(transfers), p) >= 1)
                if transfer['owner'] == 0 and arrived:
                    resource = transfer['resource']
                    gains[resource] = gains.get(resource, 0) + transfer['count']
            for resource, count in gains.items():
                x, y = app.resource_target(resource)
                app.text(f'+{count}', x + 48, y - 26, 19, (125, 214, 161), bold=True, center=True)
        if effect.kind in ('turn', 'dice'):
            app.text('Space to skip', cx, cy + (119 if effect.kind == 'dice' else 69), 12, MUTED, center=True)

    @staticmethod
    def ribbon(app, cx, text):
        from .ui import GOLD, PANEL, LIGHT
        y = app.height - 133
        width = min(520, max(320, app.font(17).size(text)[0] + 34))
        app.panel((cx - width / 2, y, width, 36), PANEL, 8, GOLD)
        app.text(text, cx, y + 18, 17, LIGHT, center=True)
