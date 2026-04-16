from __future__ import annotations

from traffic_quantum.controllers.base import Controller
from traffic_quantum.models import NetworkObservation


class ActuatedController(Controller):
    def act(self, observation: NetworkObservation) -> dict[str, str]:
        actions: dict[str, str] = {}
        for node_id, item in observation.intersections.items():
            ns_pressure = item.approaches["north"].queue_length + item.approaches["south"].queue_length
            ew_pressure = item.approaches["east"].queue_length + item.approaches["west"].queue_length
            if item.phase_age < self.config.controller.min_green_seconds and item.current_phase != "hold":
                actions[node_id] = item.current_phase
                continue
            if item.emergency_pressure > 0.8:
                actions[node_id] = "ns_green" if ns_pressure >= ew_pressure else "ew_green"
            elif max(ns_pressure, ew_pressure) < 0.8:
                actions[node_id] = "hold"
            else:
                actions[node_id] = "ns_green" if ns_pressure >= ew_pressure else "ew_green"
        return actions
