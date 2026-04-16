from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

APPROACHES = ("north", "south", "east", "west")
PHASES = ("hold", "ns_green", "ew_green", "pedestrian_all_red")


@dataclass(slots=True)
class ApproachObservation:
    queue_length: float
    avg_speed: float
    occupancy: float
    waiting_time: float

    def as_array(self) -> np.ndarray:
        return np.array(
            [self.queue_length, self.avg_speed, self.occupancy, self.waiting_time],
            dtype=float,
        )


@dataclass(slots=True)
class IntersectionObservation:
    intersection_id: str
    approaches: dict[str, ApproachObservation]
    current_phase: str
    phase_age: int
    emergency_pressure: float = 0.0

    def feature_vector(self) -> np.ndarray:
        return np.concatenate([self.approaches[name].as_array() for name in APPROACHES])

    @property
    def total_queue(self) -> float:
        return float(sum(item.queue_length for item in self.approaches.values()))

    @property
    def total_wait(self) -> float:
        return float(sum(item.waiting_time for item in self.approaches.values()))


@dataclass(slots=True)
class NetworkObservation:
    time_seconds: int
    intersections: dict[str, IntersectionObservation]
    adjacency: dict[str, list[str]]
    metadata: dict[str, Any] = field(default_factory=dict)

    def feature_matrix(self) -> np.ndarray:
        ordered = sorted(self.intersections)
        return np.vstack([self.intersections[node].feature_vector() for node in ordered])

    def ordered_ids(self) -> list[str]:
        return sorted(self.intersections)


@dataclass(slots=True)
class StepResult:
    observation: NetworkObservation
    reward: float
    done: bool
    info: dict[str, Any]


@dataclass(slots=True)
class ForecastItem:
    congestion_score: float
    state_probabilities: dict[str, float]


@dataclass(slots=True)
class CongestionForecast:
    horizon_steps: int
    by_intersection: dict[str, ForecastItem]
    latent_state: np.ndarray


@dataclass(slots=True)
class QuboProblem:
    matrix: np.ndarray
    variable_map: list[tuple[str, str]]
    local_costs: dict[tuple[str, str], float]


@dataclass(slots=True)
class OptimizationResult:
    assignment: dict[str, str]
    energy: float
    backend: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EpisodeMetrics:
    controller_name: str
    scenario_name: str
    avg_waiting_time: float
    avg_queue_length: float
    throughput: float
    avg_reward: float
    stops_per_vehicle: float
    emergency_delay: float
    total_steps: int
    metadata: dict[str, Any] = field(default_factory=dict)
