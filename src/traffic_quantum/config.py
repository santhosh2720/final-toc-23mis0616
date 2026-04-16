from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass(slots=True)
class ProjectSection:
    name: str = "traffic-quantum"
    seed: int = 7


@dataclass(slots=True)
class SimulationSection:
    backend: str = "mock"
    episode_seconds: int = 1800
    control_interval: int = 15
    warmup_seconds: int = 60
    grid_rows: int = 3
    grid_cols: int = 3
    arrival_rate: float = 0.4
    service_rate: float = 0.75
    transfer_probability: float = 0.7
    max_queue: int = 30


@dataclass(slots=True)
class ScenarioSection:
    name: str = "rush_hour"
    demand_multiplier: float = 1.0
    directional_bias_ns: float = 0.55
    directional_bias_ew: float = 0.45
    noise: float = 0.05
    emergency_vehicle_rate: float = 0.02


@dataclass(slots=True)
class ControllerSection:
    name: str = "hybrid"
    phase_actions: list[str] = field(
        default_factory=lambda: ["hold", "ns_green", "ew_green", "pedestrian_all_red"]
    )
    genetic_population: int = 24
    genetic_generations: int = 18
    qaoa_layers: int = 3
    qaoa_trials: int = 200
    prediction_horizon_steps: int = 8
    coordination_bonus: float = -12.0
    one_hot_penalty: float = 40.0
    min_green_seconds: int = 15
    max_green_seconds: int = 90


@dataclass(slots=True)
class SumoSection:
    sumo_binary: str = ""
    sumocfg_path: str = ""
    use_gui: bool = False


@dataclass(slots=True)
class OutputSection:
    directory: str = "reports"


@dataclass(slots=True)
class ProjectConfig:
    project: ProjectSection = field(default_factory=ProjectSection)
    simulation: SimulationSection = field(default_factory=SimulationSection)
    scenario: ScenarioSection = field(default_factory=ScenarioSection)
    controller: ControllerSection = field(default_factory=ControllerSection)
    sumo: SumoSection = field(default_factory=SumoSection)
    output: OutputSection = field(default_factory=OutputSection)

    @property
    def phase_actions(self) -> tuple[str, ...]:
        return tuple(self.controller.phase_actions)

    @property
    def intersection_count(self) -> int:
        return self.simulation.grid_rows * self.simulation.grid_cols

    def output_dir(self, root: Path) -> Path:
        return root / self.output.directory


def _section(data: dict, key: str, factory):
    values = data.get(key, {})
    return factory(**values)


def load_config(path: str | Path | None = None) -> ProjectConfig:
    if path is None:
        return ProjectConfig()
    config_path = Path(path)
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    return ProjectConfig(
        project=_section(data, "project", ProjectSection),
        simulation=_section(data, "simulation", SimulationSection),
        scenario=_section(data, "scenario", ScenarioSection),
        controller=_section(data, "controller", ControllerSection),
        sumo=_section(data, "sumo", SumoSection),
        output=_section(data, "output", OutputSection),
    )
