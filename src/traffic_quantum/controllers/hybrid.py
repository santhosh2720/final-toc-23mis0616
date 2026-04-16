from __future__ import annotations

from dataclasses import dataclass

from traffic_quantum.controllers.base import Controller
from traffic_quantum.models import NetworkObservation
from traffic_quantum.quantum.policy import PolicySample, QuantumPolicyNetwork
from traffic_quantum.quantum.predictor import QuantumGraphPredictor
from traffic_quantum.quantum.qaoa import QAOASolver
from traffic_quantum.quantum.qubo import TrafficQuboBuilder


@dataclass(slots=True)
class HybridDecisionContext:
    forecast_scores: dict[str, float]
    optimizer_assignment: dict[str, str]


class HybridQuantumController(Controller):
    def __init__(self, config) -> None:
        super().__init__(config)
        self.predictor = QuantumGraphPredictor(config.project.seed, layers=4)
        self.qubo_builder = TrafficQuboBuilder(config)
        self.optimizer = QAOASolver(
            seed=config.project.seed + 3,
            layers=config.controller.qaoa_layers,
            trials=config.controller.qaoa_trials,
        )
        self.policy = QuantumPolicyNetwork(config.phase_actions, seed=config.project.seed + 9)
        self.last_context: HybridDecisionContext | None = None
        self.training_buffer: list[PolicySample] = []
        self.policy_updates = 0

    def act(self, observation: NetworkObservation) -> dict[str, str]:
        forecast = self.predictor.predict(observation, self.config.controller.prediction_horizon_steps)
        qubo = self.qubo_builder.build(observation, forecast)
        optimized = self.optimizer.solve(qubo)
        actions = dict(optimized.assignment)
        global_ns = 0.0
        global_ew = 0.0
        for item in observation.intersections.values():
            global_ns += item.approaches["north"].queue_length + item.approaches["south"].queue_length
            global_ew += item.approaches["east"].queue_length + item.approaches["west"].queue_length
        dominant_axis = "ns_green" if global_ns >= global_ew else "ew_green"

        for node_id in observation.ordered_ids():
            current = observation.intersections[node_id]
            current_phase = current.current_phase or "hold"
            proposed = actions.get(node_id, current_phase)
            ns_pressure = current.approaches["north"].queue_length + current.approaches["south"].queue_length
            ew_pressure = current.approaches["east"].queue_length + current.approaches["west"].queue_length
            ns_wait = current.approaches["north"].waiting_time + current.approaches["south"].waiting_time
            ew_wait = current.approaches["east"].waiting_time + current.approaches["west"].waiting_time
            total_pressure = ns_pressure + ew_pressure
            imbalance = abs(ns_pressure - ew_pressure) / max(1.0, total_pressure)
            dominant_local = "ns_green" if ns_pressure >= ew_pressure else "ew_green"
            current_axis_pressure = ns_pressure if current_phase == "ns_green" else ew_pressure if current_phase == "ew_green" else 0.0
            opposite_axis_pressure = ew_pressure if current_phase == "ns_green" else ns_pressure if current_phase == "ew_green" else 0.0
            current_axis_wait = ns_wait if current_phase == "ns_green" else ew_wait if current_phase == "ew_green" else 0.0
            opposite_axis_wait = ew_wait if current_phase == "ns_green" else ns_wait if current_phase == "ew_green" else 0.0
            fair_switch_age = min(
                self.config.controller.max_green_seconds,
                max(self.config.controller.min_green_seconds + 4, 14),
            )
            if total_pressure >= 1.4 or imbalance >= 0.45:
                fair_switch_age = max(self.config.controller.min_green_seconds, fair_switch_age - 4)

            if current.phase_age < self.config.controller.min_green_seconds and proposed != current_phase:
                actions[node_id] = current.current_phase
                continue

            if total_pressure >= 0.35 and proposed in {"hold", "pedestrian_all_red"}:
                proposed = dominant_local

            if total_pressure >= 1.2 and imbalance >= 0.18:
                proposed = dominant_local
            elif total_pressure >= 0.55 and proposed == "hold":
                proposed = dominant_axis

            if (
                current_phase in {"ns_green", "ew_green"}
                and current.phase_age < fair_switch_age
                and proposed != current_phase
                and (
                    current_axis_pressure >= opposite_axis_pressure * 1.18
                    or current_axis_wait >= opposite_axis_wait * 1.12
                )
            ):
                proposed = current_phase

            if (
                current_phase in {"ns_green", "ew_green"}
                and current.phase_age >= fair_switch_age
                and (
                    opposite_axis_pressure >= current_axis_pressure * 0.55
                    or opposite_axis_wait >= current_axis_wait * 0.58
                )
            ):
                proposed = "ew_green" if current_phase == "ns_green" else "ns_green"
            elif current.phase_age >= self.config.controller.max_green_seconds:
                proposed = "ew_green" if current_phase == "ns_green" else "ns_green"

            features = self.policy.extract_features(
                observation,
                node_id,
                forecast.by_intersection[node_id].congestion_score,
            )
            policy_action, _, probs = self.policy.choose(features, greedy=True)
            if (
                self.policy_updates > 0
                and probs.max(initial=0.0) > 0.7
                and policy_action in {"ns_green", "ew_green"}
                and total_pressure >= 0.5
            ):
                proposed = policy_action
            actions[node_id] = proposed

        coordinated = dict(actions)
        strong_global_axis = None
        if max(global_ns, global_ew) >= 1.15 * min(global_ns, global_ew) and max(global_ns, global_ew) >= 1.5:
            strong_global_axis = dominant_axis

        for node_id in observation.ordered_ids():
            current = observation.intersections[node_id]
            ns_pressure = current.approaches["north"].queue_length + current.approaches["south"].queue_length
            ew_pressure = current.approaches["east"].queue_length + current.approaches["west"].queue_length
            total_pressure = ns_pressure + ew_pressure
            if total_pressure < 0.45:
                continue

            ns_neighbor_votes = 0
            ew_neighbor_votes = 0
            for neighbor_id in observation.adjacency.get(node_id, []):
                neighbor_action = actions.get(neighbor_id)
                if neighbor_action == "ns_green":
                    ns_neighbor_votes += 1
                elif neighbor_action == "ew_green":
                    ew_neighbor_votes += 1

            local_choice = coordinated[node_id]
            if ns_neighbor_votes >= ew_neighbor_votes + 2 and ns_pressure >= ew_pressure * 0.65:
                local_choice = "ns_green"
            elif ew_neighbor_votes >= ns_neighbor_votes + 2 and ew_pressure >= ns_pressure * 0.65:
                local_choice = "ew_green"

            if strong_global_axis == "ns_green" and ns_pressure >= ew_pressure * 0.7:
                local_choice = "ns_green"
            elif strong_global_axis == "ew_green" and ew_pressure >= ns_pressure * 0.7:
                local_choice = "ew_green"

            coordinated[node_id] = local_choice

        actions = coordinated

        self.last_context = HybridDecisionContext(
            forecast_scores={
                node_id: item.congestion_score for node_id, item in forecast.by_intersection.items()
            },
            optimizer_assignment=dict(optimized.assignment),
        )
        return actions

    def record_reward(self, observation: NetworkObservation, actions: dict[str, str], reward: float) -> None:
        if self.last_context is None:
            return
        for node_id, action in actions.items():
            try:
                action_index = self.config.phase_actions.index(action)
            except ValueError:
                continue
            features = self.policy.extract_features(
                observation,
                node_id,
                self.last_context.forecast_scores.get(node_id, 0.0),
            )
            self.training_buffer.append(
                PolicySample(features=features, action_index=action_index, reward=reward)
            )

    def update_policy(self, max_batch: int = 128) -> float:
        batch = self.training_buffer[:max_batch]
        self.training_buffer = self.training_buffer[max_batch:]
        if not batch:
            return 0.0
        loss = self.policy.update(batch)
        self.policy_updates += 1
        return loss
