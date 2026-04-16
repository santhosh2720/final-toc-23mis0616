from __future__ import annotations

from traffic_quantum.web.gemini_scan import _graph_to_layout, _parse_gemini_graph_response


def test_parse_gemini_graph_response_extracts_json_text() -> None:
    body = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '{"junctions":[{"id":"J0","x":100,"y":120,"kind":"junction"},{"id":"J1","x":100,"y":40,"kind":"endpoint"}],"roads":[{"id":"R0","from":"J0","to":"J1"}]}'
                        }
                    ]
                }
            }
        ]
    }

    graph = _parse_gemini_graph_response(body)

    assert len(graph.junctions) == 2
    assert len(graph.roads) == 1
    assert graph.roads[0]["from"] == "J0"


def test_graph_to_layout_builds_edges_from_junctions() -> None:
    graph = _parse_gemini_graph_response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"junctions":[{"id":"J0","x":80,"y":100,"kind":"junction"},{"id":"J1","x":80,"y":10,"kind":"endpoint"},{"id":"J2","x":170,"y":100,"kind":"endpoint"}],"roads":[{"id":"R0","from":"J0","to":"J1"},{"id":"R1","from":"J0","to":"J2"}]}'
                            }
                        ]
                    }
                }
            ]
        }
    )

    layout = _graph_to_layout(graph)

    assert len(layout.nodes) == 3
    assert len(layout.edges) == 2
    assert layout.edges[0]["shape"][0] == (80.0, 100.0)
