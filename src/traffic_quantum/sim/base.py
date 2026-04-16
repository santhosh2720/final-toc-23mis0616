from __future__ import annotations

from abc import ABC, abstractmethod

from traffic_quantum.models import NetworkObservation, StepResult


class SimulationBackend(ABC):
    @abstractmethod
    def reset(self) -> NetworkObservation:
        raise NotImplementedError

    @abstractmethod
    def step(self, actions: dict[str, str]) -> StepResult:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
