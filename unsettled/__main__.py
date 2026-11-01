import argparse


def main():
    parser = argparse.ArgumentParser(description="Unsettled — offline island strategy")
    parser.add_argument("--simulate", type=int, metavar="GAMES", help="run headless all-bot validation games")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--bots", type=int, choices=(2, 3), default=3)
    parser.add_argument("--screenshot", metavar="PATH", help="render a seeded board and exit (supports SDL dummy driver)")
    args = parser.parse_args()
    if args.simulate is not None:
        from .simulation import simulate
        simulate(args.simulate, args.seed, args.bots)
    else:
        from .ui import App
        App(seed=args.seed, bots=args.bots).run(screenshot=args.screenshot)


if __name__ == "__main__":
    main()
