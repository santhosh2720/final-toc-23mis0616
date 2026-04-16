from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pandas as pd

from traffic_quantum.config import ProjectConfig
from traffic_quantum.sim.mock_env import MockTrafficEnvironment


@dataclass(slots=True)
class CounterfactualScenario:
    name: str
    demand_multiplier: float
    emergency_vehicle_rate: float


class DigitalTwinAnalyzer:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config

    def evaluate(self, base_env: MockTrafficEnvironment, controller, samples: int = 4) -> pd.DataFrame:
        scenarios = [
            CounterfactualScenario("baseline", 1.0, self.config.scenario.emergency_vehicle_rate),
            CounterfactualScenario("incident", 1.15, self.config.scenario.emergency_vehicle_rate * 1.8),
            CounterfactualScenario("evacuation", 1.35, self.config.scenario.emergency_vehicle_rate * 2.6),
        ]
        rows: list[dict] = []
        for scenario in scenarios:
            for sample in range(samples):
                run_config = deepcopy(self.config)
                run_config.scenario.demand_multiplier *= scenario.demand_multiplier
                run_config.scenario.emergency_vehicle_rate = scenario.emergency_vehicle_rate
                env = MockTrafficEnvironment(run_config)
                observation = env.reset()
                controller.reset(observation)
                reward_total = 0.0
                done = False
                while not done and env.time_seconds < min(run_config.simulation.episode_seconds, 600):
                    actions = controller.act(observation)
                    result = env.step(actions)
                    reward_total += result.reward
                    observation = result.observation
                    done = result.done
                rows.append(
                    {
                        "scenario": scenario.name,
                        "sample": sample,
                        "avg_waiting_time": env.metrics["total_wait"] / max(1, env.metrics["steps"]),
                        "avg_queue_length": env.metrics["total_queue"] / max(1, env.metrics["steps"]),
                        "throughput": env.metrics["throughput"],
                        "reward_total": reward_total,
                    }
                )
        return pd.DataFrame(rows)
