# Quantum-Enhanced Multi-Agent Traffic Signal Control

This repository contains a runnable hybrid traffic-signal control project with:

- A mock urban-grid simulator that runs without SUMO for local development and testing.
- A TraCI/SUMO adapter that can control real SUMO traffic lights when SUMO binaries are installed.
- Baseline controllers: fixed-time, actuated, genetic-search.
- A hybrid controller that combines:
  - graph-based congestion forecasting,
  - QUBO formulation,
  - QAOA-style optimization with a quantum-inspired fallback,
  - a lightweight policy network for adaptive action refinement.
- Experiment runners, reporting, and a digital-twin style counterfactual evaluator.

## What is runnable right now

The mock backend is fully runnable in this workspace.

The SUMO backend is implemented, but this machine does not currently expose `sumo.exe` on `PATH`, so real SUMO runs require either:

- `SUMO_BINARY` environment variable pointing to `sumo.exe`, or
- `SUMO_HOME` pointing to your SUMO install, or
- a configured `sumo_binary` path in the TOML config.

## Quick start

```bash
python -m pip install -e .
traffic-quantum smoke-test --controller hybrid
traffic-quantum benchmark --config configs/mock_city.toml --output reports
```

## One-command run on Windows

From the project folder in VS Code or Command Prompt:

```bat
run_project.bat
```

That command:

- reuses or creates `.venv`,
- ensures the package is installed,
- runs the verified mock benchmark,
- writes CSV outputs into `reports`.

Other shortcuts:

```bat
run_project.bat smoke
run_project.bat train
run_project.bat assets
run_project.bat test
run_sumo_gui.bat
run_web_dashboard.bat
```

## Web dashboard

The project now includes a browser dashboard that lets you:

- draw an area on a live map,
- build a SUMO-ready scenario from OSM when possible,
- fall back to a generated SUMO grid when extraction is not usable,
- run the selected controller plus baseline comparison,
- replay junction decisions and inspect penalties, rewards, and explanations,
- download CSV and JSON artifacts for the run.

Run it with:

```bat
run_web_dashboard.bat
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Project layout

```text
src/traffic_quantum/
  analysis/        metrics, experiment runner
  controllers/     fixed, actuated, GA, hybrid controller
  quantum/         predictor, QUBO builder, QAOA solver, digital twin
  sim/             mock environment and SUMO adapter
  cli.py           command-line interface
```

## Example commands

```bash
traffic-quantum smoke-test --controller fixed
traffic-quantum smoke-test --controller actuated
traffic-quantum smoke-test --controller genetic
traffic-quantum smoke-test --controller hybrid

traffic-quantum benchmark --config configs/mock_city.toml --output reports
traffic-quantum train-policy --config configs/mock_city.toml --episodes 12
```

## SUMO usage

1. Install SUMO 1.18+.
2. Ensure `sumo.exe` is available through one of the supported discovery methods.
3. Create or point to a SUMO `.sumocfg` and route/network files.
4. Use a config modeled after `configs/sumo_city.toml`.

Example:

```bash
traffic-quantum smoke-test --backend sumo --controller hybrid --config configs/sumo_city.toml
```

## Notes on the quantum modules

This codebase includes a real interface boundary for quantum execution, but defaults to a quantum-inspired solver when Qiskit/PennyLane are not installed. That keeps the full system operational on a normal laptop while preserving the same controller architecture.
"# final-toc-23mis0616" 
