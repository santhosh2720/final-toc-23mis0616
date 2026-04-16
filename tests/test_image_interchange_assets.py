from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from traffic_quantum.config import load_config
from traffic_quantum.sim.sumo_assets import generate_image_interchange_assets


def test_image_interchange_assets_are_generated() -> None:
    config = load_config("configs/image_interchange.toml")
    root = Path("tests") / ".tmp" / f"image_interchange_assets_{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)

    assets = generate_image_interchange_assets(config, root)

    for key in ("nod", "edg", "rou", "sumocfg"):
        assert assets[key].exists()

    assert assets["net"].name == "image_interchange.net.xml"

    route_text = assets["rou"].read_text(encoding="utf-8")
    assert 'route id="north_south"' in route_text
    assert 'route id="middle_diagonal_east"' in route_text
    assert 'route id="east_to_upper_west"' in route_text

    shutil.rmtree(root, ignore_errors=True)
