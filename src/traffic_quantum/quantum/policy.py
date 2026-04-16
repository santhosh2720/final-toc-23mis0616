from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from traffic_quantum.models import NetworkObservation


@dataclass(slots=True)
class PolicySample:
    features: np.ndarray
    action_index: int
    reward: float


class QuantumPolicyNetwork:
    def __init__(self, actions: tuple[str, ...], seed: int) -> None:
        self.actions = actions
        self.rng = np.random.default_rng(seed)
        self.weights = self.rng.normal(0.0, 0.12, size=(len(actions), 40))
        self.bias = np.zeros(len(actions), dtype=float)

    def scores(self, features: np.ndarray) -> np.ndarray:
        encoded = self._encode(features)
        logits = self.weights @ encoded + self.bias
        logits = logits - logits.max(initial=0.0)
        exp_logits = np.exp(logits)
        return exp_logits / max(1e-9, exp_logits.sum())

    def choose(self, features: np.ndarray, greedy: bool = True) -> tuple[str, int, np.ndarray]:
        probs = self.scores(features)
        index = int(np.argmax(probs)) if greedy else int(self.rng.choice(len(self.actions), p=probs))
        return self.actions[index], index, probs

    def update(self, batch: list[PolicySample], learning_rate: float = 0.02) -> float:
        if not batch:
            return 0.0
        total_loss = 0.0
        for sample in batch:
            encoded = self._encode(sample.features)
            probs = self.scores(sample.features)
            advantage = sample.reward
            grad = -probs
            grad[sample.action_index] += 1.0
            self.weights += learning_rate * advantage * np.outer(grad, encoded)
            self.bias += learning_rate * advantage * grad
            total_loss += -np.log(max(1e-9, probs[sample.action_index])) * advantage
        return total_loss / len(batch)

    def extract_features(self, observation: NetworkObservation, node_id: str, congestion_score: float) -> np.ndarray:
        item = observation.intersections[node_id]
        base = item.feature_vector()
        aux = np.array([item.phase_age / 60.0, item.emergency_pressure, congestion_score, item.total_queue], dtype=float)
        return np.concatenate([base, aux])

    def _encode(self, features: np.ndarray) -> np.ndarray:
        scaled = np.clip(features / np.maximum(1.0, np.abs(features).max(initial=1.0)), -1.0, 1.0)
        return np.concatenate([np.sin(np.pi * scaled), np.cos(np.pi * scaled)])
