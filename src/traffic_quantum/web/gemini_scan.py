from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
from typing import Any

import requests

from traffic_quantum.web.image_scan import WarmRoadLayout


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass(slots=True)
class GeminiGraph:
    junctions: list[dict[str, Any]]
    roads: list[dict[str, Any]]


def extract_gemini_road_layout(image_data: str) -> WarmRoadLayout | None:
    env_values = _load_local_env()
    api_key = (os.environ.get("GEMINI_API_KEY") or env_values.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None

    model = (os.environ.get("GEMINI_MODEL") or env_values.get("GEMINI_MODEL") or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    mime_type, encoded = _split_data_url(image_data)
    graph = _request_gemini_graph(api_key=api_key, model=model, mime_type=mime_type, encoded_image=encoded)
    return _graph_to_layout(graph)


def _request_gemini_graph(api_key: str, model: str, mime_type: str, encoded_image: str) -> GeminiGraph:
    prompt = (
        "You are extracting a simplified traffic graph from a map screenshot. "
        "Consider only the yellow, orange, and red major roads visible inside the selected rectangle. "
        "Ignore white/local roads, labels, icons, arrows, buses, and decorative map shapes. "
        "Do not trace road outlines or polygons. Return a clean centerline road graph suitable for SUMO. "
        "For small junction areas, prefer one main corridor plus its important branches rather than many tiny nodes. "
        "Return valid JSON only with this exact schema: "
        '{"junctions":[{"id":"J0","x":120,"y":80,"kind":"junction"}],'
        '"roads":[{"id":"R0","from":"J0","to":"J1"}]}. '
        "Rules: junction coordinates are in image pixels with origin at the top-left. "
        "Use kind 'junction' for internal intersections and 'endpoint' for road ends. "
        "Keep only the meaningful major-road topology, not exact curves."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": encoded_image,
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    response = requests.post(
        GEMINI_API_URL.format(model=model),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    return _parse_gemini_graph_response(body)


def _parse_gemini_graph_response(body: dict[str, Any]) -> GeminiGraph:
    text = _extract_response_text(body)
    if not text:
        raise ValueError("Gemini response did not include text output.")
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    data = json.loads(text)
    junctions = data.get("junctions", [])
    roads = data.get("roads", [])
    if not junctions or not roads:
        raise ValueError("Gemini response did not include enough junctions or roads.")
    return GeminiGraph(junctions=junctions, roads=roads)


def _extract_response_text(body: dict[str, Any]) -> str:
    candidates = body.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if text:
                return text
    return ""


def _graph_to_layout(graph: GeminiGraph) -> WarmRoadLayout:
    nodes = []
    node_ids: set[str] = set()
    for item in graph.junctions:
        node_id = str(item["id"])
        if node_id in node_ids:
            continue
        node_ids.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "x": float(item["x"]),
                "y": float(item["y"]),
                "kind": str(item.get("kind", "endpoint")),
            }
        )

    node_lookup = {node["id"]: node for node in nodes}
    edges = []
    for index, road in enumerate(graph.roads):
        start = str(road["from"])
        end = str(road["to"])
        if start not in node_lookup or end not in node_lookup or start == end:
            continue
        edges.append(
            {
                "id": str(road.get("id", f"R{index}")),
                "from": start,
                "to": end,
                "shape": [
                    (float(node_lookup[start]["x"]), float(node_lookup[start]["y"])),
                    (float(node_lookup[end]["x"]), float(node_lookup[end]["y"])),
                ],
            }
        )
    if not nodes or not edges:
        raise ValueError("Gemini graph could not be converted into a usable layout.")

    return WarmRoadLayout(
        image_width=max(1, int(max(node["x"] for node in nodes) + 1)),
        image_height=max(1, int(max(node["y"] for node in nodes) + 1)),
        vertical_tracks=[],
        horizontal_tracks=[],
        nodes=nodes,
        edges=edges,
    )


def _split_data_url(image_data: str) -> tuple[str, str]:
    if "," not in image_data:
        raise ValueError("Expected a data URL for Gemini image extraction.")
    header, encoded = image_data.split(",", 1)
    mime_type = "image/png"
    if ";" in header and ":" in header:
        mime_type = header.split(":", 1)[1].split(";", 1)[0] or mime_type
    # Validate that the payload is base64 before sending.
    base64.b64decode(encoded)
    return mime_type, encoded


def _load_local_env() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values
