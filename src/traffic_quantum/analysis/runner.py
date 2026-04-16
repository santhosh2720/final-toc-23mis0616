from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd

from traffic_quantum.analysis.metrics import metrics_to_frame, summarize
from traffic_quantum.config import ProjectConfig
from traffic_quantum.controllers import (
    ActuatedController,
    FixedTimeController,
    GeneticSearchController,
    HybridQuantumController,
)
from traffic_quantum.models import EpisodeMetrics, NetworkObservation
from traffic_quantum.quantum.digital_twin import DigitalTwinAnalyzer
from traffic_quantum.sim import MockTrafficEnvironment, SumoEnvironment


def build_environment(config: ProjectConfig):
    if config.simulation.backend == "sumo":
        return SumoEnvironment(config)
    return MockTrafficEnvironment(config)


def build_controller(config: ProjectConfig):
    name = config.controller.name.lower()
    if name == "fixed":
        return FixedTimeController(config)
    if name == "actuated":
        return ActuatedController(config)
    if name == "genetic":
        return GeneticSearchController(config)
    return HybridQuantumController(config)


def run_episode(config: ProjectConfig) -> EpisodeMetrics:
    env = build_environment(config)
    controller = build_controller(config)
    observation = env.reset()
    controller.reset(observation)
    rewards: list[float] = []
    done = False
    while not done:
        current_observation = observation
        actions = controller.act(current_observation)
        result = env.step(actions)
        rewards.append(result.reward)
        if isinstance(controller, HybridQuantumController):
            controller.record_reward(current_observation, actions, result.reward)
        observation = result.observation
        done = result.done
    avg_waiting_time = env.metrics["total_wait"] / max(1, env.metrics["steps"])
    avg_queue_length = env.metrics["total_queue"] / max(1, env.metrics["steps"])
    throughput = env.metrics["throughput"]
    episode_reward = -avg_waiting_time - 0.25 * avg_queue_length + 0.05 * throughput
    metrics = EpisodeMetrics(
        controller_name=config.controller.name,
        scenario_name=config.scenario.name,
        avg_waiting_time=avg_waiting_time,
        avg_queue_length=avg_queue_length,
        throughput=throughput,
        avg_reward=episode_reward,
        stops_per_vehicle=env.metrics.get("stops", 0.0) / max(1.0, throughput + 1.0),
        emergency_delay=env.metrics.get("emergency_delay", 0.0) / max(1, env.metrics["steps"]),
        total_steps=env.metrics["steps"],
    )
    env.close()
    return metrics


def smoke_test(config: ProjectConfig) -> EpisodeMetrics:
    short = deepcopy(config)
    short.simulation.episode_seconds = min(short.simulation.episode_seconds, 360)
    return run_episode(short)


def benchmark_controllers(
    config: ProjectConfig,
    replications: int = 4,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    controllers = ["fixed", "actuated", "genetic", "hybrid"]
    metrics: list[EpisodeMetrics] = []
    for controller_name in controllers:
        for replication in range(replications):
            run_config = deepcopy(config)
            run_config.controller.name = controller_name
            run_config.project.seed += replication
            metrics.append(run_episode(run_config))
    frame = metrics_to_frame(metrics)
    summary = summarize(frame)
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output_dir / "benchmark_runs.csv", index=False)
        summary.to_csv(output_dir / "benchmark_summary.csv", index=False)
    return summary


def train_policy(config: ProjectConfig, episodes: int = 10) -> dict[str, float]:
    train_config = deepcopy(config)
    train_config.simulation.backend = "mock"
    train_config.controller.name = "hybrid"
    controller = build_controller(train_config)
    if not isinstance(controller, HybridQuantumController):
        raise RuntimeError("Policy training requires the hybrid controller.")
    losses = []
    rewards = []
    for episode in range(episodes):
        episode_config = deepcopy(train_config)
        episode_config.project.seed += episode
        env = MockTrafficEnvironment(episode_config)
        observation = env.reset()
        controller.reset(observation)
        done = False
        reward_total = 0.0
        while not done:
            current_observation = observation
            actions = controller.act(current_observation)
            result = env.step(actions)
            reward_total += result.reward
            controller.record_reward(current_observation, actions, result.reward)
            observation = result.observation
            done = result.done
        losses.append(controller.update_policy())
        rewards.append(reward_total)
        env.close()
    env = MockTrafficEnvironment(train_config)
    twin = DigitalTwinAnalyzer(train_config).evaluate(env, controller, samples=2)
    return {
        "episodes": episodes,
        "avg_policy_loss": float(sum(losses) / max(1, len(losses))),
        "avg_episode_reward": float(sum(rewards) / max(1, len(rewards))),
        "digital_twin_wait_mean": float(twin["avg_waiting_time"].mean()),
    }
