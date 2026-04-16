from __future__ import annotations

import numpy as np

from traffic_quantum.models import CongestionForecast, ForecastItem, NetworkObservation


class QuantumGraphPredictor:
    def __init__(self, seed: int, layers: int = 4) -> None:
        self.layers = layers
        self.rng = np.random.default_rng(seed)

    def predict(self, observation: NetworkObservation, horizon_steps: int) -> CongestionForecast:
        ordered_ids = observation.ordered_ids()
        if not ordered_ids:
            return CongestionForecast(horizon_steps=horizon_steps, by_intersection={}, latent_state=np.zeros((0, 4)))
        features = np.vstack([self._node_features(observation.intersections[node_id]) for node_id in ordered_ids])
        adjacency = self._adjacency_matrix(observation, ordered_ids)
        hidden = features.copy()
        for layer in range(self.layers):
            neighborhood = adjacency @ hidden
            hidden = 0.62 * hidden + 0.38 * neighborhood
            hidden[:, 0] = np.tanh(1.10 * hidden[:, 0] + 0.22 * hidden[:, 1])
            hidden[:, 1] = np.tanh(0.92 * hidden[:, 1] + 0.20 * hidden[:, 2])
            hidden[:, 2] = np.tanh(0.88 * hidden[:, 2] + 0.18 * hidden[:, 3])
            hidden[:, 3] = np.tanh(0.95 * hidden[:, 3] + 0.14 * hidden[:, 0])
        scores = np.clip(
            0.42 * hidden[:, 0] + 0.28 * hidden[:, 1] + 0.18 * hidden[:, 2] + 0.12 * hidden[:, 3],
            0.0,
            1.0,
        )
        forecast = {}
        for index, node_id in enumerate(ordered_ids):
            score = float(np.clip(scores[index], 0.0, 1.0))
            forecast[node_id] = ForecastItem(
                congestion_score=score,
                state_probabilities=self._probabilities(score),
            )
        return CongestionForecast(horizon_steps=horizon_steps, by_intersection=forecast, latent_state=hidden)

    def _adjacency_matrix(self, observation: NetworkObservation, ordered_ids: list[str]) -> np.ndarray:
        n = len(ordered_ids)
        index = {node_id: idx for idx, node_id in enumerate(ordered_ids)}
        matrix = np.eye(n, dtype=float)
        for node_id, neighbors in observation.adjacency.items():
            for neighbor in neighbors:
                if neighbor in index:
                    matrix[index[node_id], index[neighbor]] = 1.0
        row_sums = matrix.sum(axis=1, keepdims=True)
        return matrix / np.maximum(1.0, row_sums)

    def _node_features(self, item) -> np.ndarray:
        queue = np.clip(item.total_queue / 40.0, 0.0, 1.0)
        wait = np.clip(item.total_wait / 900.0, 0.0, 1.0)
        occupancy = np.clip(
            np.mean([approach.occupancy for approach in item.approaches.values()], dtype=float),
            0.0,
            1.0,
        )
        speed_values = [approach.avg_speed for approach in item.approaches.values()]
        max_speed = max(1.0, max(speed_values, default=1.0))
        slowdown = np.clip(1.0 - (np.mean(speed_values, dtype=float) / max_speed), 0.0, 1.0)
        return np.array([queue, wait, occupancy, slowdown], dtype=float)

    def _probabilities(self, score: float) -> dict[str, float]:
        probs = np.array(
            [
                max(0.0, 1.0 - score * 1.6),
                max(0.0, 0.75 - abs(score - 0.3)),
                max(0.0, 0.75 - abs(score - 0.65)),
                max(0.0, score - 0.45),
            ],
            dtype=float,
        )
        probs = probs / max(1e-9, probs.sum())
        return {
            "free_flow": float(probs[0]),
            "light_congestion": float(probs[1]),
            "heavy_congestion": float(probs[2]),
            "gridlock": float(probs[3]),
        }
