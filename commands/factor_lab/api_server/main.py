"""FastAPI 主入口 — 替换 http.server Dashboard"""
import sys, os, json
from pathlib import Path
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from factor_lab.api_server.routes_status import router as status_router
from factor_lab.api_server.routes_roadmap import router as roadmap_router
from factor_lab.api_server.routes_console import router as console_router
from factor_lab.api_server.routes_backup import router as backup_router

FE_DIST = Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Hermes API: http://127.0.0.1:8766")
    print(f"Static files: {FE_DIST if FE_DIST.exists() else 'not built — use Vite dev server in proxy mode'}")
    yield


app = FastAPI(title="Hermes API", version="1.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(status_router, prefix="/api")
app.include_router(roadmap_router, prefix="/api")
app.include_router(console_router, prefix="/api")
app.include_router(backup_router, prefix="/api")

# 生产模式: React dist 挂载为静态文件
if FE_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FE_DIST), html=True), name="frontend")


def serve(host="127.0.0.1", port=8766):
    import uvicorn
    print(f"Hermes API: http://{host}:{port}")
    print(f"OpenAPI docs: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="info")
