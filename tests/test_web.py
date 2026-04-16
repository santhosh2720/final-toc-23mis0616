from __future__ import annotations

from traffic_quantum.web.app import create_app
from traffic_quantum.web.service import TrafficWebService


def test_web_app_boots() -> None:
    app = create_app()
    assert app.title == "Traffic Quantum Dashboard"


def test_bbox_from_polygon() -> None:
    service = TrafficWebService()
    bbox = service._bbox_from_polygon(
        [
            {"lat": 13.08, "lng": 80.27},
            {"lat": 13.085, "lng": 80.275},
            {"lat": 13.079, "lng": 80.281},
        ]
    )
    assert bbox == {
        "south": 13.079,
        "north": 13.085,
        "west": 80.27,
        "east": 80.281,
    }
