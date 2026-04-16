from __future__ import annotations

from io import BytesIO
import base64

from PIL import Image, ImageDraw

from traffic_quantum.web.image_scan import extract_warm_road_layout


def test_extract_warm_road_layout_detects_major_cross() -> None:
    image = Image.new("RGB", (240, 240), "#f3efe5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((104, 0, 136, 239), fill=(198, 95, 82))
    draw.rectangle((0, 108, 239, 138), fill=(230, 186, 72))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    layout = extract_warm_road_layout(data)

    assert layout is not None
    assert layout.cols >= 1
    assert layout.rows >= 1


def test_extract_warm_road_layout_ignores_small_warm_noise() -> None:
    image = Image.new("RGB", (260, 160), "#f3efe5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 58, 259, 92), fill=(230, 186, 72))
    draw.rectangle((116, 0, 142, 159), fill=(198, 95, 82))
    draw.rectangle((14, 14, 20, 20), fill=(198, 95, 82))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    layout = extract_warm_road_layout(data)

    assert layout is not None
    assert len(layout.nodes) == 5
    assert len(layout.edges) == 4
