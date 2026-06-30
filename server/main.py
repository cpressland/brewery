import base64
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .routes.api import router as api_router
from .routes.web import router as web_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Brewery", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.include_router(api_router)
app.include_router(web_router)


def _basic_auth_valid(request: Request, password: str) -> bool:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return False
    try:
        _, _, supplied = base64.b64decode(auth[6:]).decode().partition(":")
        return supplied == password
    except Exception:
        return False


class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        password = os.environ.get("BREWERY_PASSWORD")
        if password:
            path = request.url.path
            if not path.startswith("/api") and path != "/login":
                if path == "/install" and _basic_auth_valid(request, password):
                    return await call_next(request)
                if not request.session.get("logged_in"):
                    return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)


# AuthMiddleware added first (inner), SessionMiddleware added second (outer → runs first on request)
app.add_middleware(_AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY", "brewery-dev-secret"))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    body = await request.body()
    log.error("422 %s %s — %s — body: %s", request.method, request.url.path, exc.errors(), body.decode(errors="replace"))
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def run() -> None:
    uvicorn.run("server.main:app", host="0.0.0.0", port=6502, reload=False)
