from __future__ import annotations

from traffic_quantum.analysis.runner import benchmark_controllers, smoke_test, train_policy
from traffic_quantum.config import load_config


def test_smoke_hybrid_runs() -> None:
    config = load_config("configs/mock_city.toml")
    config.controller.name = "hybrid"
    metrics = smoke_test(config)
    assert metrics.total_steps > 0
    assert metrics.avg_waiting_time >= 0.0


def test_benchmark_produces_all_controllers() -> None:
    config = load_config("configs/mock_city.toml")
    config.simulation.episode_seconds = 120
    summary = benchmark_controllers(config, replications=1)
    assert set(summary["controller"]) == {"fixed", "actuated", "genetic", "hybrid"}


def test_policy_training_executes() -> None:
    config = load_config("configs/mock_city.toml")
    config.simulation.episode_seconds = 120
    result = train_policy(config, episodes=2)
    assert result["episodes"] == 2
