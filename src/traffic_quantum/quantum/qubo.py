from __future__ import annotations

import numpy as np

from traffic_quantum.config import ProjectConfig
from traffic_quantum.models import CongestionForecast, NetworkObservation, QuboProblem


class TrafficQuboBuilder:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.actions = [action for action in config.phase_actions if action != "hold"]
        if "hold" in config.phase_actions:
            self.actions.insert(0, "hold")

    def build(self, observation: NetworkObservation, forecast: CongestionForecast) -> QuboProblem:
        node_ids = observation.ordered_ids()
        variable_map = [(node_id, action) for node_id in node_ids for action in self.actions]
        n = len(variable_map)
        q = np.zeros((n, n), dtype=float)
        local_costs: dict[tuple[str, str], float] = {}
        index_lookup = {entry: idx for idx, entry in enumerate(variable_map)}

        for node_id in node_ids:
            item = observation.intersections[node_id]
            pred = forecast.by_intersection[node_id]
            ns_pressure = item.approaches["north"].queue_length + item.approaches["south"].queue_length
            ew_pressure = item.approaches["east"].queue_length + item.approaches["west"].queue_length
            total_pressure = ns_pressure + ew_pressure + 1e-6
            queue_intensity = min(1.5, item.total_queue / max(1.0, self.config.simulation.max_queue * 0.6))
            wait_intensity = min(
                1.5,
                item.total_wait / max(1.0, self.config.simulation.control_interval * 20.0),
            )
            for action in self.actions:
                local_score = self._local_cost(
                    action=action,
                    ns_pressure=ns_pressure / total_pressure,
                    ew_pressure=ew_pressure / total_pressure,
                    queue_intensity=queue_intensity,
                    wait_intensity=wait_intensity,
                    predicted_congestion=pred.congestion_score,
                    emergency=item.emergency_pressure,
                    phase_age=item.phase_age,
                    current_phase=item.current_phase,
                )
                local_costs[(node_id, action)] = local_score
                q[index_lookup[(node_id, action)], index_lookup[(node_id, action)]] += local_score

            same_node_indices = [index_lookup[(node_id, action)] for action in self.actions]
            for i in same_node_indices:
                q[i, i] -= self.config.controller.one_hot_penalty
                for j in same_node_indices:
                    if i != j:
                        q[i, j] += self.config.controller.one_hot_penalty

        for node_id, neighbors in observation.adjacency.items():
            for neighbor in neighbors:
                if neighbor <= node_id:
                    continue
                for action in self.actions:
                    if action not in {"ns_green", "ew_green"}:
                        continue
                    i = index_lookup[(node_id, action)]
                    j = index_lookup[(neighbor, action)]
                    q[i, j] += self.config.controller.coordination_bonus
                    q[j, i] += self.config.controller.coordination_bonus
        return QuboProblem(matrix=q, variable_map=variable_map, local_costs=local_costs)

    def _local_cost(
        self,
        action: str,
        ns_pressure: float,
        ew_pressure: float,
        queue_intensity: float,
        wait_intensity: float,
        predicted_congestion: float,
        emergency: float,
        phase_age: int,
        current_phase: str,
    ) -> float:
        intensity = 0.58 * queue_intensity + 0.42 * wait_intensity
        if action == "ns_green":
            fit = 1.85 * ns_pressure - 0.75 * ew_pressure + 0.95 * intensity
        elif action == "ew_green":
            fit = 1.85 * ew_pressure - 0.75 * ns_pressure + 0.95 * intensity
        elif action == "hold":
            fit = 0.08 if intensity < 0.18 else -1.55 * intensity
        else:
            fit = -1.85 * intensity
        if action == current_phase and action in {"ns_green", "ew_green"} and phase_age < self.config.controller.max_green_seconds:
            fit += 0.18
        fit += 0.85 * predicted_congestion * (1.0 if action in {"ns_green", "ew_green"} else -1.2)
        fit += 0.8 * emergency * (1.0 if action in {"ns_green", "ew_green"} else -1.0)
        return -fit
