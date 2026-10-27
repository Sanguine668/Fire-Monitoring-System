from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST


def mount_frontend(app: FastAPI) -> None:
    if not (FRONTEND_DIST / "index.html").is_file():
        return
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        # index.html 里引用的是带哈希的静态资源名，必须每次回源校验，
        # 否则重新构建前端后浏览器可能仍加载旧资源，看到的是旧样式。
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )
