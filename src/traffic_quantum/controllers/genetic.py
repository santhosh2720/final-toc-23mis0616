from __future__ import annotations

import math
import numpy as np

from traffic_quantum.controllers.base import Controller
from traffic_quantum.models import NetworkObservation


class GeneticSearchController(Controller):
    def __init__(self, config) -> None:
        super().__init__(config)
        self.rng = np.random.default_rng(config.project.seed + 17)
        self.actions = tuple(config.phase_actions)

    def act(self, observation: NetworkObservation) -> dict[str, str]:
        node_ids = observation.ordered_ids()
        population_size = self.config.controller.genetic_population
        generations = self.config.controller.genetic_generations
        population = [
            [self.rng.choice(self.actions) for _ in node_ids] for _ in range(population_size)
        ]
        scored = [(self._fitness(observation, node_ids, genome), genome) for genome in population]
        for _ in range(generations):
            scored.sort(key=lambda item: item[0], reverse=True)
            parents = [genome for _, genome in scored[: max(2, population_size // 3)]]
            next_population = parents[:2]
            while len(next_population) < population_size:
                a = parents[self.rng.integers(0, len(parents))]
                b = parents[self.rng.integers(0, len(parents))]
                if len(node_ids) > 1:
                    cut = self.rng.integers(1, len(node_ids))
                    child = a[:cut] + b[cut:]
                else:
                    child = a[:]
                for index in range(len(child)):
                    if self.rng.random() < 0.12:
                        child[index] = self.rng.choice(self.actions)
                next_population.append(child)
            scored = [(self._fitness(observation, node_ids, genome), genome) for genome in next_population]
        best = max(scored, key=lambda item: item[0])[1]
        return dict(zip(node_ids, best, strict=True))

    def _fitness(self, observation: NetworkObservation, node_ids: list[str], genome: list[str]) -> float:
        score = 0.0
        for node_id, action in zip(node_ids, genome, strict=True):
            item = observation.intersections[node_id]
            ns_pressure = item.approaches["north"].queue_length + item.approaches["south"].queue_length
            ew_pressure = item.approaches["east"].queue_length + item.approaches["west"].queue_length
            if action == "ns_green":
                score += 1.6 * ns_pressure - 0.8 * ew_pressure
            elif action == "ew_green":
                score += 1.6 * ew_pressure - 0.8 * ns_pressure
            elif action == "hold":
                score += -0.4 * (ns_pressure + ew_pressure)
            else:
                score += -1.1 * (ns_pressure + ew_pressure)
            score += 0.7 * item.emergency_pressure * (1 if action != "pedestrian_all_red" else -1)
            for neighbor in observation.adjacency.get(node_id, []):
                if neighbor <= node_id:
                    continue
                neighbor_action = genome[node_ids.index(neighbor)]
                score += 0.25 if neighbor_action == action and action in {"ns_green", "ew_green"} else 0.0
        return score - 0.02 * math.fsum(item.total_wait for item in observation.intersections.values())
