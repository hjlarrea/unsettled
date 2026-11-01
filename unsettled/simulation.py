"""Reproducible headless validation; no Pygame required."""
from .engine import Game
from .bots import step


def play(seed=1, bots=3, max_commands=16000):
    game = Game(bots=bots, seed=seed, difficulties=["Easy" if i % 2 else "Standard" for i in range(bots)])
    game.players[0].difficulty = "Standard"
    for i in range(max_commands):
        if game.winner is not None:
            return game, i
        try:
            step(game)
            game.validate()
        except Exception as exc:
            raise RuntimeError(f"Seed {seed}, command {i}, turn {game.turn}, actor {game.actor}, phase {game.phase}: {exc}") from exc
    raise RuntimeError(f"Stalled seed {seed}: turn={game.turn}, points={[game.points(p, True) for p in range(len(game.players))]}, phase={game.phase}")


def simulate(count, seed=1, bots=3):
    for s in range(seed, seed + count):
        game, commands = play(s, bots)
        print(f"seed={s} players={bots + 1} winner={game.players[game.winner].name} turns={game.turn} commands={commands}", flush=True)
