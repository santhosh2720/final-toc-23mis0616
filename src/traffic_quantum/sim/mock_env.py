from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Iterable

import numpy as np

from traffic_quantum.config import ProjectConfig
from traffic_quantum.models import (
    APPROACHES,
    ApproachObservation,
    IntersectionObservation,
    NetworkObservation,
    StepResult,
)
from traffic_quantum.sim.base import SimulationBackend


NS_APPROACHES = ("north", "south")
EW_APPROACHES = ("east", "west")


@dataclass(slots=True)
class IntersectionRuntime:
    queues: dict[str, float]
    phase: str = "hold"
    phase_age: int = 0
    wait_memory: dict[str, float] | None = None
    emergency_pressure: float = 0.0

    def __post_init__(self) -> None:
        if self.wait_memory is None:
            self.wait_memory = {name: 0.0 for name in APPROACHES}


class MockTrafficEnvironment(SimulationBackend):
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.rng = np.random.default_rng(config.project.seed)
        self.control_interval = config.simulation.control_interval
        self.episode_seconds = config.simulation.episode_seconds
        self.max_queue = float(config.simulation.max_queue)
        self.time_seconds = 0
        self._teleport_arrivals: dict[str, dict[str, float]] = {}
        self._build_grid()
        self.metrics = {}

    def _build_grid(self) -> None:
        rows = self.config.simulation.grid_rows
        cols = self.config.simulation.grid_cols
        self.intersections: dict[str, IntersectionRuntime] = {}
        self.positions: dict[str, tuple[int, int]] = {}
        self.adjacency: dict[str, list[str]] = {}
        for row in range(rows):
            for col in range(cols):
                node_id = f"J{row}_{col}"
                self.positions[node_id] = (row, col)
                self.intersections[node_id] = IntersectionRuntime(
                    queues={name: 0.0 for name in APPROACHES},
                )
        for node_id, (row, col) in self.positions.items():
            neighbors: list[str] = []
            for d_row, d_col in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                candidate = (row + d_row, col + d_col)
                if 0 <= candidate[0] < rows and 0 <= candidate[1] < cols:
                    neighbors.append(f"J{candidate[0]}_{candidate[1]}")
            self.adjacency[node_id] = neighbors

    def clone(self) -> "MockTrafficEnvironment":
        clone = MockTrafficEnvironment(self.config)
        clone.rng = np.random.default_rng()
        clone.rng.bit_generator.state = deepcopy(self.rng.bit_generator.state)
        clone.time_seconds = self.time_seconds
        clone.intersections = deepcopy(self.intersections)
        clone.positions = deepcopy(self.positions)
        clone.adjacency = deepcopy(self.adjacency)
        clone._teleport_arrivals = deepcopy(self._teleport_arrivals)
        clone.metrics = deepcopy(self.metrics)
        return clone

    def reset(self) -> NetworkObservation:
        self.time_seconds = 0
        self._build_grid()
        self._teleport_arrivals = {}
        self.metrics = {
            "total_wait": 0.0,
            "total_queue": 0.0,
            "throughput": 0.0,
            "stops": 0.0,
            "emergency_delay": 0.0,
            "steps": 0,
        }
        for _ in range(self.config.simulation.warmup_seconds):
            self._one_second_tick({})
        return self._observe()

    def close(self) -> None:
        return None

    def step(self, actions: dict[str, str]) -> StepResult:
        for _ in range(self.control_interval):
            self._one_second_tick(actions)
        observation = self._observe()
        avg_wait = self.metrics["total_wait"] / max(1, self.metrics["steps"])
        avg_queue = self.metrics["total_queue"] / max(1, self.metrics["steps"])
        reward = (
            -1.0 * avg_wait
            - 0.35 * avg_queue
            - 0.2 * self.metrics["stops"] / max(1.0, self.metrics["throughput"] + 1.0)
            - 1.75 * self.metrics["emergency_delay"] / max(1, self.metrics["steps"])
            + 0.15 * self.metrics["throughput"] / max(1, self.metrics["steps"])
        )
        done = self.time_seconds >= self.episode_seconds
        info = {
            "avg_wait": avg_wait,
            "avg_queue": avg_queue,
            "throughput": self.metrics["throughput"],
        }
        return StepResult(observation=observation, reward=reward, done=done, info=info)

    def _one_second_tick(self, actions: dict[str, str]) -> None:
        pending_transfers: dict[str, dict[str, float]] = {
            node_id: {name: 0.0 for name in APPROACHES} for node_id in self.intersections
        }
        for node_id, runtime in self.intersections.items():
            action = actions.get(node_id, runtime.phase)
            runtime.phase_age = runtime.phase_age + 1 if action == runtime.phase else 1
            runtime.phase = action
            runtime.emergency_pressure = max(
                0.0,
                runtime.emergency_pressure * 0.85
                + self.rng.random() * self.config.scenario.emergency_vehicle_rate * 2.5,
            )

            external = self._sample_external_arrivals(node_id)
            for approach, value in external.items():
                runtime.queues[approach] = min(self.max_queue, runtime.queues[approach] + value)

            transferred = self._teleport_arrivals.get(node_id, {})
            for approach, value in transferred.items():
                runtime.queues[approach] = min(self.max_queue, runtime.queues[approach] + value)

            served_by_approach = self._serve(runtime)
            for approach, served in served_by_approach.items():
                if served <= 0:
                    continue
                self.metrics["throughput"] += served
                destination = self._downstream(node_id, approach)
                if destination and self.rng.random() < self.config.simulation.transfer_probability:
                    destination_id, destination_approach = destination
                    pending_transfers[destination_id][destination_approach] += served * 0.85

            total_queue = sum(runtime.queues.values())
            self.metrics["total_queue"] += total_queue
            self.metrics["total_wait"] += total_queue
            self.metrics["stops"] += sum(1.0 for q in runtime.queues.values() if q > 0.2)
            self.metrics["emergency_delay"] += runtime.emergency_pressure * total_queue * 0.02
            self.metrics["steps"] += 1

            for approach in APPROACHES:
                runtime.wait_memory[approach] = (
                    0.88 * runtime.wait_memory[approach] + 0.12 * runtime.queues[approach]
                )

        self._teleport_arrivals = pending_transfers
        self.time_seconds += 1

    def _sample_external_arrivals(self, node_id: str) -> dict[str, float]:
        row, col = self.positions[node_id]
        rows = self.config.simulation.grid_rows
        cols = self.config.simulation.grid_cols
        base = self.config.simulation.arrival_rate * self.config.scenario.demand_multiplier
        center_bonus = 1.0 + 0.15 * (
            1.0
            - abs((row + 0.5) / rows - 0.5)
            - abs((col + 0.5) / cols - 0.5)
        )
        arrivals = {}
        ns_bias = self.config.scenario.directional_bias_ns
        ew_bias = self.config.scenario.directional_bias_ew
        for approach in APPROACHES:
            bias = ns_bias if approach in NS_APPROACHES else ew_bias
            lam = max(0.02, base * center_bonus * bias)
            noisy = self.rng.poisson(lam) * (1.0 + self.rng.normal(0.0, self.config.scenario.noise))
            arrivals[approach] = max(0.0, float(noisy))
        return arrivals

    def _serve(self, runtime: IntersectionRuntime) -> dict[str, float]:
        service_rate = self.config.simulation.service_rate
        served = {name: 0.0 for name in APPROACHES}
        if runtime.phase == "ns_green":
            enabled = NS_APPROACHES
            capacity_scale = 1.0
        elif runtime.phase == "ew_green":
            enabled = EW_APPROACHES
            capacity_scale = 1.0
        elif runtime.phase == "hold":
            enabled = APPROACHES
            capacity_scale = 0.35
        else:
            enabled = ()
            capacity_scale = 0.0

        for approach in enabled:
            flow = min(runtime.queues[approach], service_rate * capacity_scale)
            runtime.queues[approach] = max(0.0, runtime.queues[approach] - flow)
            served[approach] = flow
        return served

    def _downstream(self, node_id: str, approach: str) -> tuple[str, str] | None:
        row, col = self.positions[node_id]
        if approach == "north" and row > 0:
            return f"J{row - 1}_{col}", "south"
        if approach == "south" and row < self.config.simulation.grid_rows - 1:
            return f"J{row + 1}_{col}", "north"
        if approach == "west" and col > 0:
            return f"J{row}_{col - 1}", "east"
        if approach == "east" and col < self.config.simulation.grid_cols - 1:
            return f"J{row}_{col + 1}", "west"
        return None

    def _observe(self) -> NetworkObservation:
        intersections: dict[str, IntersectionObservation] = {}
        for node_id, runtime in self.intersections.items():
            approaches = {}
            for approach in APPROACHES:
                queue = runtime.queues[approach]
                occupancy = min(1.0, queue / self.max_queue)
                avg_speed = max(0.0, 1.0 - occupancy)
                approaches[approach] = ApproachObservation(
                    queue_length=queue,
                    avg_speed=avg_speed,
                    occupancy=occupancy,
                    waiting_time=runtime.wait_memory[approach],
                )
            intersections[node_id] = IntersectionObservation(
                intersection_id=node_id,
                approaches=approaches,
                current_phase=runtime.phase,
                phase_age=runtime.phase_age,
                emergency_pressure=runtime.emergency_pressure,
            )
        return NetworkObservation(
            time_seconds=self.time_seconds,
            intersections=intersections,
            adjacency=deepcopy(self.adjacency),
            metadata={"backend": "mock"},
        )

    def apply_action_sequence(self, action_provider: Iterable[dict[str, str]], steps: int) -> StepResult:
        latest_result: StepResult | None = None
        iterator = iter(action_provider)
        for _ in range(steps):
            latest_result = self.step(next(iterator, {}))
            if latest_result.done:
                break
        assert latest_result is not None
        return latest_result
