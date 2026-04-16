from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from io import BytesIO
import base64

import numpy as np
from PIL import Image


@dataclass(slots=True)
class WarmRoadLayout:
    image_width: int
    image_height: int
    vertical_tracks: list[list[tuple[float, float]]]
    horizontal_tracks: list[list[tuple[float, float]]]
    nodes: list[dict[str, object]]
    edges: list[dict[str, object]]

    @property
    def rows(self) -> int:
        return max(1, len(self.horizontal_tracks))

    @property
    def cols(self) -> int:
        return max(1, len(self.vertical_tracks))


def extract_warm_road_layout(image_data: str) -> WarmRoadLayout | None:
    image = _decode_data_url(image_data).convert("RGB")
    rgb = np.asarray(image, dtype=np.uint8)
    mask = _warm_road_mask(rgb)
    mask = _filter_small_components(mask)
    if mask.mean() < 0.003:
        return None

    graph_layout = _extract_segment_graph_layout(mask)
    if graph_layout is not None:
        graph_layout = _clean_graph_layout(graph_layout, rgb.shape[1], rgb.shape[0])
    if graph_layout is not None:
        return WarmRoadLayout(
            image_width=rgb.shape[1],
            image_height=rgb.shape[0],
            vertical_tracks=[],
            horizontal_tracks=[],
            nodes=graph_layout["nodes"],
            edges=graph_layout["edges"],
        )

    return WarmRoadLayout(
        image_width=rgb.shape[1],
        image_height=rgb.shape[0],
        vertical_tracks=[],
        horizontal_tracks=[],
        nodes=[],
        edges=[],
    )


def _decode_data_url(image_data: str) -> Image.Image:
    if "," in image_data:
        _, encoded = image_data.split(",", 1)
    else:
        encoded = image_data
    raw = base64.b64decode(encoded)
    return Image.open(BytesIO(raw))


def _warm_road_mask(rgb: np.ndarray) -> np.ndarray:
    red = rgb[..., 0].astype(np.int16)
    green = rgb[..., 1].astype(np.int16)
    blue = rgb[..., 2].astype(np.int16)

    yellow = (red > 185) & (green > 150) & (blue < 135) & ((red - blue) > 65)
    orange = (red > 175) & (green > 110) & (green < 205) & (blue < 135) & ((red - blue) > 70)
    red_road = (red > 170) & (green > 80) & (green < 165) & (blue < 120) & ((red - green) > 15)
    mask = yellow | orange | red_road

    # Thicken the detected roads slightly so grouped profiles are stable.
    for _ in range(2):
        mask = _expand_mask(mask)
    return mask


def _expand_mask(mask: np.ndarray) -> np.ndarray:
    expanded = mask.copy()
    expanded[:-1, :] |= mask[1:, :]
    expanded[1:, :] |= mask[:-1, :]
    expanded[:, :-1] |= mask[:, 1:]
    expanded[:, 1:] |= mask[:, :-1]
    return expanded


def _filter_small_components(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    min_pixels = max(42, int(mask.size * 0.00028))
    min_span = max(10, int(min(height, width) * 0.06))
    visited = np.zeros_like(mask, dtype=bool)
    kept = np.zeros_like(mask, dtype=bool)
    for y in range(height):
        for x in range(width):
            if visited[y, x] or not mask[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(y, x)])
            visited[y, x] = True
            component: list[tuple[int, int]] = []
            min_y = max_y = y
            min_x = max_x = x
            while queue:
                cy, cx = queue.popleft()
                component.append((cy, cx))
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                for ny in range(max(0, cy - 1), min(height, cy + 2)):
                    for nx in range(max(0, cx - 1), min(width, cx + 2)):
                        if visited[ny, nx] or not mask[ny, nx]:
                            continue
                        visited[ny, nx] = True
                        queue.append((ny, nx))
            span_x = max_x - min_x + 1
            span_y = max_y - min_y + 1
            if len(component) >= min_pixels and max(span_x, span_y) >= min_span:
                for cy, cx in component:
                    kept[cy, cx] = True
    return kept


def _smooth_profile(values: np.ndarray, window: int) -> np.ndarray:
    window = max(3, int(window))
    if window % 2 == 0:
        window += 1
    kernel = np.ones(window, dtype=np.float64) / window
    return np.convolve(values, kernel, mode="same")


def _find_axis_centers(profile: np.ndarray, min_gap: int) -> list[float]:
    threshold = max(float(profile.mean() + profile.std() * 1.1), 0.018)
    active = profile >= threshold
    segments: list[tuple[float, float]] = []

    start: int | None = None
    for index, flag in enumerate(active):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            _append_segment(profile, segments, start, index - 1)
            start = None
    if start is not None:
        _append_segment(profile, segments, start, len(profile) - 1)

    if not segments:
        strongest = int(np.argmax(profile))
        return [float(strongest)]

    segments.sort(key=lambda item: item[0], reverse=True)
    centers: list[float] = []
    for _, center in segments:
        if all(abs(center - kept) >= min_gap for kept in centers):
            centers.append(center)
        if len(centers) == 4:
            break
    return sorted(centers)


def _append_segment(profile: np.ndarray, segments: list[tuple[float, float]], start: int, end: int) -> None:
    if end - start < 2:
        return
    weights = profile[start : end + 1]
    positions = np.arange(start, end + 1, dtype=np.float64)
    center = float(np.average(positions, weights=weights))
    strength = float(weights.mean())
    segments.append((strength, center))


def _trace_vertical(mask: np.ndarray, center_x: float) -> list[tuple[float, float]]:
    height, width = mask.shape
    sample_count = max(8, min(18, height // 35))
    ys = np.linspace(0, height - 1, sample_count)
    search = max(18, width // 10)
    current_x = center_x
    points: list[tuple[float, float]] = []
    misses = 0
    for y in ys:
        y0 = max(0, int(y - 10))
        y1 = min(height, int(y + 10))
        x0 = max(0, int(current_x - search))
        x1 = min(width, int(current_x + search))
        window = mask[y0:y1, x0:x1]
        if window.any():
            xs = np.where(window)[1] + x0
            current_x = float(xs.mean())
            points.append((round(current_x, 2), round(float(y), 2)))
            misses = 0
        else:
            misses += 1
            if misses >= 2 and points:
                break
    return points


def _trace_horizontal(mask: np.ndarray, center_y: float) -> list[tuple[float, float]]:
    height, width = mask.shape
    sample_count = max(8, min(18, width // 35))
    xs = np.linspace(0, width - 1, sample_count)
    search = max(18, height // 10)
    current_y = center_y
    points: list[tuple[float, float]] = []
    misses = 0
    for x in xs:
        x0 = max(0, int(x - 10))
        x1 = min(width, int(x + 10))
        y0 = max(0, int(current_y - search))
        y1 = min(height, int(current_y + search))
        window = mask[y0:y1, x0:x1]
        if window.any():
            ys = np.where(window)[0] + y0
            current_y = float(ys.mean())
            points.append((round(float(x), 2), round(current_y, 2)))
            misses = 0
        else:
            misses += 1
            if misses >= 2 and points:
                break
    return points


def _trace_horizontal_segments(mask: np.ndarray, center_y: float) -> list[list[tuple[float, float]]]:
    height, width = mask.shape
    sample_count = max(10, min(28, width // 16))
    xs = np.linspace(0, width - 1, sample_count)
    search = max(18, height // 10)
    current_y = center_y
    segment: list[tuple[float, float]] = []
    segments: list[list[tuple[float, float]]] = []
    misses = 0
    for x in xs:
        target_y = current_y if segment else center_y
        y0 = max(0, int(target_y - search))
        y1 = min(height, int(target_y + search))
        x0 = max(0, int(x - 10))
        x1 = min(width, int(x + 10))
        window = mask[y0:y1, x0:x1]
        if window.any():
            ys = np.where(window)[0] + y0
            current_y = float(ys.mean())
            segment.append((round(float(x), 2), round(current_y, 2)))
            misses = 0
        else:
            misses += 1
            if misses >= 2 and len(segment) >= 3:
                segments.append(segment)
                segment = []
                misses = 0
                current_y = center_y
    if len(segment) >= 3:
        segments.append(segment)
    return segments


def _trace_vertical_segments(mask: np.ndarray, center_x: float) -> list[list[tuple[float, float]]]:
    height, width = mask.shape
    sample_count = max(10, min(28, height // 16))
    ys = np.linspace(0, height - 1, sample_count)
    search = max(18, width // 10)
    current_x = center_x
    segment: list[tuple[float, float]] = []
    segments: list[list[tuple[float, float]]] = []
    misses = 0
    for y in ys:
        target_x = current_x if segment else center_x
        y0 = max(0, int(y - 10))
        y1 = min(height, int(y + 10))
        x0 = max(0, int(target_x - search))
        x1 = min(width, int(target_x + search))
        window = mask[y0:y1, x0:x1]
        if window.any():
            xs = np.where(window)[1] + x0
            current_x = float(xs.mean())
            segment.append((round(current_x, 2), round(float(y), 2)))
            misses = 0
        else:
            misses += 1
            if misses >= 2 and len(segment) >= 3:
                segments.append(segment)
                segment = []
                misses = 0
                current_x = center_x
    if len(segment) >= 3:
        segments.append(segment)
    return segments


def _extract_segment_graph_layout(mask: np.ndarray) -> dict[str, list[dict[str, object]]] | None:
    vertical_profile = _smooth_profile(mask.mean(axis=0), window=max(9, mask.shape[1] // 30))
    horizontal_profile = _smooth_profile(mask.mean(axis=1), window=max(9, mask.shape[0] // 30))

    vertical_centers = _find_axis_centers(vertical_profile, min_gap=max(20, mask.shape[1] // 8))
    horizontal_centers = _find_axis_centers(horizontal_profile, min_gap=max(20, mask.shape[0] // 8))
    if not vertical_centers and not horizontal_centers:
        return None

    horizontal_segments = []
    for index, center in enumerate(horizontal_centers):
        for segment_index, points in enumerate(_trace_horizontal_segments(mask, center)):
            if len(points) >= 3:
                horizontal_segments.append({"id": f"H{index}_{segment_index}", "axis": "h", "points": points})

    vertical_segments = []
    for index, center in enumerate(vertical_centers):
        for segment_index, points in enumerate(_trace_vertical_segments(mask, center)):
            if len(points) >= 3:
                vertical_segments.append({"id": f"V{index}_{segment_index}", "axis": "v", "points": points})

    if not horizontal_segments and not vertical_segments:
        return None

    nodes: list[dict[str, object]] = []
    node_index = 0

    def register_node(point: tuple[float, float], kind: str) -> str:
        nonlocal node_index
        for item in nodes:
            if _distance((float(item["x"]), float(item["y"])), point) <= 16:
                if kind == "junction":
                    item["kind"] = "junction"
                return str(item["id"])
        node_id = f"P{node_index}"
        node_index += 1
        nodes.append({"id": node_id, "x": round(point[0], 2), "y": round(point[1], 2), "kind": kind})
        return node_id

    junction_links: dict[str, list[tuple[dict[str, object], float]]] = {
        segment["id"]: [] for segment in horizontal_segments + vertical_segments
    }

    for h_segment in horizontal_segments:
        for v_segment in vertical_segments:
            point = _segment_intersection_from_points(h_segment["points"], v_segment["points"])
            if point is None:
                continue
            node_id = register_node(point, "junction")
            junction_links[h_segment["id"]].append(({"id": node_id, "point": point}, point[0]))
            junction_links[v_segment["id"]].append(({"id": node_id, "point": point}, point[1]))

    edges: list[dict[str, object]] = []
    seen_edges: set[tuple[str, str]] = set()

    def add_segment_edges(segment: dict[str, object]) -> None:
        axis = segment["axis"]
        points = segment["points"]
        axis_index = 0 if axis == "h" else 1
        anchors: list[tuple[str, tuple[float, float], float]] = []
        start_point = points[0]
        end_point = points[-1]
        anchors.append((register_node(start_point, "endpoint"), start_point, start_point[axis_index]))
        anchors.extend((item["id"], item["point"], value) for item, value in junction_links[segment["id"]])
        anchors.append((register_node(end_point, "endpoint"), end_point, end_point[axis_index]))
        anchors.sort(key=lambda item: item[2])

        compact: list[tuple[str, tuple[float, float], float]] = []
        for item in anchors:
            if compact and compact[-1][0] == item[0]:
                continue
            compact.append(item)

        for left, right in zip(compact, compact[1:]):
            if left[0] == right[0]:
                continue
            pair = tuple(sorted((left[0], right[0])))
            if pair in seen_edges:
                continue
            segment_shape = _extract_polyline_between(points, left[1], right[1], axis=axis)
            if len(segment_shape) < 2:
                continue
            seen_edges.add(pair)
            edges.append({"id": f"E{len(edges)}", "from": left[0], "to": right[0], "shape": segment_shape})

    for segment in horizontal_segments + vertical_segments:
        add_segment_edges(segment)

    if len(edges) < 1:
        return None

    degrees = {str(node["id"]): 0 for node in nodes}
    for edge in edges:
        degrees[edge["from"]] += 1
        degrees[edge["to"]] += 1
    for node in nodes:
        if degrees[str(node["id"])] >= 3:
            node["kind"] = "junction"

    return {"nodes": nodes, "edges": edges}


def _clean_graph_layout(
    graph_layout: dict[str, list[dict[str, object]]],
    image_width: int,
    image_height: int,
) -> dict[str, list[dict[str, object]]] | None:
    nodes = [
        {
            "id": str(node["id"]),
            "x": float(node["x"]),
            "y": float(node["y"]),
            "kind": str(node.get("kind", "endpoint")),
        }
        for node in graph_layout["nodes"]
    ]
    edges = [
        {
            "id": str(edge["id"]),
            "from": str(edge["from"]),
            "to": str(edge["to"]),
            "shape": [(float(x), float(y)) for x, y in edge["shape"]],
        }
        for edge in graph_layout["edges"]
    ]
    if not nodes or not edges:
        return None

    merge_threshold = max(24.0, min(image_width, image_height) * 0.07)
    prune_threshold = max(16.0, min(image_width, image_height) * 0.045)

    nodes, edges = _merge_short_links(nodes, edges, merge_threshold)
    nodes, edges = _prune_short_leaf_edges(nodes, edges, prune_threshold)
    nodes, edges = _keep_largest_graph_component(nodes, edges)
    if not nodes or not edges:
        return None

    degrees = _graph_degrees(nodes, edges)
    cleaned_nodes = []
    for node in nodes:
        kind = "junction" if degrees.get(node["id"], 0) >= 3 else "endpoint"
        cleaned_nodes.append(
            {
                "id": node["id"],
                "x": round(node["x"], 2),
                "y": round(node["y"], 2),
                "kind": kind,
            }
        )
    cleaned_edges = []
    for edge in edges:
        cleaned_edges.append(
            {
                "id": edge["id"],
                "from": edge["from"],
                "to": edge["to"],
                "shape": [(round(x, 2), round(y, 2)) for x, y in _simplify_polyline(edge["shape"])],
            }
        )
    return {"nodes": cleaned_nodes, "edges": cleaned_edges}


def _merge_short_links(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
    threshold: float,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    node_by_id = {str(node["id"]): node for node in nodes}
    degrees = _graph_degrees(nodes, edges)
    parent = {node_id: node_id for node_id in node_by_id}

    def find(node_id: str) -> str:
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    changed = False
    for edge in edges:
        start = str(edge["from"])
        end = str(edge["to"])
        if _polyline_length(edge["shape"]) > threshold:
            continue
        if degrees.get(start, 0) <= 1 and degrees.get(end, 0) <= 1:
            continue
        if node_by_id[start]["kind"] == "endpoint" and node_by_id[end]["kind"] == "endpoint":
            continue
        union(start, end)
        changed = True

    if not changed:
        return nodes, edges

    clusters: dict[str, list[str]] = {}
    for node_id in node_by_id:
        clusters.setdefault(find(node_id), []).append(node_id)

    merged_nodes: list[dict[str, object]] = []
    old_to_new: dict[str, str] = {}
    for cluster_index, member_ids in enumerate(clusters.values()):
        cluster_nodes = [node_by_id[node_id] for node_id in member_ids]
        avg_x = sum(float(node["x"]) for node in cluster_nodes) / len(cluster_nodes)
        avg_y = sum(float(node["y"]) for node in cluster_nodes) / len(cluster_nodes)
        new_id = min(member_ids)
        new_kind = "junction" if len(cluster_nodes) > 1 or any(node["kind"] == "junction" for node in cluster_nodes) else "endpoint"
        merged_nodes.append({"id": new_id, "x": avg_x, "y": avg_y, "kind": new_kind})
        for node_id in member_ids:
            old_to_new[node_id] = new_id

    merged_by_id = {str(node["id"]): node for node in merged_nodes}
    best_edges: dict[tuple[str, str], dict[str, object]] = {}
    for edge in edges:
        start = old_to_new[str(edge["from"])]
        end = old_to_new[str(edge["to"])]
        if start == end:
            continue
        start_node = merged_by_id[start]
        end_node = merged_by_id[end]
        interior = [(float(x), float(y)) for x, y in edge["shape"][1:-1]]
        shape = _simplify_polyline(
            [(float(start_node["x"]), float(start_node["y"]))] + interior + [(float(end_node["x"]), float(end_node["y"]))]
        )
        pair = tuple(sorted((start, end)))
        candidate = {"id": str(edge["id"]), "from": start, "to": end, "shape": shape}
        existing = best_edges.get(pair)
        if existing is None or _polyline_length(shape) > _polyline_length(existing["shape"]):
            best_edges[pair] = candidate

    return merged_nodes, list(best_edges.values())


def _prune_short_leaf_edges(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
    threshold: float,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes = list(nodes)
    edges = list(edges)
    while True:
        degrees = _graph_degrees(nodes, edges)
        kept_edges = []
        removed = False
        for edge in edges:
            start = str(edge["from"])
            end = str(edge["to"])
            length = _polyline_length(edge["shape"])
            if length < threshold and (degrees.get(start, 0) == 1 or degrees.get(end, 0) == 1):
                removed = True
                continue
            kept_edges.append(edge)
        edges = kept_edges
        if not removed:
            break
        referenced = {str(edge["from"]) for edge in edges} | {str(edge["to"]) for edge in edges}
        nodes = [node for node in nodes if str(node["id"]) in referenced]
        if not edges:
            break
    return nodes, edges


def _keep_largest_graph_component(
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not nodes or not edges:
        return nodes, edges
    adjacency: dict[str, list[str]] = {str(node["id"]): [] for node in nodes}
    for edge in edges:
        start = str(edge["from"])
        end = str(edge["to"])
        adjacency[start].append(end)
        adjacency[end].append(start)

    best_component: set[str] = set()
    visited: set[str] = set()
    for node_id in adjacency:
        if node_id in visited:
            continue
        queue = deque([node_id])
        component: set[str] = set()
        visited.add(node_id)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbor in adjacency[current]:
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
        if len(component) > len(best_component):
            best_component = component

    kept_nodes = [node for node in nodes if str(node["id"]) in best_component]
    kept_edges = [
        edge
        for edge in edges
        if str(edge["from"]) in best_component and str(edge["to"]) in best_component
    ]
    return kept_nodes, kept_edges


def _graph_degrees(nodes: list[dict[str, object]], edges: list[dict[str, object]]) -> dict[str, int]:
    degrees = {str(node["id"]): 0 for node in nodes}
    for edge in edges:
        degrees[str(edge["from"])] += 1
        degrees[str(edge["to"])] += 1
    return degrees


def _polyline_length(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return float(
        sum(
            _distance(points[index], points[index + 1])
            for index in range(len(points) - 1)
        )
    )


def _extract_graph_layout(mask: np.ndarray) -> dict[str, list[dict[str, object]]] | None:
    scale = max(1, int(max(mask.shape) / 170))
    reduced = mask[::scale, ::scale]
    reduced = _largest_component(reduced)
    if reduced.mean() < 0.004:
        return None
    skeleton = _zhang_suen_thinning(reduced)
    if skeleton.sum() < 12:
        return None

    neighbors = _neighbor_counts(skeleton)
    candidate_mask = skeleton & ((neighbors != 2) | _near_border_mask(skeleton.shape, margin=2))
    nodes = _cluster_points(np.argwhere(candidate_mask), distance=3.2)
    if len(nodes) < 2:
        return None

    node_lookup = {}
    node_pixels: list[tuple[int, int]] = []
    for index, (y, x) in enumerate(nodes):
        snapped = _nearest_skeleton_pixel(skeleton, int(round(y)), int(round(x)))
        if snapped in node_lookup:
            continue
        node_lookup[snapped] = f"P{len(node_lookup)}"
        node_pixels.append(snapped)

    if len(node_pixels) < 2:
        return None

    node_set = set(node_pixels)
    graph_edges = []
    seen_pairs: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    for start in node_pixels:
        for neighbor in _skeleton_neighbors(start, skeleton):
            path = _walk_edge(start, neighbor, skeleton, node_set)
            if path is None or len(path) < 2:
                continue
            end = path[-1]
            if end == start:
                continue
            pair = tuple(sorted((start, end)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            graph_edges.append((start, end, path))

    if not graph_edges:
        return None

    degree = {node: 0 for node in node_pixels}
    for start, end, _ in graph_edges:
        degree[start] += 1
        degree[end] += 1

    nodes_payload = []
    for pixel in node_pixels:
        y, x = pixel
        nodes_payload.append(
            {
                "id": node_lookup[pixel],
                "x": float(x * scale),
                "y": float(y * scale),
                "kind": "junction" if degree[pixel] >= 3 else "endpoint",
                "degree": degree[pixel],
            }
        )

    edges_payload = []
    for index, (start, end, path) in enumerate(graph_edges):
        simplified = _simplify_polyline([(float(x * scale), float(y * scale)) for y, x in path])
        edges_payload.append(
            {
                "id": f"E{index}",
                "from": node_lookup[start],
                "to": node_lookup[end],
                "shape": simplified,
            }
        )

    return {"nodes": nodes_payload, "edges": edges_payload}


def _largest_component(mask: np.ndarray) -> np.ndarray:
    visited = np.zeros_like(mask, dtype=bool)
    best_component: list[tuple[int, int]] = []
    height, width = mask.shape
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            component: list[tuple[int, int]] = []
            queue: deque[tuple[int, int]] = deque([(y, x)])
            visited[y, x] = True
            while queue:
                cy, cx = queue.popleft()
                component.append((cy, cx))
                for ny in range(max(0, cy - 1), min(height, cy + 2)):
                    for nx in range(max(0, cx - 1), min(width, cx + 2)):
                        if (ny == cy and nx == cx) or visited[ny, nx] or not mask[ny, nx]:
                            continue
                        visited[ny, nx] = True
                        queue.append((ny, nx))
            if len(component) > len(best_component):
                best_component = component
    result = np.zeros_like(mask, dtype=bool)
    for y, x in best_component:
        result[y, x] = True
    return result


def _zhang_suen_thinning(mask: np.ndarray) -> np.ndarray:
    skeleton = mask.copy().astype(np.uint8)
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            to_remove = []
            rows, cols = skeleton.shape
            for y in range(1, rows - 1):
                for x in range(1, cols - 1):
                    if skeleton[y, x] != 1:
                        continue
                    p2, p3, p4 = skeleton[y - 1, x], skeleton[y - 1, x + 1], skeleton[y, x + 1]
                    p5, p6, p7 = skeleton[y + 1, x + 1], skeleton[y + 1, x], skeleton[y + 1, x - 1]
                    p8, p9 = skeleton[y, x - 1], skeleton[y - 1, x - 1]
                    neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
                    count = sum(neighbors)
                    if count < 2 or count > 6:
                        continue
                    transitions = sum((neighbors[i] == 0 and neighbors[(i + 1) % 8] == 1) for i in range(8))
                    if transitions != 1:
                        continue
                    if step == 0:
                        if p2 * p4 * p6 != 0 or p4 * p6 * p8 != 0:
                            continue
                    else:
                        if p2 * p4 * p8 != 0 or p2 * p6 * p8 != 0:
                            continue
                    to_remove.append((y, x))
            if to_remove:
                changed = True
                for y, x in to_remove:
                    skeleton[y, x] = 0
    return skeleton.astype(bool)


def _neighbor_counts(mask: np.ndarray) -> np.ndarray:
    counts = np.zeros_like(mask, dtype=np.int16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            ys_from = max(0, -dy)
            ys_to = mask.shape[0] - max(0, dy)
            xs_from = max(0, -dx)
            xs_to = mask.shape[1] - max(0, dx)
            counts[ys_from:ys_to, xs_from:xs_to] += mask[ys_from + dy : ys_to + dy, xs_from + dx : xs_to + dx]
    return counts


def _near_border_mask(shape: tuple[int, int], margin: int) -> np.ndarray:
    height, width = shape
    result = np.zeros(shape, dtype=bool)
    result[:margin, :] = True
    result[-margin:, :] = True
    result[:, :margin] = True
    result[:, -margin:] = True
    return result


def _cluster_points(points: np.ndarray, distance: float) -> list[tuple[float, float]]:
    if len(points) == 0:
        return []
    remaining = [tuple(map(float, point)) for point in points]
    clusters: list[list[tuple[float, float]]] = []
    while remaining:
        seed = remaining.pop()
        cluster = [seed]
        changed = True
        while changed:
            changed = False
            next_remaining = []
            for point in remaining:
                if any((point[0] - item[0]) ** 2 + (point[1] - item[1]) ** 2 <= distance ** 2 for item in cluster):
                    cluster.append(point)
                    changed = True
                else:
                    next_remaining.append(point)
            remaining = next_remaining
        clusters.append(cluster)
    return [(_mean([y for y, _ in cluster]), _mean([x for _, x in cluster])) for cluster in clusters]


def _mean(values: list[float]) -> float:
    return float(sum(values) / max(1, len(values)))


def _nearest_skeleton_pixel(mask: np.ndarray, y: int, x: int) -> tuple[int, int]:
    best = None
    best_distance = 10**9
    for ny in range(max(0, y - 4), min(mask.shape[0], y + 5)):
        for nx in range(max(0, x - 4), min(mask.shape[1], x + 5)):
            if not mask[ny, nx]:
                continue
            distance = (ny - y) ** 2 + (nx - x) ** 2
            if distance < best_distance:
                best_distance = distance
                best = (ny, nx)
    return best if best is not None else (y, x)


def _skeleton_neighbors(point: tuple[int, int], skeleton: np.ndarray) -> list[tuple[int, int]]:
    y, x = point
    neighbors: list[tuple[int, int]] = []
    for ny in range(max(0, y - 1), min(skeleton.shape[0], y + 2)):
        for nx in range(max(0, x - 1), min(skeleton.shape[1], x + 2)):
            if (ny == y and nx == x) or not skeleton[ny, nx]:
                continue
            neighbors.append((ny, nx))
    return neighbors


def _walk_edge(
    start: tuple[int, int],
    current: tuple[int, int],
    skeleton: np.ndarray,
    node_set: set[tuple[int, int]],
) -> list[tuple[int, int]] | None:
    path = [start, current]
    previous = start
    while True:
        if current in node_set and current != start:
            return path
        neighbors = [point for point in _skeleton_neighbors(current, skeleton) if point != previous]
        if not neighbors:
            return path if current in node_set else None
        if len(neighbors) > 1:
            # snap branching point to nearest node candidate later; stop noisy forks
            return path if current in node_set else None
        previous, current = current, neighbors[0]
        path.append(current)


def _simplify_polyline(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    simplified = [points[0]]
    for point in points[1:-1]:
        if (point[0] - simplified[-1][0]) ** 2 + (point[1] - simplified[-1][1]) ** 2 >= 18**2:
            simplified.append(point)
    simplified.append(points[-1])
    return simplified


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)


def _segment_intersection_from_points(
    horizontal_points: list[tuple[float, float]],
    vertical_points: list[tuple[float, float]],
) -> tuple[float, float] | None:
    x_guess = _interpolate_track_x(vertical_points, _track_mid_y(horizontal_points))
    if x_guess < min(point[0] for point in horizontal_points) - 18 or x_guess > max(point[0] for point in horizontal_points) + 18:
        return None
    y_guess = _interpolate_track_y(horizontal_points, x_guess)
    if y_guess < min(point[1] for point in vertical_points) - 18 or y_guess > max(point[1] for point in vertical_points) + 18:
        return None
    x_refined = _interpolate_track_x(vertical_points, y_guess)
    if abs(x_refined - x_guess) > 25:
        return None
    return (round(x_refined, 2), round(y_guess, 2))


def _extract_polyline_between(
    points: list[tuple[float, float]],
    start: tuple[float, float],
    end: tuple[float, float],
    axis: str,
) -> list[tuple[float, float]]:
    axis_index = 0 if axis == "h" else 1
    ordered = sorted(points, key=lambda item: item[axis_index])
    start_value = start[axis_index]
    end_value = end[axis_index]
    lo, hi = sorted((start_value, end_value))
    segment = [point for point in ordered if lo - 3 <= point[axis_index] <= hi + 3]
    if not segment:
        segment = [start, end]
    else:
        if _distance(segment[0], start) > 8:
            segment.insert(0, start)
        else:
            segment[0] = start
        if _distance(segment[-1], end) > 8:
            segment.append(end)
        else:
            segment[-1] = end
    return _simplify_polyline(segment)


def _interpolate_track_x(track: list[tuple[float, float]], target_y: float) -> float:
    points = sorted(track, key=lambda item: item[1])
    for index in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[index], points[index + 1]
        if y0 <= target_y <= y1 or y1 <= target_y <= y0:
            ratio = 0.0 if y1 == y0 else (target_y - y0) / (y1 - y0)
            return x0 + ratio * (x1 - x0)
    return points[-1][0]


def _interpolate_track_y(track: list[tuple[float, float]], target_x: float) -> float:
    points = sorted(track, key=lambda item: item[0])
    for index in range(len(points) - 1):
        (x0, y0), (x1, y1) = points[index], points[index + 1]
        if x0 <= target_x <= x1 or x1 <= target_x <= x0:
            ratio = 0.0 if x1 == x0 else (target_x - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return points[-1][1]


def _track_mid_y(track: list[tuple[float, float]]) -> float:
    return track[len(track) // 2][1]
