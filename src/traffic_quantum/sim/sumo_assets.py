from __future__ import annotations

from pathlib import Path
import subprocess
import random
import math

from traffic_quantum.config import ProjectConfig


def generate_grid_assets(config: ProjectConfig, output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    nod = root / "grid.nod.xml"
    edg = root / "grid.edg.xml"
    rou = root / "grid.rou.xml"
    tll = root / "grid.tll.xml"
    sumocfg = root / "grid.sumocfg"
    net = root / "grid.net.xml"

    rows = config.simulation.grid_rows
    cols = config.simulation.grid_cols
    spacing = 200

    nodes = ['<nodes>']
    for row in range(rows):
        for col in range(cols):
            node_id = f"J{row}_{col}"
            x = col * spacing
            y = row * spacing
            nodes.append(f'    <node id="{node_id}" x="{x}" y="{y}" type="traffic_light"/>')
    nodes.append("</nodes>")
    nod.write_text("\n".join(nodes), encoding="utf-8")

    edges = ['<edges>']
    for row in range(rows):
        for col in range(cols):
            if col < cols - 1:
                left = f"J{row}_{col}"
                right = f"J{row}_{col + 1}"
                edges.append(f'    <edge id="{left}_to_{right}" from="{left}" to="{right}" numLanes="2" speed="13.9"/>')
                edges.append(f'    <edge id="{right}_to_{left}" from="{right}" to="{left}" numLanes="2" speed="13.9"/>')
            if row < rows - 1:
                top = f"J{row}_{col}"
                bottom = f"J{row + 1}_{col}"
                edges.append(f'    <edge id="{top}_to_{bottom}" from="{top}" to="{bottom}" numLanes="2" speed="13.9"/>')
                edges.append(f'    <edge id="{bottom}_to_{top}" from="{bottom}" to="{top}" numLanes="2" speed="13.9"/>')
    edges.append("</edges>")
    edg.write_text("\n".join(edges), encoding="utf-8")

    tll.write_text(
        "\n".join(
            [
                "<additional>",
                '    <vType id="car" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
                '    <vType id="bus" accel="1.2" decel="4.0" sigma="0.5" length="12" maxSpeed="11.1"/>',
                '    <vType id="truck" accel="0.8" decel="3.5" sigma="0.5" length="10" maxSpeed="10.0"/>',
                '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
                "</additional>",
            ]
        ),
        encoding="utf-8",
    )

    random.seed(config.project.seed)
    routes = ['<routes>']
    routes.append('    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>')
    routes.append('    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>')
    boundary_pairs = _boundary_routes(rows, cols)
    for route_id, edge_sequence in enumerate(boundary_pairs):
        edges_joined = " ".join(edge_sequence)
        routes.append(f'    <route id="r{route_id}" edges="{edges_joined}"/>')
    vehicle_count = max(100, int(config.simulation.episode_seconds * config.simulation.arrival_rate * 2))
    for vehicle_id in range(vehicle_count):
        route_index = random.randrange(len(boundary_pairs))
        depart = round(vehicle_id * (config.simulation.episode_seconds / vehicle_count), 2)
        vehicle_type = "emergency" if random.random() < config.scenario.emergency_vehicle_rate else "passenger"
        routes.append(
            f'    <vehicle id="veh{vehicle_id}" type="{vehicle_type}" route="r{route_index}" depart="{depart}"/>'
        )
    routes.append("</routes>")
    rou.write_text("\n".join(routes), encoding="utf-8")

    sumocfg.write_text(
        "\n".join(
            [
                "<configuration>",
                "    <input>",
                f'        <net-file value="{net.name}"/>',
                f'        <route-files value="{rou.name}"/>',
                "    </input>",
                "    <time>",
                '        <begin value="0"/>',
                f'        <end value="{config.simulation.episode_seconds}"/>',
                "    </time>",
                "</configuration>",
            ]
        ),
        encoding="utf-8",
    )

    return {"nod": nod, "edg": edg, "rou": rou, "tll": tll, "sumocfg": sumocfg, "net": net}


def generate_cross_intersection_assets(config: ProjectConfig, output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    nod = root / "cross.nod.xml"
    edg = root / "cross.edg.xml"
    rou = root / "cross.rou.xml"
    tll = root / "cross.tll.xml"
    sumocfg = root / "cross.sumocfg"
    net = root / "cross.net.xml"

    spacing = 220
    nod.write_text(
        "\n".join(
            [
                "<nodes>",
                '    <node id="N" x="0" y="220" type="priority"/>',
                '    <node id="S" x="0" y="-220" type="priority"/>',
                '    <node id="E" x="220" y="0" type="priority"/>',
                '    <node id="W" x="-220" y="0" type="priority"/>',
                '    <node id="J0" x="0" y="0" type="traffic_light"/>',
                "</nodes>",
            ]
        ),
        encoding="utf-8",
    )

    edge_lines = ["<edges>"]
    for start, end in (("N", "J0"), ("J0", "N"), ("S", "J0"), ("J0", "S"), ("E", "J0"), ("J0", "E"), ("W", "J0"), ("J0", "W")):
        edge_lines.append(
            f'    <edge id="{start}_to_{end}" from="{start}" to="{end}" numLanes="2" speed="13.9"/>'
        )
    edge_lines.append("</edges>")
    edg.write_text("\n".join(edge_lines), encoding="utf-8")

    tll.write_text(
        "\n".join(
            [
                "<additional>",
                '    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
                '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
                "</additional>",
            ]
        ),
        encoding="utf-8",
    )

    random.seed(config.project.seed)
    routes = [
        "<routes>",
        '    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
        '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
        '    <route id="north_south" edges="N_to_J0 J0_to_S"/>',
        '    <route id="south_north" edges="S_to_J0 J0_to_N"/>',
        '    <route id="east_west" edges="E_to_J0 J0_to_W"/>',
        '    <route id="west_east" edges="W_to_J0 J0_to_E"/>',
        '    <route id="north_east" edges="N_to_J0 J0_to_E"/>',
        '    <route id="south_west" edges="S_to_J0 J0_to_W"/>',
        '    <route id="east_north" edges="E_to_J0 J0_to_N"/>',
        '    <route id="west_south" edges="W_to_J0 J0_to_S"/>',
    ]
    route_ids = [
        "north_south",
        "south_north",
        "east_west",
        "west_east",
        "north_east",
        "south_west",
        "east_north",
        "west_south",
    ]
    vehicle_count = max(80, int(config.simulation.episode_seconds * config.simulation.arrival_rate * 2))
    for vehicle_id in range(vehicle_count):
        route_id = random.choice(route_ids)
        depart = round(vehicle_id * (config.simulation.episode_seconds / vehicle_count), 2)
        vehicle_type = "emergency" if random.random() < config.scenario.emergency_vehicle_rate else "passenger"
        routes.append(
            f'    <vehicle id="veh{vehicle_id}" type="{vehicle_type}" route="{route_id}" depart="{depart}"/>'
        )
    routes.append("</routes>")
    rou.write_text("\n".join(routes), encoding="utf-8")

    sumocfg.write_text(
        "\n".join(
            [
                "<configuration>",
                "    <input>",
                f'        <net-file value="{net.name}"/>',
                f'        <route-files value="{rou.name}"/>',
                "    </input>",
                "    <time>",
                '        <begin value="0"/>',
                f'        <end value="{config.simulation.episode_seconds}"/>',
                "    </time>",
                "</configuration>",
            ]
        ),
        encoding="utf-8",
    )

    return {"nod": nod, "edg": edg, "rou": rou, "tll": tll, "sumocfg": sumocfg, "net": net}


def generate_image_interchange_assets(config: ProjectConfig, output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    nod = root / "image_interchange.nod.xml"
    edg = root / "image_interchange.edg.xml"
    rou = root / "image_interchange.rou.xml"
    tll = root / "image_interchange.tll.xml"
    sumocfg = root / "image_interchange.sumocfg"
    net = root / "image_interchange.net.xml"

    width = 1400
    height = 1250
    positions = {
        "N": (700, 1180),
        "S": (700, 120),
        "WU": (80, 1000),
        "WM": (80, 760),
        "WL": (80, 520),
        "EU": (1320, 1000),
        "EM": (1320, 760),
        "EL": (1320, 520),
        "J0": (380, 1000),
        "J1": (700, 1000),
        "J2": (380, 760),
        "J3": (700, 760),
        "J4": (1020, 760),
        "J5": (380, 520),
        "J6": (700, 520),
        "J7": (1020, 520),
    }
    signal_nodes = {"J1", "J2", "J3", "J4", "J6"}

    node_lines = ["<nodes>"]
    for node_id, (x, y) in positions.items():
        node_type = "traffic_light" if node_id in signal_nodes else "priority"
        node_lines.append(f'    <node id="{node_id}" x="{x}" y="{y}" type="{node_type}"/>')
    node_lines.append("</nodes>")
    nod.write_text("\n".join(node_lines), encoding="utf-8")

    edge_lines = ["<edges>"]
    edge_specs: list[tuple[str, str, int, float]] = []

    def add_bidirectional(a: str, b: str, lanes: int, speed: float) -> None:
        edge_specs.append((a, b, lanes, speed))
        edge_specs.append((b, a, lanes, speed))

    # Main arterial cross inspired by the image.
    add_bidirectional("N", "J1", lanes=3, speed=18.0)
    add_bidirectional("J1", "J3", lanes=3, speed=18.0)
    add_bidirectional("J3", "J6", lanes=3, speed=18.0)
    add_bidirectional("J6", "S", lanes=3, speed=18.0)

    add_bidirectional("WM", "J2", lanes=3, speed=17.0)
    add_bidirectional("J2", "J3", lanes=3, speed=17.0)
    add_bidirectional("J3", "J4", lanes=3, speed=17.0)
    add_bidirectional("J4", "EM", lanes=3, speed=17.0)

    # Secondary corridors from the image.
    add_bidirectional("WU", "J0", lanes=2, speed=15.0)
    add_bidirectional("J0", "J1", lanes=2, speed=15.0)
    add_bidirectional("J1", "EU", lanes=2, speed=15.0)

    add_bidirectional("WL", "J5", lanes=2, speed=15.0)
    add_bidirectional("J5", "J6", lanes=2, speed=15.0)
    add_bidirectional("J6", "J7", lanes=2, speed=15.0)
    add_bidirectional("J7", "EL", lanes=2, speed=15.0)

    add_bidirectional("J0", "J2", lanes=2, speed=14.0)
    add_bidirectional("J2", "J5", lanes=2, speed=14.0)
    add_bidirectional("J4", "J7", lanes=2, speed=14.0)

    # A strategic diagonal/turn connector so coordinated control has real value.
    add_bidirectional("J2", "J6", lanes=1, speed=12.0)

    for start, end, lanes, speed in edge_specs:
        edge_lines.append(
            f'    <edge id="{start}_to_{end}" from="{start}" to="{end}" numLanes="{lanes}" speed="{speed}"/>'
        )
    edge_lines.append("</edges>")
    edg.write_text("\n".join(edge_lines), encoding="utf-8")

    tll.write_text(
        "\n".join(
            [
                "<additional>",
                '    <vType id="passenger" accel="2.8" decel="4.6" sigma="0.4" length="5" maxSpeed="16.7"/>',
                '    <vType id="emergency" accel="3.2" decel="5.0" sigma="0.2" length="5" maxSpeed="18.0" color="1,0,0"/>',
                "</additional>",
            ]
        ),
        encoding="utf-8",
    )

    route_defs = {
        "upper_east": ["WU_to_J0", "J0_to_J1", "J1_to_EU"],
        "upper_west": ["EU_to_J1", "J1_to_J0", "J0_to_WU"],
        "middle_east": ["WM_to_J2", "J2_to_J3", "J3_to_J4", "J4_to_EM"],
        "middle_west": ["EM_to_J4", "J4_to_J3", "J3_to_J2", "J2_to_WM"],
        "lower_east": ["WL_to_J5", "J5_to_J6", "J6_to_J7", "J7_to_EL"],
        "lower_west": ["EL_to_J7", "J7_to_J6", "J6_to_J5", "J5_to_WL"],
        "north_south": ["N_to_J1", "J1_to_J3", "J3_to_J6", "J6_to_S"],
        "south_north": ["S_to_J6", "J6_to_J3", "J3_to_J1", "J1_to_N"],
        "north_middle_east": ["N_to_J1", "J1_to_J3", "J3_to_J4", "J4_to_EM"],
        "west_middle_south": ["WM_to_J2", "J2_to_J3", "J3_to_J6", "J6_to_S"],
        "upper_to_south": ["WU_to_J0", "J0_to_J1", "J1_to_J3", "J3_to_J6", "J6_to_S"],
        "lower_to_north": ["WL_to_J5", "J5_to_J2", "J2_to_J0", "J0_to_J1", "J1_to_N"],
        "middle_diagonal_east": ["WM_to_J2", "J2_to_J6", "J6_to_J7", "J7_to_EL"],
        "lower_to_middle_east": ["WL_to_J5", "J5_to_J6", "J6_to_J3", "J3_to_J4", "J4_to_EM"],
        "east_to_south": ["EM_to_J4", "J4_to_J3", "J3_to_J6", "J6_to_S"],
        "east_to_upper_west": ["EM_to_J4", "J4_to_J3", "J3_to_J1", "J1_to_J0", "J0_to_WU"],
    }
    route_categories = {
        "upper_east": "upper",
        "upper_west": "upper",
        "middle_east": "middle",
        "middle_west": "middle",
        "lower_east": "lower",
        "lower_west": "lower",
        "north_south": "vertical",
        "south_north": "vertical",
        "north_middle_east": "turn",
        "west_middle_south": "turn",
        "upper_to_south": "turn",
        "lower_to_north": "turn",
        "middle_diagonal_east": "connector",
        "lower_to_middle_east": "connector",
        "east_to_south": "turn",
        "east_to_upper_west": "turn",
    }

    route_lines = [
        "<routes>",
        '    <vType id="passenger" accel="2.8" decel="4.6" sigma="0.4" length="5" maxSpeed="16.7"/>',
        '    <vType id="emergency" accel="3.2" decel="5.0" sigma="0.2" length="5" maxSpeed="18.0" color="1,0,0"/>',
    ]
    for route_id, edges in route_defs.items():
        route_lines.append(f'    <route id="{route_id}" edges="{" ".join(edges)}"/>')

    random.seed(config.project.seed)
    vehicle_count = max(220, int(config.simulation.episode_seconds * config.simulation.arrival_rate * 2.2))
    route_ids = list(route_defs)
    wave_specs = [
        (
            0.00,
            0.26,
            0.32,
            {
                "vertical": 7.5,
                "middle": 0.9,
                "upper": 1.3,
                "lower": 1.1,
                "turn": 2.1,
                "connector": 0.6,
            },
        ),
        (
            0.26,
            0.54,
            0.30,
            {
                "vertical": 1.1,
                "middle": 7.2,
                "upper": 1.4,
                "lower": 1.4,
                "turn": 2.4,
                "connector": 1.7,
            },
        ),
        (
            0.54,
            0.80,
            0.24,
            {
                "vertical": 1.0,
                "middle": 2.0,
                "upper": 1.5,
                "lower": 1.8,
                "turn": 5.6,
                "connector": 4.6,
            },
        ),
        (
            0.80,
            1.00,
            0.14,
            {
                "vertical": 2.5,
                "middle": 3.0,
                "upper": 2.2,
                "lower": 2.2,
                "turn": 3.4,
                "connector": 2.6,
            },
        ),
    ]

    vehicle_specs: list[tuple[float, str, str]] = []
    allocated = 0
    for index, (start_frac, end_frac, share, weights_by_category) in enumerate(wave_specs):
        if index == len(wave_specs) - 1:
            wave_count = vehicle_count - allocated
        else:
            wave_count = int(round(vehicle_count * share))
            allocated += wave_count
        wave_start = config.simulation.episode_seconds * start_frac
        wave_end = config.simulation.episode_seconds * end_frac
        mode = (wave_start + wave_end) / 2.0
        weights = [weights_by_category[route_categories[route_id]] for route_id in route_ids]
        for _ in range(max(0, wave_count)):
            depart = round(random.triangular(wave_start, wave_end, mode), 2)
            route_id = random.choices(route_ids, weights=weights, k=1)[0]
            vehicle_type = "emergency" if random.random() < config.scenario.emergency_vehicle_rate else "passenger"
            vehicle_specs.append((depart, route_id, vehicle_type))

    vehicle_specs.sort(key=lambda item: item[0])
    for vehicle_id, (depart, route_id, vehicle_type) in enumerate(vehicle_specs):
        route_lines.append(
            f'    <vehicle id="veh{vehicle_id}" type="{vehicle_type}" route="{route_id}" depart="{depart}"/>'
        )
    route_lines.append("</routes>")
    rou.write_text("\n".join(route_lines), encoding="utf-8")

    sumocfg.write_text(
        "\n".join(
            [
                "<configuration>",
                "    <input>",
                f'        <net-file value="{net.name}"/>',
                f'        <route-files value="{rou.name}"/>',
                "    </input>",
                "    <time>",
                '        <begin value="0"/>',
                f'        <end value="{config.simulation.episode_seconds}"/>',
                "    </time>",
                "</configuration>",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "nod": nod,
        "edg": edg,
        "rou": rou,
        "tll": tll,
        "sumocfg": sumocfg,
        "net": net,
        "layout": {"rows": 3, "cols": 3, "width": width, "height": height},
    }


def generate_abstract_area_assets(
    config: ProjectConfig,
    output_dir: str | Path,
    junction_count: int,
) -> dict[str, Path]:
    if junction_count <= 1:
        return generate_cross_intersection_assets(config, output_dir)
    grid_size = 2 if junction_count <= 4 else 3 if junction_count <= 9 else 4
    config.simulation.grid_rows = grid_size
    config.simulation.grid_cols = grid_size
    return generate_grid_assets(config, output_dir)


def generate_area_based_assets(
    config: ProjectConfig,
    output_dir: str | Path,
    bbox: dict[str, float],
) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    nod = root / "area.nod.xml"
    edg = root / "area.edg.xml"
    rou = root / "area.rou.xml"
    tll = root / "area.tll.xml"
    sumocfg = root / "area.sumocfg"
    net = root / "area.net.xml"

    lat_span = max(0.001, abs(bbox["north"] - bbox["south"]))
    lon_span = max(0.001, abs(bbox["east"] - bbox["west"]))
    aspect = lon_span / lat_span

    base_cells = 2 if max(lat_span, lon_span) < 0.02 else 3 if max(lat_span, lon_span) < 0.05 else 4
    cols = max(2, min(4, round(base_cells * max(1.0, aspect))))
    rows = max(2, min(4, round(base_cells * max(1.0, 1 / max(aspect, 0.0001)))))

    width = 900
    height = max(500, round(width / max(aspect, 0.65)))
    margin_x = 120
    margin_y = 120
    internal_width = width - margin_x * 2
    internal_height = height - margin_y * 2

    def interior_point(row: int, col: int) -> tuple[float, float]:
        x = margin_x + (col / max(1, cols - 1)) * internal_width
        y = margin_y + (row / max(1, rows - 1)) * internal_height
        phase = (row + 1) * (col + 2)
        x += math.sin(phase) * 22
        y += math.cos(phase * 1.3) * 18
        return (round(x, 2), round(y, 2))

    interior = {
        (row, col): interior_point(row, col)
        for row in range(rows)
        for col in range(cols)
    }

    node_lines = ["<nodes>"]
    for row in range(rows):
        for col in range(cols):
            x, y = interior[(row, col)]
            node_lines.append(
                f'    <node id="J{row}_{col}" x="{x}" y="{y}" type="traffic_light"/>'
            )

    for row in range(rows):
        _, y = interior[(row, 0)]
        node_lines.append(f'    <node id="W{row}" x="0" y="{y}" type="priority"/>')
        _, y2 = interior[(row, cols - 1)]
        node_lines.append(f'    <node id="E{row}" x="{width}" y="{y2}" type="priority"/>')
    for col in range(cols):
        x, _ = interior[(0, col)]
        node_lines.append(f'    <node id="N{col}" x="{x}" y="0" type="priority"/>')
        x2, _ = interior[(rows - 1, col)]
        node_lines.append(f'    <node id="S{col}" x="{x2}" y="{height}" type="priority"/>')
    node_lines.append("</nodes>")
    nod.write_text("\n".join(node_lines), encoding="utf-8")

    edge_lines = ["<edges>"]

    primary_rows = {rows // 2}
    primary_cols = {cols // 2}

    def add_bidirectional(a: str, b: str, lanes: int = 2, speed: float = 13.9) -> None:
        edge_lines.append(f'    <edge id="{a}_to_{b}" from="{a}" to="{b}" numLanes="{lanes}" speed="{speed}"/>')
        edge_lines.append(f'    <edge id="{b}_to_{a}" from="{b}" to="{a}" numLanes="{lanes}" speed="{speed}"/>')

    for row in range(rows):
        for col in range(cols - 1):
            is_primary = row in primary_rows
            add_bidirectional(f"J{row}_{col}", f"J{row}_{col + 1}", lanes=3 if is_primary else 2, speed=15.5 if is_primary else 13.9)
    for col in range(cols):
        for row in range(rows - 1):
            is_primary = col in primary_cols
            add_bidirectional(f"J{row}_{col}", f"J{row + 1}_{col}", lanes=3 if is_primary else 2, speed=15.5 if is_primary else 13.9)

    for row in range(rows):
        is_primary = row in primary_rows
        add_bidirectional(f"W{row}", f"J{row}_0", lanes=3 if is_primary else 2, speed=15.5 if is_primary else 13.9)
        add_bidirectional(f"J{row}_{cols - 1}", f"E{row}", lanes=3 if is_primary else 2, speed=15.5 if is_primary else 13.9)
    for col in range(cols):
        is_primary = col in primary_cols
        add_bidirectional(f"N{col}", f"J0_{col}", lanes=3 if is_primary else 2, speed=15.5 if is_primary else 13.9)
        add_bidirectional(f"J{rows - 1}_{col}", f"S{col}", lanes=3 if is_primary else 2, speed=15.5 if is_primary else 13.9)

    if rows >= 3 and cols >= 3:
        add_bidirectional("J0_0", "J1_1", lanes=2, speed=12.0)
        add_bidirectional(f"J{rows - 1}_0", f"J{rows - 2}_1", lanes=2, speed=12.0)
        add_bidirectional(f"J0_{cols - 1}", f"J1_{cols - 2}", lanes=2, speed=12.0)

    edge_lines.append("</edges>")
    edg.write_text("\n".join(edge_lines), encoding="utf-8")

    tll.write_text(
        "\n".join(
            [
                "<additional>",
                '    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
                '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
                "</additional>",
            ]
        ),
        encoding="utf-8",
    )

    route_lines = [
        "<routes>",
        '    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
        '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
    ]
    route_defs = {}
    route_index = 0

    for row in range(rows):
        eastward = [f"W{row}_to_J{row}_0"] + [f"J{row}_{col}_to_J{row}_{col + 1}" for col in range(cols - 1)] + [f"J{row}_{cols - 1}_to_E{row}"]
        westward = [f"E{row}_to_J{row}_{cols - 1}"] + [f"J{row}_{col}_to_J{row}_{col - 1}" for col in range(cols - 1, 0, -1)] + [f"J{row}_0_to_W{row}"]
        route_defs[f"r{route_index}"] = eastward
        route_index += 1
        route_defs[f"r{route_index}"] = westward
        route_index += 1

    for col in range(cols):
        southward = [f"N{col}_to_J0_{col}"] + [f"J{row}_{col}_to_J{row + 1}_{col}" for row in range(rows - 1)] + [f"J{rows - 1}_{col}_to_S{col}"]
        northward = [f"S{col}_to_J{rows - 1}_{col}"] + [f"J{row}_{col}_to_J{row - 1}_{col}" for row in range(rows - 1, 0, -1)] + [f"J0_{col}_to_N{col}"]
        route_defs[f"r{route_index}"] = southward
        route_index += 1
        route_defs[f"r{route_index}"] = northward
        route_index += 1

    for route_id, edges in route_defs.items():
        route_lines.append(f'    <route id="{route_id}" edges="{" ".join(edges)}"/>')

    random.seed(config.project.seed)
    vehicle_count = max(120, int(config.simulation.episode_seconds * config.simulation.arrival_rate * 2.5))
    route_ids = list(route_defs)
    for vehicle_id in range(vehicle_count):
        route_id = random.choice(route_ids)
        depart = round(vehicle_id * (config.simulation.episode_seconds / vehicle_count), 2)
        vehicle_type = "emergency" if random.random() < config.scenario.emergency_vehicle_rate else "passenger"
        route_lines.append(
            f'    <vehicle id="veh{vehicle_id}" type="{vehicle_type}" route="{route_id}" depart="{depart}"/>'
        )
    route_lines.append("</routes>")
    rou.write_text("\n".join(route_lines), encoding="utf-8")

    sumocfg.write_text(
        "\n".join(
            [
                "<configuration>",
                "    <input>",
                f'        <net-file value="{net.name}"/>',
                f'        <route-files value="{rou.name}"/>',
                "    </input>",
                "    <time>",
                '        <begin value="0"/>',
                f'        <end value="{config.simulation.episode_seconds}"/>',
                "    </time>",
                "</configuration>",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "nod": nod,
        "edg": edg,
        "rou": rou,
        "tll": tll,
        "sumocfg": sumocfg,
        "net": net,
        "layout": {"rows": rows, "cols": cols, "width": width, "height": height},
    }


def generate_scanned_major_road_assets(
    config: ProjectConfig,
    output_dir: str | Path,
    scan_layout,
) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    nod = root / "area.nod.xml"
    edg = root / "area.edg.xml"
    rou = root / "area.rou.xml"
    tll = root / "area.tll.xml"
    sumocfg = root / "area.sumocfg"
    net = root / "area.net.xml"

    if getattr(scan_layout, "nodes", None) and getattr(scan_layout, "edges", None):
        compact_layout = _compact_scanned_graph(scan_layout)
        width = 960.0
        height = 640.0
        return _generate_scanned_graph_assets(
            config=config,
            root=root,
            nod=nod,
            edg=edg,
            rou=rou,
            tll=tll,
            sumocfg=sumocfg,
            net=net,
            scan_layout=compact_layout,
            map_x=lambda value: round(float(value), 2),
            map_y=lambda value: round(float(value), 2),
            width=width,
            height=height,
        )

    source_width = max(1.0, float(scan_layout.image_width))
    source_height = max(1.0, float(scan_layout.image_height))
    width = max(2200.0, source_width * 8.0)
    height = max(1400.0, source_height * 8.0)
    margin = 180.0
    usable_width = width - margin * 2
    usable_height = height - margin * 2

    def map_x(x: float) -> float:
        return round(margin + (x / source_width) * usable_width, 2)

    def map_y(y: float) -> float:
        return round(margin + ((source_height - y) / source_height) * usable_height, 2)

    vertical_tracks = [mapped for mapped in [[(map_x(x), map_y(y)) for x, y in track] for track in scan_layout.vertical_tracks] if len(mapped) >= 2]
    horizontal_tracks = [mapped for mapped in [[(map_x(x), map_y(y)) for x, y in track] for track in scan_layout.horizontal_tracks] if len(mapped) >= 2]
    cols = len(vertical_tracks)
    rows = len(horizontal_tracks)

    intersections: dict[tuple[int, int], tuple[float, float]] = {}
    for row, h_track in enumerate(horizontal_tracks):
        for col, v_track in enumerate(vertical_tracks):
            point = _track_intersection(h_track, v_track)
            if point is not None:
                intersections[(row, col)] = point

    node_lines = ["<nodes>"]
    node_positions: dict[str, tuple[float, float]] = {}
    for (row, col), (x, y) in intersections.items():
        node_id = f"J{row}_{col}"
        node_positions[node_id] = (x, y)
        node_lines.append(f'    <node id="{node_id}" x="{round(x, 2)}" y="{round(y, 2)}" type="traffic_light"/>')

    row_nodes: dict[int, list[tuple[str, float, float]]] = {}
    for row, h_track in enumerate(horizontal_tracks):
        connected = [(f"J{row}_{col}", *intersections[(row, col)]) for col in range(cols) if (row, col) in intersections]
        if not connected:
            continue
        connected.sort(key=lambda item: item[1])
        left_x, left_y = h_track[0]
        right_x, right_y = h_track[-1]
        w_id = f"W{row}"
        e_id = f"E{row}"
        node_positions[w_id] = (left_x, left_y)
        node_positions[e_id] = (right_x, right_y)
        node_lines.append(f'    <node id="{w_id}" x="{round(left_x, 2)}" y="{round(left_y, 2)}" type="priority"/>')
        node_lines.append(f'    <node id="{e_id}" x="{round(right_x, 2)}" y="{round(right_y, 2)}" type="priority"/>')
        row_nodes[row] = [(w_id, left_x, left_y)] + connected + [(e_id, right_x, right_y)]

    col_nodes: dict[int, list[tuple[str, float, float]]] = {}
    for col, v_track in enumerate(vertical_tracks):
        connected = [(f"J{row}_{col}", *intersections[(row, col)]) for row in range(rows) if (row, col) in intersections]
        if not connected:
            continue
        connected.sort(key=lambda item: item[2], reverse=True)
        top_x, top_y = max(v_track, key=lambda item: item[1])
        bottom_x, bottom_y = min(v_track, key=lambda item: item[1])
        n_id = f"N{col}"
        s_id = f"S{col}"
        node_positions[n_id] = (top_x, top_y)
        node_positions[s_id] = (bottom_x, bottom_y)
        node_lines.append(f'    <node id="{n_id}" x="{round(top_x, 2)}" y="{round(top_y, 2)}" type="priority"/>')
        node_lines.append(f'    <node id="{s_id}" x="{round(bottom_x, 2)}" y="{round(bottom_y, 2)}" type="priority"/>')
        col_nodes[col] = [(n_id, top_x, top_y)] + connected + [(s_id, bottom_x, bottom_y)]

    node_lines.append("</nodes>")
    nod.write_text("\n".join(node_lines), encoding="utf-8")

    edge_lines = ["<edges>"]
    graph_adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_positions}
    edge_lookup: dict[tuple[str, str], str] = {}
    edge_counter = 0

    def add_bidirectional(a: str, b: str, shape_points: list[tuple[float, float]], lanes: int = 1, speed: float = 13.9) -> None:
        nonlocal edge_counter
        edge_id = f"SE{edge_counter}"
        edge_counter += 1
        shape_text = " ".join(f"{round(x, 2)},{round(y, 2)}" for x, y in shape_points)
        reverse_text = " ".join(f"{round(x, 2)},{round(y, 2)}" for x, y in reversed(shape_points))
        edge_lines.append(f'    <edge id="{edge_id}_{a}_{b}" from="{a}" to="{b}" numLanes="{lanes}" speed="{speed}" shape="{shape_text}"/>')
        edge_lines.append(f'    <edge id="{edge_id}_{b}_{a}" from="{b}" to="{a}" numLanes="{lanes}" speed="{speed}" shape="{reverse_text}"/>')
        graph_adjacency[a].append(b)
        graph_adjacency[b].append(a)
        edge_lookup[(a, b)] = f"{edge_id}_{a}_{b}"
        edge_lookup[(b, a)] = f"{edge_id}_{b}_{a}"

    for row, items in row_nodes.items():
        if len(items) < 2:
            continue
        track = horizontal_tracks[row]
        for index in range(len(items) - 1):
            start_id, start_x, _ = items[index]
            end_id, end_x, _ = items[index + 1]
            shape_points = _extract_track_segment(track, start_x, end_x, axis="x")
            add_bidirectional(start_id, end_id, shape_points)

    for col, items in col_nodes.items():
        if len(items) < 2:
            continue
        track = vertical_tracks[col]
        for index in range(len(items) - 1):
            start_id, _, start_y = items[index]
            end_id, _, end_y = items[index + 1]
            shape_points = _extract_track_segment(track, start_y, end_y, axis="y")
            add_bidirectional(start_id, end_id, shape_points)

    edge_lines.append("</edges>")
    edg.write_text("\n".join(edge_lines), encoding="utf-8")

    tll.write_text(
        "\n".join(
            [
                "<additional>",
                '    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
                '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
                "</additional>",
            ]
        ),
        encoding="utf-8",
    )

    route_lines = [
        "<routes>",
        '    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
        '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
    ]
    route_defs: dict[str, list[str]] = {}
    route_index = 0
    endpoints = [node_id for node_id in node_positions if node_id.startswith(("W", "E", "N", "S"))]
    for start in endpoints:
        for end in endpoints:
            if start == end:
                continue
            path = _shortest_path(graph_adjacency, start, end)
            if len(path) < 2:
                continue
            edges = [edge_lookup[(path[i], path[i + 1])] for i in range(len(path) - 1)]
            route_defs[f"r{route_index}"] = edges
            route_index += 1

    for route_id, edges in route_defs.items():
        route_lines.append(f'    <route id="{route_id}" edges="{" ".join(edges)}"/>')

    random.seed(config.project.seed)
    vehicle_count = max(90, int(config.simulation.episode_seconds * config.simulation.arrival_rate * 2.2))
    route_ids = list(route_defs)
    for vehicle_id in range(vehicle_count):
        route_id = random.choice(route_ids)
        depart = round(vehicle_id * (config.simulation.episode_seconds / vehicle_count), 2)
        vehicle_type = "emergency" if random.random() < config.scenario.emergency_vehicle_rate else "passenger"
        route_lines.append(
            f'    <vehicle id="veh{vehicle_id}" type="{vehicle_type}" route="{route_id}" depart="{depart}"/>'
        )
    route_lines.append("</routes>")
    rou.write_text("\n".join(route_lines), encoding="utf-8")

    sumocfg.write_text(
        "\n".join(
            [
                "<configuration>",
                "    <input>",
                f'        <net-file value="{net.name}"/>',
                f'        <route-files value="{rou.name}"/>',
                "    </input>",
                "    <time>",
                '        <begin value="0"/>',
                f'        <end value="{config.simulation.episode_seconds}"/>',
                "    </time>",
                "</configuration>",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "nod": nod,
        "edg": edg,
        "rou": rou,
        "tll": tll,
        "sumocfg": sumocfg,
        "net": net,
        "layout": {"rows": max(1, rows), "cols": max(1, cols), "width": width, "height": height},
    }


def _generate_scanned_graph_assets(
    config: ProjectConfig,
    root: Path,
    nod: Path,
    edg: Path,
    rou: Path,
    tll: Path,
    sumocfg: Path,
    net: Path,
    scan_layout,
    map_x,
    map_y,
    width: float,
    height: float,
) -> dict[str, Path]:
    raw_nodes = scan_layout["nodes"] if isinstance(scan_layout, dict) else scan_layout.nodes
    raw_edges = scan_layout["edges"] if isinstance(scan_layout, dict) else scan_layout.edges

    mapped_nodes = {
        node["id"]: {
            "id": node["id"],
            "x": map_x(float(node["x"])),
            "y": map_y(float(node["y"])),
            "kind": node["kind"],
        }
        for node in raw_nodes
    }

    node_lines = ["<nodes>"]
    for node in mapped_nodes.values():
        node_type = "traffic_light" if node["kind"] == "junction" else "priority"
        node_lines.append(f'    <node id="{node["id"]}" x="{node["x"]}" y="{node["y"]}" type="{node_type}"/>')
    node_lines.append("</nodes>")
    nod.write_text("\n".join(node_lines), encoding="utf-8")

    edge_lines = ["<edges>"]
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in mapped_nodes}

    for edge in raw_edges:
        start = edge["from"]
        end = edge["to"]
        mapped_shape = " ".join(f"{map_x(float(x))},{map_y(float(y))}" for x, y in edge["shape"])
        edge_lines.append(
            f'    <edge id="{edge["id"]}_{start}_{end}" from="{start}" to="{end}" numLanes="1" speed="13.9" shape="{mapped_shape}"/>'
        )
        reverse_shape = " ".join(f"{map_x(float(x))},{map_y(float(y))}" for x, y in reversed(edge["shape"]))
        edge_lines.append(
            f'    <edge id="{edge["id"]}_{end}_{start}" from="{end}" to="{start}" numLanes="1" speed="13.9" shape="{reverse_shape}"/>'
        )
        adjacency[start].append(end)
        adjacency[end].append(start)

    edge_lines.append("</edges>")
    edg.write_text("\n".join(edge_lines), encoding="utf-8")

    tll.write_text(
        "\n".join(
            [
                "<additional>",
                '    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
                '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
                "</additional>",
            ]
        ),
        encoding="utf-8",
    )

    route_lines = [
        "<routes>",
        '    <vType id="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" maxSpeed="13.9"/>',
        '    <vType id="emergency" accel="3.0" decel="5.0" sigma="0.2" length="5" maxSpeed="16.0" color="1,0,0"/>',
    ]

    endpoints = [node_id for node_id, node in mapped_nodes.items() if node["kind"] != "junction"]
    route_defs: dict[str, list[str]] = {}
    route_meta: dict[str, dict[str, float | str]] = {}
    route_index = 0
    for start in endpoints:
        for end in endpoints:
            if start == end:
                continue
            path = _shortest_path(adjacency, start, end)
            if len(path) < 2:
                continue
            edges = [f"{_edge_prefix(scan_layout, path[i], path[i + 1])}_{path[i]}_{path[i + 1]}" for i in range(len(path) - 1)]
            route_id = f"r{route_index}"
            route_defs[route_id] = edges
            dx = abs(float(mapped_nodes[end]["x"]) - float(mapped_nodes[start]["x"]))
            dy = abs(float(mapped_nodes[end]["y"]) - float(mapped_nodes[start]["y"]))
            route_meta[route_id] = {
                "axis": "ew" if dx >= dy else "ns",
                "distance": dx + dy,
            }
            route_index += 1

    if not route_defs:
        node_ids = list(mapped_nodes)
        if len(node_ids) >= 2:
            route_defs["r0"] = [f"{raw_edges[0]['id']}_{raw_edges[0]['from']}_{raw_edges[0]['to']}"]
            route_meta["r0"] = {"axis": "ew", "distance": 1.0}

    for route_id, edges in route_defs.items():
        route_lines.append(f'    <route id="{route_id}" edges="{" ".join(edges)}"/>')

    random.seed(config.project.seed)
    vehicle_count = max(96, int(config.simulation.episode_seconds * config.simulation.arrival_rate * 2.3))
    route_ids = list(route_defs)
    if route_ids:
        avg_ns = sum(float(meta["distance"]) for route_id, meta in route_meta.items() if meta["axis"] == "ns")
        avg_ew = sum(float(meta["distance"]) for route_id, meta in route_meta.items() if meta["axis"] == "ew")
        dominant_axis = "ns" if avg_ns >= avg_ew else "ew"
    else:
        dominant_axis = "ew"
    for vehicle_id in range(vehicle_count):
        route_id = random.choice(route_ids)
        depart = round(vehicle_id * (config.simulation.episode_seconds / vehicle_count), 2)
        if route_ids:
            progress = depart / max(1.0, float(config.simulation.episode_seconds))
            if progress < 0.35:
                preferred_axis = dominant_axis
            elif progress < 0.7:
                preferred_axis = "ew" if dominant_axis == "ns" else "ns"
            else:
                preferred_axis = dominant_axis
            weighted_choices = []
            for candidate in route_ids:
                meta = route_meta.get(candidate, {"axis": preferred_axis, "distance": 1.0})
                weight = 1.0
                if meta["axis"] == preferred_axis:
                    weight = 3.4
                elif meta["axis"] == dominant_axis:
                    weight = 1.6
                weighted_choices.append(weight)
            route_id = random.choices(route_ids, weights=weighted_choices, k=1)[0]
        vehicle_type = "emergency" if random.random() < config.scenario.emergency_vehicle_rate else "passenger"
        route_lines.append(
            f'    <vehicle id="veh{vehicle_id}" type="{vehicle_type}" route="{route_id}" depart="{depart}"/>'
        )
    route_lines.append("</routes>")
    rou.write_text("\n".join(route_lines), encoding="utf-8")

    sumocfg.write_text(
        "\n".join(
            [
                "<configuration>",
                "    <input>",
                f'        <net-file value="{net.name}"/>',
                f'        <route-files value="{rou.name}"/>',
                "    </input>",
                "    <time>",
                '        <begin value="0"/>',
                f'        <end value="{config.simulation.episode_seconds}"/>',
                "    </time>",
                "</configuration>",
            ]
        ),
        encoding="utf-8",
    )

    return {
        "nod": nod,
        "edg": edg,
        "rou": rou,
        "tll": tll,
        "sumocfg": sumocfg,
        "net": net,
        "layout": {"rows": len(endpoints), "cols": len(mapped_nodes), "width": width, "height": height},
    }


def build_netconvert(assets: dict[str, Path], netconvert_binary: str = "netconvert") -> None:
    command = [
        netconvert_binary,
        "--node-files",
        str(assets["nod"]),
        "--edge-files",
        str(assets["edg"]),
        "--output-file",
        str(assets["net"]),
        "--default.lanewidth",
        "1.5",
        "--junctions.corner-detail",
        "0",
    ]
    subprocess.run(command, check=True)


def _boundary_routes(rows: int, cols: int) -> list[list[str]]:
    routes: list[list[str]] = []
    for row in range(rows):
        forward = []
        backward = []
        for col in range(cols - 1):
            forward.append(f"J{row}_{col}_to_J{row}_{col + 1}")
            backward.append(f"J{row}_{cols - col - 1}_to_J{row}_{cols - col - 2}")
        routes.extend([forward, backward])
    for col in range(cols):
        forward = []
        backward = []
        for row in range(rows - 1):
            forward.append(f"J{row}_{col}_to_J{row + 1}_{col}")
            backward.append(f"J{rows - row - 1}_{col}_to_J{rows - row - 2}_{col}")
        routes.extend([forward, backward])
    return [route for route in routes if route]


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


def _track_mid_x(track: list[tuple[float, float]]) -> float:
    return track[len(track) // 2][0]


def _track_mid_y(track: list[tuple[float, float]]) -> float:
    return track[len(track) // 2][1]


def _track_start_x(track: list[tuple[float, float]]) -> float:
    return track[0][0]


def _track_end_x(track: list[tuple[float, float]]) -> float:
    return track[-1][0]


def _track_start_y(track: list[tuple[float, float]]) -> float:
    return track[0][1]


def _track_end_y(track: list[tuple[float, float]]) -> float:
    return track[-1][1]


def _shortest_path(adjacency: dict[str, list[str]], start: str, end: str) -> list[str]:
    queue = [(start, [start])]
    visited = {start}
    while queue:
        node, path = queue.pop(0)
        if node == end:
            return path
        for neighbor in adjacency.get(node, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, path + [neighbor]))
    return []


def _edge_prefix(scan_layout, start: str, end: str) -> str:
    edges = scan_layout["edges"] if isinstance(scan_layout, dict) else scan_layout.edges
    for edge in edges:
        if (edge["from"] == start and edge["to"] == end) or (edge["from"] == end and edge["to"] == start):
            return edge["id"]
    return "E0"


def _compact_scanned_graph(scan_layout) -> dict[str, list[dict[str, object]]]:
    nodes = [
        {
            "id": node["id"],
            "x": float(node["x"]),
            "y": float(node["y"]),
            "kind": node["kind"],
        }
        for node in scan_layout.nodes
    ]
    edges = [
        {
            "id": edge["id"],
            "from": edge["from"],
            "to": edge["to"],
            "shape": [(float(x), float(y)) for x, y in edge["shape"]],
        }
        for edge in scan_layout.edges
    ]
    if not nodes or not edges:
        return {"nodes": nodes, "edges": edges}

    degrees = {node["id"]: 0 for node in nodes}
    for edge in edges:
        degrees[edge["from"]] += 1
        degrees[edge["to"]] += 1
    junctions = [node for node in nodes if degrees[node["id"]] >= 3]

    if len(junctions) == 1 and all(junctions[0]["id"] in (edge["from"], edge["to"]) for edge in edges):
        return _compact_single_junction_graph(nodes, edges, junctions[0])

    if len(nodes) <= 7 and len(junctions) <= 2:
        nodes, edges = _schematic_tree_layout(nodes, edges)
        return _scale_graph_to_box(nodes, edges, width=700.0, height=460.0, margin=50.0)

    nodes, edges = _orthogonalize_graph(nodes, edges)
    return _scale_graph_to_box(nodes, edges, width=760.0, height=500.0, margin=55.0)


def _schematic_tree_layout(nodes, edges):
    node_by_id = {node["id"]: dict(node) for node in nodes}
    adjacency: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    edge_map: dict[tuple[str, str], dict[str, object]] = {}
    for edge in edges:
        adjacency[edge["from"]].append(edge["to"])
        adjacency[edge["to"]].append(edge["from"])
        edge_map[(edge["from"], edge["to"])] = edge
        edge_map[(edge["to"], edge["from"])] = edge

    root = max(nodes, key=lambda node: (len(adjacency[node["id"]]), -float(node["y"])))
    coords: dict[str, tuple[float, float]] = {root["id"]: (0.0, 0.0)}
    queue = [(root["id"], None)]
    spacing = 180.0
    used_positions = {(0.0, 0.0)}

    direction_vectors = {
        "n": (0.0, -1.0),
        "s": (0.0, 1.0),
        "e": (1.0, 0.0),
        "w": (-1.0, 0.0),
        "ne": (1.0, -0.75),
        "nw": (-1.0, -0.75),
        "se": (1.0, 0.75),
        "sw": (-1.0, 0.75),
    }

    while queue:
        node_id, parent_id = queue.pop(0)
        current = node_by_id[node_id]
        children = [neighbor for neighbor in adjacency[node_id] if neighbor != parent_id]
        ranked = []
        for child_id in children:
            child = node_by_id[child_id]
            dx = float(child["x"]) - float(current["x"])
            dy = float(child["y"]) - float(current["y"])
            if abs(dx) >= abs(dy) * 1.4:
                direction = "e" if dx >= 0 else "w"
            elif abs(dy) >= abs(dx) * 1.4:
                direction = "s" if dy >= 0 else "n"
            else:
                if dx >= 0 and dy >= 0:
                    direction = "se"
                elif dx >= 0 and dy < 0:
                    direction = "ne"
                elif dx < 0 and dy >= 0:
                    direction = "sw"
                else:
                    direction = "nw"
            ranked.append((child_id, direction))

        for child_id, direction in ranked:
            if child_id in coords:
                continue
            base_x, base_y = coords[node_id]
            vx, vy = direction_vectors[direction]
            candidate = (round(base_x + vx * spacing, 2), round(base_y + vy * spacing, 2))
            bump = 0
            while candidate in used_positions:
                bump += 1
                if direction in {"n", "s"}:
                    candidate = (round(base_x + (bump * 55.0), 2), round(base_y + vy * spacing, 2))
                elif direction in {"e", "w"}:
                    candidate = (round(base_x + vx * spacing, 2), round(base_y + (bump * 55.0), 2))
                else:
                    candidate = (
                        round(base_x + vx * spacing, 2),
                        round(base_y + vy * spacing + bump * 40.0, 2),
                    )
            coords[child_id] = candidate
            used_positions.add(candidate)
            queue.append((child_id, node_id))

    layout_nodes = [
        {
            "id": node["id"],
            "x": coords.get(node["id"], (0.0, 0.0))[0],
            "y": coords.get(node["id"], (0.0, 0.0))[1],
            "kind": "junction" if len(adjacency[node["id"]]) >= 3 else node["kind"],
        }
        for node in nodes
    ]
    layout_by_id = {node["id"]: node for node in layout_nodes}
    layout_edges = []
    for edge in edges:
        start = layout_by_id[edge["from"]]
        end = layout_by_id[edge["to"]]
        shape = _straight_or_single_bend(
            (float(start["x"]), float(start["y"])),
            (float(end["x"]), float(end["y"])),
        )
        layout_edges.append(
            {
                "id": edge["id"],
                "from": edge["from"],
                "to": edge["to"],
                "shape": shape,
            }
        )
    return layout_nodes, layout_edges


def _straight_or_single_bend(start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    if abs(start[0] - end[0]) < 1e-6 or abs(start[1] - end[1]) < 1e-6:
        return [start, end]
    bend = (end[0], start[1])
    return [start, bend, end]


def _orthogonalize_graph(nodes, edges):
    node_by_id = {node["id"]: dict(node) for node in nodes}
    parent_x = {node["id"]: node["id"] for node in nodes}
    parent_y = {node["id"]: node["id"] for node in nodes}

    def find(parent, item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(parent, left, right):
        left_root = find(parent, left)
        right_root = find(parent, right)
        if left_root != right_root:
            parent[right_root] = left_root

    edge_orientations: dict[str, str] = {}
    for edge in edges:
        start = node_by_id[edge["from"]]
        end = node_by_id[edge["to"]]
        dx = float(end["x"]) - float(start["x"])
        dy = float(end["y"]) - float(start["y"])
        orientation = "h" if abs(dx) >= abs(dy) else "v"
        edge_orientations[edge["id"]] = orientation
        if orientation == "h":
            union(parent_y, start["id"], end["id"])
        else:
            union(parent_x, start["id"], end["id"])

    x_groups: dict[str, list[float]] = {}
    y_groups: dict[str, list[float]] = {}
    for node in nodes:
        x_groups.setdefault(find(parent_x, node["id"]), []).append(float(node["x"]))
        y_groups.setdefault(find(parent_y, node["id"]), []).append(float(node["y"]))

    group_x = {group: sum(values) / len(values) for group, values in x_groups.items()}
    group_y = {group: sum(values) / len(values) for group, values in y_groups.items()}

    orth_nodes = []
    for node in nodes:
        x_group = find(parent_x, node["id"])
        y_group = find(parent_y, node["id"])
        orth_nodes.append(
            {
                "id": node["id"],
                "x": group_x.get(x_group, float(node["x"])),
                "y": group_y.get(y_group, float(node["y"])),
                "kind": node["kind"],
            }
        )
    orth_by_id = {node["id"]: node for node in orth_nodes}

    orth_edges = []
    for edge in edges:
        start = orth_by_id[edge["from"]]
        end = orth_by_id[edge["to"]]
        if edge_orientations[edge["id"]] == "h":
            shape = [
                (float(start["x"]), float(start["y"])),
                (float(end["x"]), float(start["y"])),
            ]
        else:
            shape = [
                (float(start["x"]), float(start["y"])),
                (float(start["x"]), float(end["y"])),
            ]
        orth_edges.append(
            {
                "id": edge["id"],
                "from": edge["from"],
                "to": edge["to"],
                "shape": shape,
            }
        )
    return orth_nodes, orth_edges


def _compact_single_junction_graph(nodes, edges, junction):
    node_by_id = {node["id"]: dict(node) for node in nodes}
    center = (220.0, 230.0)
    kept_edges = []
    bucket_members: dict[int, list[tuple[dict[str, object], str, float, float]]] = {}

    for edge in edges:
        endpoint_id = edge["to"] if edge["from"] == junction["id"] else edge["from"]
        endpoint = node_by_id[endpoint_id]
        angle = math.atan2(endpoint["y"] - junction["y"], endpoint["x"] - junction["x"])
        bucket = int(round(angle / (math.pi / 4)))
        distance = math.hypot(endpoint["x"] - junction["x"], endpoint["y"] - junction["y"])
        bucket_members.setdefault(bucket, []).append((edge, endpoint_id, distance, angle))

    bucket_choice: dict[int, tuple[dict[str, object], str, float, float]] = {}
    for bucket, members in bucket_members.items():
        bucket_choice[bucket] = max(members, key=lambda item: item[2])

    east_buckets = {0, 1, -1}
    west_buckets = {4, -4, 3, -3}
    north_buckets = {-2}
    south_buckets = {2}

    east_items = [item for bucket, item in bucket_choice.items() if bucket in east_buckets]
    west_items = [item for bucket, item in bucket_choice.items() if bucket in west_buckets]
    north_items = [item for bucket, item in bucket_choice.items() if bucket in north_buckets]
    south_items = [item for bucket, item in bucket_choice.items() if bucket in south_buckets]

    if not north_items:
        north_items = [item for bucket, item in bucket_choice.items() if bucket < -1 and item not in west_items]
    if not south_items:
        south_items = [item for bucket, item in bucket_choice.items() if bucket > 1 and item not in west_items]

    east_sorted = sorted(east_items, key=lambda item: item[3])
    west_sorted = sorted(west_items, key=lambda item: item[3])

    compact_nodes = [{"id": junction["id"], "x": center[0], "y": center[1], "kind": "junction"}]
    endpoint_positions: dict[str, tuple[float, float]] = {}

    if north_items:
        endpoint_positions[north_items[0][1]] = (center[0], center[1] - 170.0)
    if south_items:
        endpoint_positions[south_items[0][1]] = (center[0], center[1] + 170.0)

    east_offsets = [-90.0, 0.0, 90.0]
    if len(east_sorted) == 1:
        east_offsets = [0.0]
    elif len(east_sorted) == 2:
        east_offsets = [-55.0, 55.0]
    elif len(east_sorted) >= 3:
        east_offsets = [-95.0, 0.0, 95.0]
    for item, offset in zip(east_sorted[:3], east_offsets, strict=False):
        endpoint_positions[item[1]] = (center[0] + 250.0, center[1] + offset)

    west_offsets = [-70.0, 70.0]
    if len(west_sorted) == 1:
        west_offsets = [0.0]
    for item, offset in zip(west_sorted[:2], west_offsets, strict=False):
        endpoint_positions[item[1]] = (center[0] - 180.0, center[1] + offset)

    # Any leftover rare endpoints are placed by angle, but still close and schematic.
    for _, endpoint_id, _, angle in bucket_choice.values():
        if endpoint_id in endpoint_positions:
            continue
        endpoint_positions[endpoint_id] = (
            round(center[0] + math.cos(angle) * 180.0, 2),
            round(center[1] + math.sin(angle) * 150.0, 2),
        )

    for endpoint_id, (x, y) in endpoint_positions.items():
        compact_nodes.append(
            {
                "id": endpoint_id,
                "x": round(x, 2),
                "y": round(y, 2),
                "kind": "endpoint",
            }
        )

    compact_by_id = {node["id"]: node for node in compact_nodes}
    filtered_edges = [item[0] for item in bucket_choice.values()]
    for edge in filtered_edges:
        start = edge["from"]
        end = edge["to"]
        start_pos = compact_by_id[start]
        end_pos = compact_by_id[end]
        shape = _junction_schematic_shape(
            (start_pos["x"], start_pos["y"]),
            (end_pos["x"], end_pos["y"]),
            center,
        )
        kept_edges.append(
            {
                "id": edge["id"],
                "from": start,
                "to": end,
                "shape": shape,
            }
        )
    return {"nodes": compact_nodes, "edges": kept_edges}


def _junction_schematic_shape(start: tuple[float, float], end: tuple[float, float], center: tuple[float, float]) -> list[tuple[float, float]]:
    if start == center or end == center:
        other = end if start == center else start
        if abs(other[0] - center[0]) < 1e-6 or abs(other[1] - center[1]) < 1e-6:
            return [start, end]
        bend = (other[0], center[1]) if other[0] >= center[0] else (center[0], other[1])
        return [start, bend, end]
    return _straight_or_single_bend(start, end)


def _scale_graph_to_box(nodes, edges, width: float, height: float, margin: float):
    xs = [node["x"] for node in nodes]
    ys = [node["y"] for node in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(1.0, max_x - min_x)
    span_y = max(1.0, max_y - min_y)

    def sx(x: float) -> float:
        return round(margin + ((x - min_x) / span_x) * (width - margin * 2), 2)

    def sy(y: float) -> float:
        return round(margin + ((max_y - y) / span_y) * (height - margin * 2), 2)

    compact_nodes = [
        {"id": node["id"], "x": sx(node["x"]), "y": sy(node["y"]), "kind": node["kind"]}
        for node in nodes
    ]
    compact_edges = []
    for edge in edges:
        compact_edges.append(
            {
                "id": edge["id"],
                "from": edge["from"],
                "to": edge["to"],
                "shape": [(sx(x), sy(y)) for x, y in edge["shape"]],
            }
        )
    return {"nodes": compact_nodes, "edges": compact_edges}


def _track_intersection(horizontal_track: list[tuple[float, float]], vertical_track: list[tuple[float, float]]) -> tuple[float, float] | None:
    if len(horizontal_track) < 2 or len(vertical_track) < 2:
        return None
    x_guess = _interpolate_track_x(vertical_track, _track_mid_y(horizontal_track))
    if x_guess < min(point[0] for point in horizontal_track) - 30 or x_guess > max(point[0] for point in horizontal_track) + 30:
        return None
    y_guess = _interpolate_track_y(horizontal_track, x_guess)
    if y_guess < min(point[1] for point in vertical_track) - 30 or y_guess > max(point[1] for point in vertical_track) + 30:
        return None
    x_refined = _interpolate_track_x(vertical_track, y_guess)
    if abs(x_refined - x_guess) > 40:
        return None
    return (round(x_refined, 2), round(y_guess, 2))


def _extract_track_segment(track: list[tuple[float, float]], start_value: float, end_value: float, axis: str) -> list[tuple[float, float]]:
    if axis == "x":
        points = sorted(track, key=lambda item: item[0])
        lo, hi = sorted((start_value, end_value))
        segment = [point for point in points if lo - 5 <= point[0] <= hi + 5]
    else:
        points = sorted(track, key=lambda item: item[1], reverse=True)
        lo, hi = sorted((start_value, end_value))
        segment = [point for point in points if lo - 5 <= point[1] <= hi + 5]
    if len(segment) < 2:
        return [points[0], points[-1]]
    return segment
