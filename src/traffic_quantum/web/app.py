from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import uvicorn

from traffic_quantum.web.service import TrafficWebService


class AreaRequest(BaseModel):
    polygon: list[dict[str, float]] = Field(min_length=3)
    scenario_name: str | None = None
    image_data: str | None = None


class SimulationRequest(BaseModel):
    controller: str = "hybrid"
    episode_seconds: int = 300
    open_gui: bool = False
    mode: str = "quick"


class ImageDemoRequest(BaseModel):
    episode_seconds: int = 300
    replications: int = 2


def create_app() -> FastAPI:
    app = FastAPI(title="Traffic Quantum Dashboard")
    service = TrafficWebService()
    web_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("image_results.html", {"request": request})

    @app.get("/map-dashboard", response_class=HTMLResponse)
    async def map_dashboard(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/api/image-demo/latest")
    async def get_latest_image_demo():
        payload = service.get_latest_image_demo()
        if payload is None:
            raise HTTPException(status_code=404, detail="No image-demo analytics have been generated yet.")
        return payload

    @app.post("/api/image-demo/run")
    async def run_image_demo(payload: ImageDemoRequest):
        try:
            return service.run_image_demo_dashboard(
                episode_seconds=payload.episode_seconds,
                replications=payload.replications,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/image-demo/open-gui")
    async def open_image_demo_gui():
        try:
            return service.launch_image_demo_gui()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/areas")
    async def create_area(payload: AreaRequest):
        try:
            return service.create_area_scenario(payload.polygon, payload.scenario_name, payload.image_data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/simulate")
    async def run_simulation(run_id: str, payload: SimulationRequest):
        try:
            return service.run_area_benchmark(
                run_id=run_id,
                selected_controller=payload.controller,
                episode_seconds=payload.episode_seconds,
                open_gui=payload.open_gui,
                mode=payload.mode,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        try:
            return service.get_run(run_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/open-gui")
    async def open_gui(run_id: str):
        try:
            return service.launch_gui(run_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/artifacts/{filename}")
    async def download_artifact(run_id: str, filename: str):
        try:
            path = service.artifact_path(run_id, filename)
            return FileResponse(path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


def main() -> None:
    uvicorn.run(
        "traffic_quantum.web.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
