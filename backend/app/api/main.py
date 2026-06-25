import app.config.settings  # noqa: F401
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import health, jobs
from app.config.settings import get_settings
from app.core.common.logger import configure_json_logging
from app.core.context_manager import ContextManager
from app.service.container import ServiceContainer
from app.service.exceptions import BaseServiceException


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_json_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)

    context_manager = ContextManager(settings)
    await context_manager.initialize()

    app.state.context_manager = context_manager
    app.state.container = ServiceContainer(context_manager)

    yield

    await context_manager.close()


from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Medical Billing Extraction API", lifespan=lifespan)

# Enable CORS for frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.exception_handler(BaseServiceException)
async def service_exception_handler(request: Request, exc: BaseServiceException):
    return JSONResponse(
        status_code=exc.http_status.value,
        content=exc.to_dict(),
    )


app.include_router(health.router, tags=["Health"])
app.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
