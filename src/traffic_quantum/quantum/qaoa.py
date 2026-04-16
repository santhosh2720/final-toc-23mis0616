from __future__ import annotations

import math
import numpy as np

from traffic_quantum.models import OptimizationResult, QuboProblem

try:
    from qiskit.quantum_info import SparsePauliOp  # pragma: no cover
except ImportError:  # pragma: no cover
    SparsePauliOp = None


class QAOASolver:
    def __init__(self, seed: int, layers: int = 3, trials: int = 200) -> None:
        self.seed = seed
        self.layers = layers
        self.trials = trials
        self.rng = np.random.default_rng(seed)

    def solve(self, qubo: QuboProblem) -> OptimizationResult:
        best_x, best_energy = self._quantum_inspired_search(qubo)
        assignment = self._decode(best_x, qubo)
        return OptimizationResult(
            assignment=assignment,
            energy=float(best_energy),
            backend="quantum-inspired-qaoa" if SparsePauliOp is None else "hybrid-qaoa",
            metadata={"layers": self.layers, "trials": self.trials},
        )

    def _quantum_inspired_search(self, qubo: QuboProblem) -> tuple[np.ndarray, float]:
        grouped: dict[str, list[int]] = {}
        for index, (node_id, _) in enumerate(qubo.variable_map):
            grouped.setdefault(node_id, []).append(index)

        current = np.zeros(len(qubo.variable_map), dtype=int)
        for indices in grouped.values():
            best_idx = min(indices, key=lambda idx: qubo.matrix[idx, idx])
            current[best_idx] = 1
        best = current.copy()
        best_energy = self._energy(best, qubo.matrix)

        temperature = 2.0
        for _ in range(self.trials):
            proposal = current.copy()
            node_id = list(grouped)[self.rng.integers(0, len(grouped))]
            indices = grouped[node_id]
            chosen = indices[np.argmax(current[indices])]
            proposal[chosen] = 0
            replacement = indices[self.rng.integers(0, len(indices))]
            proposal[replacement] = 1
            proposal = self._repair(proposal, grouped)
            energy = self._energy(proposal, qubo.matrix)
            delta = energy - self._energy(current, qubo.matrix)
            if delta < 0 or self.rng.random() < math.exp(-delta / max(temperature, 1e-6)):
                current = proposal
            current_energy = self._energy(current, qubo.matrix)
            if current_energy < best_energy:
                best = current.copy()
                best_energy = current_energy
            temperature *= 0.992
        return best, best_energy

    def _repair(self, vector: np.ndarray, grouped: dict[str, list[int]]) -> np.ndarray:
        fixed = vector.copy()
        for indices in grouped.values():
            if fixed[indices].sum() != 1:
                fixed[indices] = 0
                fixed[self.rng.choice(indices)] = 1
        return fixed

    def _energy(self, vector: np.ndarray, matrix: np.ndarray) -> float:
        return float(vector @ matrix @ vector)

    def _decode(self, vector: np.ndarray, qubo: QuboProblem) -> dict[str, str]:
        assignment = {}
        for value, (node_id, action) in zip(vector, qubo.variable_map, strict=True):
            if value == 1:
                assignment[node_id] = action
        return assignment
