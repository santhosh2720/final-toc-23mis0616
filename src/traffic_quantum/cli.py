from __future__ import annotations

import argparse
from pathlib import Path

from .analysis.runner import benchmark_controllers, smoke_test, train_policy
from .config import load_config
from .sim.sumo_assets import build_netconvert, generate_grid_assets, generate_image_interchange_assets
from .web.app import main as serve_web


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="traffic-quantum")
    subparsers = parser.add_subparsers(dest="command", required=True)

    smoke = subparsers.add_parser("smoke-test", help="Run a short simulation.")
    smoke.add_argument("--config", default="configs/mock_city.toml")
    smoke.add_argument("--backend", choices=["mock", "sumo"], default=None)
    smoke.add_argument(
        "--controller",
        choices=["fixed", "actuated", "genetic", "hybrid"],
        default=None,
    )

    bench = subparsers.add_parser("benchmark", help="Benchmark controllers.")
    bench.add_argument("--config", default="configs/mock_city.toml")
    bench.add_argument("--output", default=None)
    bench.add_argument("--replications", type=int, default=4)

    train = subparsers.add_parser("train-policy", help="Train hybrid policy on the mock env.")
    train.add_argument("--config", default="configs/mock_city.toml")
    train.add_argument("--episodes", type=int, default=10)

    assets = subparsers.add_parser("generate-sumo-assets", help="Generate grid SUMO source files.")
    assets.add_argument("--config", default="configs/sumo_city.toml")
    assets.add_argument("--output", default="sumo_assets")
    assets.add_argument("--build-net", action="store_true")
    assets.add_argument("--netconvert", default="netconvert")
    assets.add_argument("--preset", choices=["grid", "image-interchange"], default="grid")

    subparsers.add_parser("serve-web", help="Run the map-based web dashboard.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(getattr(args, "config", None))

    if getattr(args, "backend", None):
        config.simulation.backend = args.backend
    if getattr(args, "controller", None):
        config.controller.name = args.controller

    if args.command == "smoke-test":
        metrics = smoke_test(config)
        print(metrics)
    elif args.command == "benchmark":
        output_dir = Path(args.output) if args.output else None
        summary = benchmark_controllers(config, replications=args.replications, output_dir=output_dir)
        print(summary.to_string(index=False))
    elif args.command == "train-policy":
        result = train_policy(config, episodes=args.episodes)
        print(result)
    elif args.command == "generate-sumo-assets":
        if args.preset == "image-interchange":
            paths = generate_image_interchange_assets(config, args.output)
        else:
            paths = generate_grid_assets(config, args.output)
        if args.build_net:
            build_netconvert(paths, netconvert_binary=args.netconvert)
        print({name: str(path) for name, path in paths.items()})
    elif args.command == "serve-web":
        serve_web()


if __name__ == "__main__":
    main()
