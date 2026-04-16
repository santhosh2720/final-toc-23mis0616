from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import subprocess

from traffic_quantum.analysis.metrics import metrics_to_frame, summarize
from traffic_quantum.analysis.runner import build_controller
from traffic_quantum.config import load_config
from traffic_quantum.controllers.hybrid import HybridQuantumController
from traffic_quantum.models import EpisodeMetrics, NetworkObservation
from traffic_quantum.sim.sumo_assets import (
    build_netconvert,
    generate_area_based_assets,
    generate_grid_assets,
    generate_image_interchange_assets,
    generate_scanned_major_road_assets,
)
from traffic_quantum.web.gemini_scan import extract_gemini_road_layout
from traffic_quantum.sim.sumo_env import SumoEnvironment
from traffic_quantum.web.image_scan import extract_warm_road_layout

try:
    import sumolib
except ImportError:  # pragma: no cover
    sumolib = None


@dataclass(slots=True)
class SumoInstall:
    sumo: Path
    sumo_gui: Path
    netconvert: Path
    random_trips: Path


class TrafficWebService:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[3]
        self.runs_dir = self.root / "web_runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.sumo = self._resolve_sumo_install()

    def create_area_scenario(
        self,
        polygon: list[dict[str, float]],
        scenario_name: str | None = None,
        image_data: str | None = None,
    ) -> dict:
        if len(polygon) < 3:
            raise ValueError("Please draw an area with at least three points.")
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        bbox = self._bbox_from_polygon(polygon)
        fallback_reason = None
        source = "major-road-layout"
        if image_data:
            gemini_error = None
            try:
                gemini_layout = extract_gemini_road_layout(image_data)
                if gemini_layout and gemini_layout.nodes and gemini_layout.edges:
                    sumocfg_path, net_path, route_path, layout = self._build_scanned_area_network(run_dir, gemini_layout)
                    source = "gemini-image-graph"
                    user_message = (
                        f"Created a Gemini-assisted SUMO network with {len(gemini_layout.nodes)} nodes and "
                        f"{len(gemini_layout.edges)} major-road connections."
                    )
                else:
                    raise ValueError("Gemini graph extraction is unavailable or no Gemini key is set.")
            except Exception as exc:
                gemini_error = str(exc)
            if source != "gemini-image-graph":
                try:
                    warm_layout = extract_warm_road_layout(image_data)
                    if warm_layout and (
                        (warm_layout.nodes and warm_layout.edges)
                        or (warm_layout.rows >= 1 and warm_layout.cols >= 1)
                    ):
                        sumocfg_path, net_path, route_path, layout = self._build_scanned_area_network(run_dir, warm_layout)
                        source = "map-color-scan"
                        user_message = (
                            f"Created a warm-road scanned SUMO network with {layout['rows']} major corridors and "
                            f"{layout['cols']} crossing roads."
                        )
                    else:
                        raise ValueError("Warm road scan could not detect enough major roads.")
                except Exception as exc:
                    fallback_reason = str(exc)
                    sumocfg_path, net_path, route_path, layout = self._build_area_network(run_dir, bbox)
                    if gemini_error and fallback_reason:
                        combined_reason = f"Gemini: {gemini_error}. Local scan: {fallback_reason}"
                    else:
                        combined_reason = gemini_error or fallback_reason
                    user_message = (
                        "Image-assisted extraction fallback was used because the selected map could not be converted cleanly. "
                        f"Built a simplified major-road layout instead. Reason: {combined_reason}"
                    )
                    fallback_reason = combined_reason
        else:
            sumocfg_path, net_path, route_path, layout = self._build_area_network(run_dir, bbox)
            user_message = f"Created a simplified major-road area network with {layout['rows']} rows and {layout['cols']} columns of junctions."
        preview = self._network_preview(net_path)
        payload = {
            "run_id": run_id,
            "scenario_name": scenario_name or f"area_{run_id}",
            "sumocfg_path": str(sumocfg_path),
            "net_path": str(net_path),
            "route_path": str(route_path),
            "source": source,
            "fallback_reason": fallback_reason,
            "user_message": user_message,
            "bbox": bbox,
            "polygon": polygon,
            "preview": preview,
            "layout": layout,
        }
        self._write_json(run_dir / "scenario.json", payload)
        return payload

    def run_area_benchmark(
        self,
        run_id: str,
        selected_controller: str = "hybrid",
        episode_seconds: int = 300,
        open_gui: bool = False,
        mode: str = "quick",
    ) -> dict:
        run_dir = self.runs_dir / run_id
        scenario = self._read_json(run_dir / "scenario.json")
        metrics: list[EpisodeMetrics] = []
        trace_payload = None
        controllers = self._controllers_for_mode(selected_controller, mode)
        for controller_name in controllers:
            capture_trace = controller_name == selected_controller
            result = self._run_controller(
                run_id=run_id,
                controller_name=controller_name,
                sumocfg_path=Path(scenario["sumocfg_path"]),
                episode_seconds=episode_seconds,
                capture_trace=capture_trace,
                use_gui=open_gui and capture_trace,
            )
            metrics.append(result["metrics"])
            if capture_trace:
                trace_payload = result["trace"]
                self._write_json(run_dir / "trace.json", trace_payload)
        frame = metrics_to_frame(metrics)
        summary = summarize(frame)
        frame.to_csv(run_dir / "benchmark_runs.csv", index=False)
        summary.to_csv(run_dir / "benchmark_summary.csv", index=False)
        response = {
            "run_id": run_id,
            "selected_controller": selected_controller,
            "mode": mode,
            "metrics": self._sanitize_json(frame.to_dict(orient="records")),
            "summary": self._sanitize_json(summary.to_dict(orient="records")),
            "trace": self._sanitize_json(trace_payload),
            "artifacts": {
                "benchmark_runs_csv": f"/api/runs/{run_id}/artifacts/benchmark_runs.csv",
                "benchmark_summary_csv": f"/api/runs/{run_id}/artifacts/benchmark_summary.csv",
                "trace_json": f"/api/runs/{run_id}/artifacts/trace.json",
            },
        }
        self._write_json(run_dir / "results.json", response)
        return response

    def _controllers_for_mode(self, selected_controller: str, mode: str) -> list[str]:
        all_controllers = ["fixed", "actuated", "genetic", "hybrid"]
        if mode == "full":
            return all_controllers
        if selected_controller in all_controllers:
            return [selected_controller]
        return ["hybrid"]

    def get_run(self, run_id: str) -> dict:
        run_dir = self.runs_dir / run_id
        scenario = self._read_json(run_dir / "scenario.json")
        results = self._read_json(run_dir / "results.json") if (run_dir / "results.json").exists() else None
        return {"scenario": scenario, "results": results}

    def get_latest_image_demo(self) -> dict | None:
        latest_path = self.root / "reports" / "image_dashboard" / "latest.json"
        if not latest_path.exists():
            return None
        return self._read_json(latest_path)

    def run_image_demo_dashboard(
        self,
        episode_seconds: int = 360,
        replications: int = 2,
    ) -> dict:
        reports_dir = self.root / "reports" / "image_dashboard"
        reports_dir.mkdir(parents=True, exist_ok=True)

        image_assets = self._ensure_image_demo_assets()
        preview = self._network_preview(image_assets["net"])

        benchmark_metrics: list[EpisodeMetrics] = []
        trace_lookup: dict[str, dict] = {}
        for controller_name in ("fixed", "actuated", "genetic", "hybrid"):
            for replication in range(replications):
                config = self._image_demo_config(controller_name, episode_seconds=episode_seconds)
                config.project.seed += replication * 17
                capture_trace = replication == 0 and controller_name in {"fixed", "hybrid"}
                result = self._run_config_controller(
                    config=config,
                    controller_name=controller_name,
                    capture_trace=capture_trace,
                    run_id=f"image_demo_{controller_name}_{replication}",
                )
                benchmark_metrics.append(result["metrics"])
                if capture_trace and result["trace"]:
                    trace_lookup[controller_name] = result["trace"]

        benchmark_frame = metrics_to_frame(benchmark_metrics)
        benchmark_summary = summarize(benchmark_frame)
        benchmark_frame.to_csv(reports_dir / "benchmark_runs.csv", index=False)
        benchmark_summary.to_csv(reports_dir / "benchmark_summary.csv", index=False)

        qaoa_trials = []
        for trials in (60, 120, 240, 420):
            config = self._image_demo_config("hybrid", episode_seconds=min(240, episode_seconds))
            config.controller.qaoa_trials = trials
            result = self._run_config_controller(config, "hybrid", capture_trace=False, run_id=f"qaoa_{trials}")
            qaoa_trials.append(
                {
                    "trials": trials,
                    "avg_waiting_time": result["metrics"].avg_waiting_time,
                    "avg_queue_length": result["metrics"].avg_queue_length,
                    "throughput": result["metrics"].throughput,
                    "avg_reward": result["metrics"].avg_reward,
                }
            )

        prediction_horizon = []
        for horizon in (2, 4, 6, 8, 10):
            config = self._image_demo_config("hybrid", episode_seconds=min(240, episode_seconds))
            config.controller.prediction_horizon_steps = horizon
            result = self._run_config_controller(config, "hybrid", capture_trace=False, run_id=f"horizon_{horizon}")
            prediction_horizon.append(
                {
                    "horizon": horizon,
                    "avg_waiting_time": result["metrics"].avg_waiting_time,
                    "avg_queue_length": result["metrics"].avg_queue_length,
                    "throughput": result["metrics"].throughput,
                    "avg_reward": result["metrics"].avg_reward,
                }
            )

        scalability = self._scalability_study()
        hybrid_trace = trace_lookup.get("hybrid")
        fixed_trace = trace_lookup.get("fixed")
        hybrid_series = self._trace_series(hybrid_trace)
        fixed_series = self._trace_series(fixed_trace)
        heatmap = self._junction_queue_heatmap(hybrid_trace, preview)

        payload = {
            "title": "Image Demo Traffic Results Dashboard",
            "scenario": {
                "name": "image_interchange_peak",
                "sumocfg_path": str(image_assets["sumocfg"]),
                "net_path": str(image_assets["net"]),
                "episode_seconds": episode_seconds,
                "replications": replications,
            },
            "preview": preview,
            "benchmark": {
                "runs": self._sanitize_json(benchmark_frame.to_dict(orient="records")),
                "summary": self._sanitize_json(benchmark_summary.to_dict(orient="records")),
            },
            "charts": {
                "time_series": {
                    "hybrid": self._sanitize_json(hybrid_series),
                    "fixed": self._sanitize_json(fixed_series),
                },
                "qaoa_trials": self._sanitize_json(qaoa_trials),
                "prediction_horizon": self._sanitize_json(prediction_horizon),
                "scalability": self._sanitize_json(scalability),
                "queue_heatmap": self._sanitize_json(heatmap),
            },
            "artifacts": {
                "benchmark_runs_csv": str(reports_dir / "benchmark_runs.csv"),
                "benchmark_summary_csv": str(reports_dir / "benchmark_summary.csv"),
            },
        }
        self._write_json(reports_dir / "latest.json", payload)
        return payload

    def artifact_path(self, run_id: str, filename: str) -> Path:
        target = (self.runs_dir / run_id / filename).resolve()
        if not str(target).startswith(str((self.runs_dir / run_id).resolve())):
            raise ValueError("Invalid artifact path.")
        if not target.exists():
            raise FileNotFoundError(target)
        return target

    def launch_gui(self, run_id: str) -> dict:
        run_dir = self.runs_dir / run_id
        scenario = self._read_json(run_dir / "scenario.json")
        subprocess.Popen([str(self.sumo.sumo_gui), "-c", scenario["sumocfg_path"]], cwd=run_dir)
        return {"status": "started", "message": "SUMO GUI launched."}

    def launch_image_demo_gui(self) -> dict:
        assets = self._ensure_image_demo_assets()
        subprocess.Popen([str(self.sumo.sumo_gui), "-c", str(assets["sumocfg"])], cwd=self.root)
        return {"status": "started", "message": "Image-demo SUMO GUI launched."}

    def _run_controller(
        self,
        run_id: str,
        controller_name: str,
        sumocfg_path: Path,
        episode_seconds: int,
        capture_trace: bool,
        use_gui: bool,
    ) -> dict:
        config = load_config(self.root / "configs" / "sumo_city.toml")
        config.simulation.backend = "sumo"
        config.simulation.episode_seconds = episode_seconds
        config.simulation.warmup_seconds = min(config.simulation.warmup_seconds, 15)
        config.controller.name = controller_name
        config.controller.phase_actions = ["ns_green", "ew_green"]
        config.sumo.sumocfg_path = str(sumocfg_path)
        config.sumo.sumo_binary = str(self.sumo.sumo_gui if use_gui else self.sumo.sumo)
        config.sumo.use_gui = use_gui
        return self._run_config_controller(config, controller_name, capture_trace, run_id)

    def _run_config_controller(
        self,
        config,
        controller_name: str,
        capture_trace: bool,
        run_id: str,
    ) -> dict:
        env = SumoEnvironment(config)
        controller = build_controller(config)
        observation = env.reset()
        controller.reset(observation)
        trace_steps: list[dict] = []
        rewards: list[float] = []
        done = False
        while not done:
            current_observation = observation
            actions = controller.act(current_observation)
            if capture_trace:
                trace_steps.append(self._trace_step(current_observation, controller_name, controller, actions, config))
            result = env.step(actions)
            rewards.append(result.reward)
            if isinstance(controller, HybridQuantumController):
                controller.record_reward(current_observation, actions, result.reward)
            observation = result.observation
            done = result.done
        avg_wait = env.metrics["total_wait"] / max(1, env.metrics["steps"])
        avg_queue = env.metrics["total_queue"] / max(1, env.metrics["steps"])
        throughput = env.metrics["throughput"]
        avg_reward = -avg_wait - 0.25 * avg_queue + 0.05 * throughput
        metrics = EpisodeMetrics(
            controller_name=controller_name,
            scenario_name=config.scenario.name,
            avg_waiting_time=avg_wait,
            avg_queue_length=avg_queue,
            throughput=throughput,
            avg_reward=avg_reward,
            stops_per_vehicle=env.metrics.get("stops", 0.0) / max(1.0, throughput + 1.0),
            emergency_delay=env.metrics.get("emergency_delay", 0.0) / max(1, env.metrics["steps"]),
            total_steps=env.metrics["steps"],
            metadata={"run_id": run_id, "backend": "sumo"},
        )
        env.close()
        trace = {"run_id": run_id, "controller": controller_name, "steps": trace_steps} if capture_trace else None
        return {"metrics": metrics, "trace": trace}

    def _trace_step(
        self,
        observation: NetworkObservation,
        controller_name: str,
        controller,
        actions: dict[str, str],
        config,
    ) -> dict:
        explanations: dict[str, dict] = {}
        total_queue = 0.0
        total_wait = 0.0
        if isinstance(controller, HybridQuantumController):
            forecast = controller.predictor.predict(observation, config.controller.prediction_horizon_steps)
            qubo = controller.qubo_builder.build(observation, forecast)
            for node_id in observation.ordered_ids():
                item = observation.intersections[node_id]
                total_queue += item.total_queue
                total_wait += item.total_wait
                ns_pressure = item.approaches["north"].queue_length + item.approaches["south"].queue_length
                ew_pressure = item.approaches["east"].queue_length + item.approaches["west"].queue_length
                chosen_action = actions.get(node_id, item.current_phase)
                explanations[node_id] = {
                    "forecast_score": round(forecast.by_intersection[node_id].congestion_score, 4),
                    "ns_pressure": round(ns_pressure, 3),
                    "ew_pressure": round(ew_pressure, 3),
                    "chosen_action": chosen_action,
                    "optimizer_action": controller.last_context.optimizer_assignment.get(node_id, chosen_action)
                    if controller.last_context
                    else chosen_action,
                    "action_rewards": {
                        action: round(-qubo.local_costs[(node_id, action)], 4) for action in config.phase_actions
                    },
                    "one_hot_penalty": config.controller.one_hot_penalty,
                    "coordination_bonus": config.controller.coordination_bonus,
                    "message": self._explain_choice(
                        chosen_action,
                        ns_pressure,
                        ew_pressure,
                        forecast.by_intersection[node_id].congestion_score,
                    ),
                }
        else:
            for node_id in observation.ordered_ids():
                item = observation.intersections[node_id]
                total_queue += item.total_queue
                total_wait += item.total_wait
                ns_pressure = item.approaches["north"].queue_length + item.approaches["south"].queue_length
                ew_pressure = item.approaches["east"].queue_length + item.approaches["west"].queue_length
                explanations[node_id] = {
                    "forecast_score": None,
                    "ns_pressure": round(ns_pressure, 3),
                    "ew_pressure": round(ew_pressure, 3),
                    "chosen_action": actions.get(node_id, item.current_phase),
                    "optimizer_action": None,
                    "action_rewards": {},
                    "one_hot_penalty": None,
                    "coordination_bonus": None,
                    "message": f"{controller_name} controller selected {actions.get(node_id, item.current_phase)} using its internal rule.",
                }
        return {
            "time_seconds": observation.time_seconds,
            "controller": controller_name,
            "actions": actions,
            "network_metrics": {
                "avg_queue": round(total_queue / max(1, len(observation.intersections)), 3),
                "avg_wait": round(total_wait / max(1, len(observation.intersections)), 3),
            },
            "intersections": {
                node_id: {
                    "current_phase": item.current_phase,
                    "phase_age": item.phase_age,
                    "total_queue": round(item.total_queue, 3),
                    "total_wait": round(item.total_wait, 3),
                    "approaches": {
                        approach: {
                            "queue_length": round(obs.queue_length, 3),
                            "avg_speed": round(obs.avg_speed, 3),
                            "occupancy": round(obs.occupancy, 3),
                            "waiting_time": round(obs.waiting_time, 3),
                        }
                        for approach, obs in item.approaches.items()
                    },
                    "decision": explanations[node_id],
                }
                for node_id, item in observation.intersections.items()
            },
        }

    def _image_demo_config(self, controller_name: str, episode_seconds: int, use_gui: bool = False):
        config = load_config(self.root / "configs" / "image_interchange.toml")
        config.controller.name = controller_name
        config.simulation.backend = "sumo"
        config.simulation.episode_seconds = episode_seconds
        config.sumo.sumo_binary = str(self.sumo.sumo_gui if use_gui else self.sumo.sumo)
        config.sumo.use_gui = use_gui
        config.sumo.sumocfg_path = str((self.root / "generated_image_demo" / "image_interchange.sumocfg").resolve())
        return config

    def _ensure_image_demo_assets(self) -> dict[str, Path]:
        output_dir = self.root / "generated_image_demo"
        config = load_config(self.root / "configs" / "image_interchange.toml")
        assets = generate_image_interchange_assets(config, output_dir)
        build_netconvert(assets, netconvert_binary=str(self.sumo.netconvert))
        return assets

    def _trace_series(self, trace: dict | None) -> list[dict]:
        if not trace:
            return []
        points = []
        cumulative_throughput = 0.0
        for step in trace.get("steps", []):
            avg_queue = float(step.get("network_metrics", {}).get("avg_queue", 0.0))
            avg_wait = float(step.get("network_metrics", {}).get("avg_wait", 0.0))
            cumulative_throughput += max(0.0, 5.0 - min(4.5, avg_queue * 0.04))
            points.append(
                {
                    "time_seconds": step["time_seconds"],
                    "avg_queue": avg_queue,
                    "avg_wait": avg_wait,
                    "throughput_proxy": round(cumulative_throughput, 3),
                }
            )
        return points

    def _junction_queue_heatmap(self, trace: dict | None, preview: dict) -> dict:
        if not trace:
            return {"junctions": []}
        junction_totals: dict[str, float] = {}
        step_count = max(1, len(trace.get("steps", [])))
        for step in trace.get("steps", []):
            for node_id, item in step.get("intersections", {}).items():
                junction_totals[node_id] = junction_totals.get(node_id, 0.0) + float(item.get("total_queue", 0.0))
        preview_nodes = {node["id"]: node for node in preview.get("nodes", [])}
        junctions = []
        for node_id, total in sorted(junction_totals.items()):
            node = preview_nodes.get(node_id, {})
            junctions.append(
                {
                    "id": node_id,
                    "avg_queue": round(total / step_count, 3),
                    "x": node.get("x", 0.0),
                    "y": node.get("y", 0.0),
                }
            )
        return {"junctions": junctions}

    def _scalability_study(self) -> list[dict]:
        study_dir = self.root / "reports" / "image_dashboard" / "scalability_assets"
        study_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for size in (2, 3, 4):
            assets_dir = study_dir / f"{size}x{size}"
            config = load_config(self.root / "configs" / "sumo_city.toml")
            config.simulation.backend = "sumo"
            config.simulation.grid_rows = size
            config.simulation.grid_cols = size
            config.simulation.episode_seconds = 150
            config.simulation.arrival_rate = 0.34 + size * 0.03
            config.simulation.warmup_seconds = 15
            config.controller.phase_actions = ["ns_green", "ew_green"]
            assets = generate_grid_assets(config, assets_dir)
            build_netconvert(assets, netconvert_binary=str(self.sumo.netconvert))
            for controller_name in ("fixed", "hybrid"):
                trial_config = deepcopy(config)
                trial_config.controller.name = controller_name
                trial_config.sumo.sumocfg_path = str(assets["sumocfg"])
                trial_config.sumo.sumo_binary = str(self.sumo.sumo)
                trial_config.sumo.use_gui = False
                result = self._run_config_controller(
                    trial_config,
                    controller_name,
                    capture_trace=False,
                    run_id=f"scale_{size}_{controller_name}",
                )
                results.append(
                    {
                        "junction_count": size * size,
                        "controller": controller_name,
                        "avg_waiting_time": result["metrics"].avg_waiting_time,
                        "throughput": result["metrics"].throughput,
                        "avg_reward": result["metrics"].avg_reward,
                    }
                )
        return results

    def _build_area_network(self, run_dir: Path, bbox: dict[str, float]) -> tuple[Path, Path, Path, dict]:
        config = load_config(self.root / "configs" / "sumo_city.toml")
        assets = generate_area_based_assets(config, run_dir, bbox)
        build_netconvert(assets, netconvert_binary=str(self.sumo.netconvert))
        return assets["sumocfg"], assets["net"], assets["rou"], assets["layout"]

    def _build_scanned_area_network(self, run_dir: Path, warm_layout) -> tuple[Path, Path, Path, dict]:
        config = load_config(self.root / "configs" / "sumo_city.toml")
        assets = generate_scanned_major_road_assets(config, run_dir, warm_layout)
        build_netconvert(assets, netconvert_binary=str(self.sumo.netconvert))
        return assets["sumocfg"], assets["net"], assets["rou"], assets["layout"]

    def _network_preview(self, net_path: Path) -> dict:
        if sumolib is None:
            raise RuntimeError("sumolib is not installed.")
        net = sumolib.net.readNet(str(net_path))
        nodes = []
        edges = []
        for node in net.getNodes():
            x, y = node.getCoord()
            nodes.append({"id": node.getID(), "x": float(x), "y": float(y), "type": node.getType()})
        for edge in net.getEdges():
            if edge.isSpecial():
                continue
            shape = edge.getShape() or [edge.getFromNode().getCoord(), edge.getToNode().getCoord()]
            edges.append(
                {
                    "id": edge.getID(),
                    "from": edge.getFromNode().getID(),
                    "to": edge.getToNode().getID(),
                    "lanes": edge.getLaneNumber(),
                    "shape": [{"x": float(x), "y": float(y)} for x, y in shape],
                }
            )
        xs = [item["x"] for item in nodes] or [0.0]
        ys = [item["y"] for item in nodes] or [0.0]
        return {
            "nodes": nodes,
            "edges": edges,
            "bounds": {
                "min_x": min(xs),
                "max_x": max(xs),
                "min_y": min(ys),
                "max_y": max(ys),
            },
        }


    def _resolve_sumo_install(self) -> SumoInstall:
        for base in (Path(r"C:\Program Files\Eclipse\Sumo"), Path(r"C:\Program Files (x86)\Eclipse\Sumo")):
            sumo = base / "bin" / "sumo.exe"
            sumo_gui = base / "bin" / "sumo-gui.exe"
            netconvert = base / "bin" / "netconvert.exe"
            random_trips = base / "tools" / "randomTrips.py"
            if all(path.exists() for path in (sumo, sumo_gui, netconvert, random_trips)):
                return SumoInstall(sumo=sumo, sumo_gui=sumo_gui, netconvert=netconvert, random_trips=random_trips)
        raise RuntimeError("SUMO installation not found.")

    def _bbox_from_polygon(self, polygon: list[dict[str, float]]) -> dict[str, float]:
        lats = [point["lat"] for point in polygon]
        lngs = [point["lng"] for point in polygon]
        return {
            "south": min(lats),
            "north": max(lats),
            "west": min(lngs),
            "east": max(lngs),
        }

    def _explain_choice(self, action: str, ns_pressure: float, ew_pressure: float, forecast: float) -> str:
        if action == "ns_green":
            return f"North-south green was selected because north-south pressure ({ns_pressure:.2f}) is dominant and forecast congestion is {forecast:.2f}."
        if action == "ew_green":
            return f"East-west green was selected because east-west pressure ({ew_pressure:.2f}) is dominant and forecast congestion is {forecast:.2f}."
        if action == "pedestrian_all_red":
            return f"Pedestrian all-red was selected as a defensive phase under forecast congestion {forecast:.2f}."
        return "Hold was selected because the queues are currently balanced."

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(self._sanitize_json(payload), indent=2), encoding="utf-8")

    def _read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _sanitize_json(self, value):
        if isinstance(value, float):
            return value if value == value and value not in (float("inf"), float("-inf")) else None
        if isinstance(value, dict):
            return {key: self._sanitize_json(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize_json(item) for item in value]
        return value
