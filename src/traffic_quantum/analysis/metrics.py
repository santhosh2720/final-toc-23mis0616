from __future__ import annotations

import math
import pandas as pd

from traffic_quantum.models import EpisodeMetrics


def reward_score(raw_reward: float) -> float:
    penalty = max(0.0, -float(raw_reward))
    return 100.0 / (1.0 + (penalty / 1000.0))


def metrics_to_frame(metrics: list[EpisodeMetrics]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "controller": item.controller_name,
                "scenario": item.scenario_name,
                "avg_waiting_time": item.avg_waiting_time,
                "avg_queue_length": item.avg_queue_length,
                "throughput": item.throughput,
                "avg_reward": item.avg_reward,
                "reward_score": reward_score(item.avg_reward),
                "stops_per_vehicle": item.stops_per_vehicle,
                "emergency_delay": item.emergency_delay,
                "total_steps": item.total_steps,
            }
            for item in metrics
        ]
    )


def summarize(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.groupby(["controller", "scenario"], as_index=False).agg(
        avg_waiting_time_mean=("avg_waiting_time", "mean"),
        avg_waiting_time_std=("avg_waiting_time", "std"),
        avg_queue_length_mean=("avg_queue_length", "mean"),
        throughput_mean=("throughput", "mean"),
        avg_reward_mean=("avg_reward", "mean"),
        reward_score_mean=("reward_score", "mean"),
        stops_per_vehicle_mean=("stops_per_vehicle", "mean"),
        emergency_delay_mean=("emergency_delay", "mean"),
        runs=("avg_waiting_time", "count"),
    )
    grouped["wait_ci95"] = grouped.apply(
        lambda row: 1.96 * (0.0 if pd.isna(row["avg_waiting_time_std"]) else row["avg_waiting_time_std"]) / max(1.0, math.sqrt(row["runs"])),
        axis=1,
    )
    return grouped
