from __future__ import annotations

from abc import ABC, abstractmethod

from traffic_quantum.config import ProjectConfig
from traffic_quantum.models import NetworkObservation


class Controller(ABC):
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.__class__.__name__.replace("Controller", "").lower()

    def reset(self, observation: NetworkObservation) -> None:
        return None

    @abstractmethod
    def act(self, observation: NetworkObservation) -> dict[str, str]:
        raise NotImplementedError
