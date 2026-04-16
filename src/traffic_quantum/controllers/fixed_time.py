from __future__ import annotations

from traffic_quantum.controllers.base import Controller
from traffic_quantum.models import NetworkObservation


class FixedTimeController(Controller):
    def act(self, observation: NetworkObservation) -> dict[str, str]:
        phase_duration = max(30, self.config.simulation.control_interval * 4, self.config.controller.min_green_seconds * 4)
        phase = "ns_green" if (observation.time_seconds // phase_duration) % 2 == 0 else "ew_green"
        return {node_id: phase for node_id in observation.intersections}
