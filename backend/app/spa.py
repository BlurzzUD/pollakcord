from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings


def mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.frontend_dist
    index = dist / "index.html"
    if not settings.serve_frontend or not index.is_file():
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "media/")):
            return JSONResponse({"error": {"code": "not_found", "message": "not_found"}}, status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
