from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .database import engine
from .models import Base
from .routes.api import router as api_router
from .routes.web import router as web_router
from .settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Brewery", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.include_router(api_router)
app.include_router(web_router)


def run() -> None:
    uvicorn.run("server.main:app", host=settings.host, port=settings.port, reload=False)
