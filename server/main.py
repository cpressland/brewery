import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .database import engine
from .models import Base
from .routes.api import router as api_router
from .routes.web import router as web_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Brewery", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.include_router(api_router)
app.include_router(web_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    body = await request.body()
    log.error("422 %s %s — %s — body: %s", request.method, request.url.path, exc.errors(), body.decode(errors="replace"))
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def run() -> None:
    uvicorn.run("server.main:app", host="0.0.0.0", port=6502, reload=False)
