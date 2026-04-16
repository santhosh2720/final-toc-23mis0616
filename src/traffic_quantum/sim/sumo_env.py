from __future__ import annotations

from pathlib import Path
import os
import uuid
import xml.etree.ElementTree as ET

from traffic_quantum.config import ProjectConfig
from traffic_quantum.models import (
    APPROACHES,
    ApproachObservation,
    IntersectionObservation,
    NetworkObservation,
    StepResult,
)
from traffic_quantum.sim.base import SimulationBackend

try:
    import traci
except ImportError:  # pragma: no cover
    traci = None

try:
    import sumolib
except ImportError:  # pragma: no cover
    sumolib = None


class SumoEnvironment(SimulationBackend):
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self._started = False
        self.time_seconds = 0
        self.connection_label = self._next_connection_label()
        self.metrics = {
            "total_wait": 0.0,
            "total_queue": 0.0,
            "throughput": 0.0,
            "steps": 0,
        }
        self.phase_age: dict[str, int] = {}
        self.phase_names: dict[str, dict[int, str]] = {}
        self.phase_indices: dict[str, dict[str, int]] = {}
        self.adjacency: dict[str, list[str]] = {}
        self.approach_lookup: dict[str, dict[str, str]] = {}
        self.net = None

    def reset(self) -> NetworkObservation:
        self.close()
        if traci is None:
            raise RuntimeError("TraCI is not installed. Install SUMO python bindings first.")
        self.connection_label = self._next_connection_label()
        sumo_binary = self._discover_sumo_binary()
        sumocfg = self.config.sumo.sumocfg_path
        if not sumocfg:
            raise RuntimeError("SUMO backend selected but no sumocfg_path was provided.")
        if not Path(sumocfg).exists():
            raise RuntimeError(f"SUMO config not found: {sumocfg}")
        self._prepare_network_metadata(Path(sumocfg))
        command = [sumo_binary, "-c", sumocfg]
        if not self.config.sumo.use_gui:
            command.extend(["--quit-on-end", "--no-warnings", "true", "--no-step-log", "true", "--duration-log.disable", "true"])
        traci.start(command, label=self.connection_label)
        self.conn = traci.getConnection(self.connection_label)
        self._started = True
        self.time_seconds = 0
        self.metrics = {
            "total_wait": 0.0,
            "total_queue": 0.0,
            "throughput": 0.0,
            "steps": 0,
        }
        self.phase_age = {tls_id: 0 for tls_id in self.conn.trafficlight.getIDList()}
        self._build_phase_maps()
        for _ in range(self.config.simulation.warmup_seconds):
            self.conn.simulationStep()
        return self._observe()

    def step(self, actions: dict[str, str]) -> StepResult:
        if not self._started:
            raise RuntimeError("SUMO environment has not been reset.")
        for tls_id, phase_name in actions.items():
            self._apply_phase(tls_id, phase_name)
        for _ in range(self.config.simulation.control_interval):
            previous_arrived = self.conn.simulation.getArrivedNumber()
            self.conn.simulationStep()
            self.time_seconds += 1
            self.metrics["throughput"] += max(0, self.conn.simulation.getArrivedNumber() - previous_arrived)
            self._collect_step_metrics()
        observation = self._observe()
        done = self.time_seconds >= self.config.simulation.episode_seconds
        avg_wait = self.metrics["total_wait"] / max(1, self.metrics["steps"])
        avg_queue = self.metrics["total_queue"] / max(1, self.metrics["steps"])
        reward = -avg_wait - 0.25 * avg_queue + 0.05 * self.metrics["throughput"]
        return StepResult(
            observation=observation,
            reward=reward,
            done=done,
            info={"avg_wait": avg_wait, "avg_queue": avg_queue},
        )

    def close(self) -> None:
        if self._started and traci is not None:
            try:
                self.conn.close()
            except Exception:
                pass
        self._started = False
        self.phase_age = {}

    def _next_connection_label(self) -> str:
        return f"traffic_quantum_{self.config.project.seed}_{uuid.uuid4().hex[:8]}"

    def _discover_sumo_binary(self) -> str:
        candidates = [
            self.config.sumo.sumo_binary,
            os.environ.get("SUMO_BINARY", ""),
        ]
        sumo_home = os.environ.get("SUMO_HOME")
        if sumo_home:
            candidates.extend(
                [
                    str(Path(sumo_home) / "bin" / "sumo.exe"),
                    str(Path(sumo_home) / "bin" / "sumo"),
                ]
            )
        candidates.extend(
            [
                r"C:\Program Files\Eclipse\Sumo\bin\sumo.exe",
                r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe",
            ]
        )
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        raise RuntimeError(
            "Could not find SUMO binary. Set sumo_binary in config or define SUMO_HOME/SUMO_BINARY."
        )

    def _apply_phase(self, tls_id: str, phase_name: str) -> None:
        current_program = self.conn.trafficlight.getAllProgramLogics(tls_id)
        if not current_program:
            return
        current_phase = self.conn.trafficlight.getPhase(tls_id)
        phase_lookup = self.phase_indices.get(tls_id, {})
        phase_lookup = {
            "hold": current_phase,
            "ns_green": phase_lookup.get("ns_green", current_phase),
            "ew_green": phase_lookup.get("ew_green", current_phase),
            "pedestrian_all_red": phase_lookup.get("pedestrian_all_red", current_phase),
        }
        target_phase = phase_lookup.get(phase_name, current_phase)
        if current_phase == target_phase:
            self.phase_age[tls_id] = self.phase_age.get(tls_id, 0) + self.config.simulation.control_interval
        else:
            self.phase_age[tls_id] = 0
        self.conn.trafficlight.setPhase(tls_id, target_phase)

    def _collect_step_metrics(self) -> None:
        total_wait = 0.0
        total_queue = 0.0
        for lane_id in self.conn.lane.getIDList():
            total_wait += self.conn.lane.getWaitingTime(lane_id)
            total_queue += self.conn.lane.getLastStepHaltingNumber(lane_id)
        self.metrics["total_wait"] += total_wait
        self.metrics["total_queue"] += total_queue
        self.metrics["steps"] += 1

    def _observe(self) -> NetworkObservation:
        intersections = {}
        adjacency = dict(self.adjacency)
        tls_ids = self.conn.trafficlight.getIDList()
        for tls_id in tls_ids:
            controlled_lanes = list(dict.fromkeys(self.conn.trafficlight.getControlledLanes(tls_id)))
            lane_groups = {name: [] for name in APPROACHES}
            edge_approaches = self.approach_lookup.get(tls_id, {})
            for lane_id in controlled_lanes:
                if lane_id.startswith(":"):
                    continue
                edge_id = self.conn.lane.getEdgeID(lane_id)
                approach = edge_approaches.get(edge_id)
                if approach is None:
                    lane_lower = lane_id.lower()
                    if "north" in lane_lower or lane_lower.endswith("_n"):
                        approach = "north"
                    elif "south" in lane_lower or lane_lower.endswith("_s"):
                        approach = "south"
                    elif "east" in lane_lower or lane_lower.endswith("_e"):
                        approach = "east"
                    else:
                        approach = "west"
                lane_groups[approach].append(lane_id)
            approaches = {}
            for approach, lane_ids in lane_groups.items():
                if lane_ids:
                    queue = sum(self.conn.lane.getLastStepHaltingNumber(lane) for lane in lane_ids)
                    speed = sum(self.conn.lane.getLastStepMeanSpeed(lane) for lane in lane_ids) / len(lane_ids)
                    waiting = sum(self.conn.lane.getWaitingTime(lane) for lane in lane_ids)
                    occupancy = sum(self.conn.lane.getLastStepOccupancy(lane) for lane in lane_ids) / (
                        100.0 * len(lane_ids)
                    )
                else:
                    queue = speed = waiting = occupancy = 0.0
                approaches[approach] = ApproachObservation(
                    queue_length=float(queue),
                    avg_speed=float(speed),
                    occupancy=float(occupancy),
                    waiting_time=float(waiting),
                )
            intersections[tls_id] = IntersectionObservation(
                intersection_id=tls_id,
                approaches=approaches,
                current_phase=self.phase_names.get(tls_id, {}).get(
                    self.conn.trafficlight.getPhase(tls_id),
                    "hold",
                ),
                phase_age=self.phase_age.get(tls_id, 0),
            )
        return NetworkObservation(
            time_seconds=self.time_seconds,
            intersections=intersections,
            adjacency=adjacency,
            metadata={"backend": "sumo"},
        )

    def _prepare_network_metadata(self, sumocfg_path: Path) -> None:
        self.net = None
        self.adjacency = {}
        self.approach_lookup = {}
        if sumolib is None:
            return
        root = ET.parse(sumocfg_path).getroot()
        net_path = None
        for element in root.findall(".//input/net-file"):
            net_path = element.attrib.get("value")
            break
        if not net_path:
            return
        candidate = (sumocfg_path.parent / net_path).resolve()
        if not candidate.exists():
            return
        self.net = sumolib.net.readNet(str(candidate))
        tls_ids = {tls.getID() for tls in self.net.getTrafficLights()}
        adjacency = {tls_id: set() for tls_id in tls_ids}
        for node in self.net.getNodes():
            tls_id = node.getID()
            if tls_id not in adjacency:
                continue
            neighbors = set()
            incoming_approaches: dict[str, str] = {}
            node_x, node_y = node.getCoord()
            for edge in list(node.getIncoming()) + list(node.getOutgoing()):
                other = edge.getFromNode().getID() if edge.getToNode().getID() == tls_id else edge.getToNode().getID()
                if other in adjacency and other != tls_id:
                    neighbors.add(other)
            for edge in node.getIncoming():
                from_x, from_y = edge.getFromNode().getCoord()
                dx = node_x - from_x
                dy = node_y - from_y
                if abs(dx) >= abs(dy):
                    approach = "west" if from_x < node_x else "east"
                else:
                    approach = "south" if from_y < node_y else "north"
                incoming_approaches[edge.getID()] = approach
            adjacency[tls_id] = neighbors
            self.approach_lookup[tls_id] = incoming_approaches
        self.adjacency = {tls_id: sorted(values) for tls_id, values in adjacency.items()}

    def _build_phase_maps(self) -> None:
        self.phase_names = {}
        self.phase_indices = {}
        for tls_id in self.conn.trafficlight.getIDList():
            current_program = self.conn.trafficlight.getAllProgramLogics(tls_id)
            if not current_program:
                self.phase_names[tls_id] = {0: "hold"}
                self.phase_indices[tls_id] = {"hold": 0, "ns_green": 0, "ew_green": 0}
                continue
            definition = current_program[0]
            edge_approaches = self.approach_lookup.get(tls_id, {})
            controlled_links = self.conn.trafficlight.getControlledLinks(tls_id)
            phase_scores: list[tuple[int, int, int, int]] = []
            for phase_index, phase in enumerate(definition.phases):
                ns_score = 0
                ew_score = 0
                green_score = 0
                seen_lanes: set[str] = set()
                for signal_index, links in enumerate(controlled_links):
                    if signal_index >= len(phase.state):
                        break
                    if phase.state[signal_index] not in {"g", "G"}:
                        continue
                    for link in links:
                        if not link:
                            continue
                        incoming_lane = link[0]
                        if not incoming_lane or incoming_lane.startswith(":") or incoming_lane in seen_lanes:
                            continue
                        seen_lanes.add(incoming_lane)
                        edge_id = self.conn.lane.getEdgeID(incoming_lane)
                        approach = edge_approaches.get(edge_id)
                        if approach in {"north", "south"}:
                            ns_score += 1
                        elif approach in {"east", "west"}:
                            ew_score += 1
                        green_score += 1
                phase_scores.append((phase_index, ns_score, ew_score, green_score))

            if not phase_scores:
                self.phase_names[tls_id] = {0: "hold"}
                self.phase_indices[tls_id] = {"hold": 0, "ns_green": 0, "ew_green": 0}
                continue

            ns_phase = max(
                phase_scores,
                key=lambda item: (item[1] - item[2], item[1], item[3]),
            )[0]
            ew_phase = max(
                phase_scores,
                key=lambda item: (item[2] - item[1], item[2], item[3]),
            )[0]
            red_candidates = [item[0] for item in phase_scores if item[3] == 0]
            red_phase = red_candidates[0] if red_candidates else None

            phase_name_map: dict[int, str] = {}
            phase_index_map: dict[str, int] = {"ns_green": ns_phase, "ew_green": ew_phase}
            phase_name_map[ns_phase] = "ns_green"
            if ew_phase != ns_phase:
                phase_name_map[ew_phase] = "ew_green"
            if red_phase is not None:
                phase_name_map[red_phase] = "pedestrian_all_red"
                phase_index_map["pedestrian_all_red"] = red_phase
            self.phase_names[tls_id] = phase_name_map
            self.phase_indices[tls_id] = phase_index_map
