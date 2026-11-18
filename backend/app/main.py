import logging.config
from contextlib import asynccontextmanager

import logfire
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from honeybadger import contrib, honeybadger
from pydantic import BaseModel
from pydantic_ai import Agent
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.admin.router import router as admin_router
from app.analytics.router import router as analytics_router
from app.area.router import router as area_router
from app.assistant_actions.router import router as assistant_actions_router
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.billing.webhooks import router as billing_webhooks
from app.chat.router import router as chat_router
from app.clickhouse import close_clickhouse
from app.config import settings
from app.core.logging_config import LOGGING_CONFIG
from app.core.observability import Middleware as ObservabilityMiddleware
from app.core.observability import configure as configure_observability
from app.crm.collection_public_router import router as crm_collection_public_router
from app.crm.router import router as crm_router
from app.feasibility.router import router as feasibility_router
from app.filters.router import router as filters_router
from app.listings.router import router as listings_router
from app.news.router import router as news_router
from app.organization.router import router as organization_router
from app.postgres import close_postgres
from app.project.router import router as project_router
from app.providers.auth.auth_backend import AuthBackend
from app.supply.router import router as supply_router
from app.transaction.router import router as transaction_router
from app.upload.router import router as upload_router
from app.whatsapp.connection_router import admin_router as whatsapp_admin_router
from app.whatsapp.connection_router import router as whatsapp_connection_router
from app.whatsapp.customer_connections import (
    bootstrap_on_startup as bootstrap_whatsapp_env_connection,
)
from app.whatsapp.customer_intake import shutdown as drain_whatsapp_classification
from app.whatsapp.customer_router import router as whatsapp_customer_router
from app.whatsapp.logging import CallbackQueryFilter
from app.whatsapp.logging import scrub_notice as scrub_whatsapp_notice
from app.whatsapp.router import router as whatsapp_router

# Remote telemetry must cross our allowlist exporter; legacy Logfire defaults can
# capture endpoint bodies and provider exceptions containing private CRM text.
logfire.configure(send_to_logfire=False)
observability_provider = configure_observability(settings)
if observability_provider is None:
    Agent.instrument_all(False)
logging.config.dictConfig(LOGGING_CONFIG)
logging.getLogger("uvicorn.access").addFilter(CallbackQueryFilter())


def custom_generate_unique_id(route: APIRoute) -> str:
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}-{route.name}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    await bootstrap_whatsapp_env_connection()
    yield
    await drain_whatsapp_classification()
    await close_clickhouse()
    await close_postgres()
    if observability_provider is not None:
        observability_provider.shutdown()


def docs_urls_for(environment: str) -> dict[str, str | None]:
    """Interactive docs and the schema are for local development only.

    Staging and production serve a live API behind a public tunnel; /docs, /redoc and
    /openapi.json would publish every route and model to anyone. `app.openapi()` still
    works in-process, so client generation (scripts/generate-client.sh) is unaffected.
    """
    if environment == "local":
        return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan,
    **docs_urls_for(settings.ENVIRONMENT),
    generate_unique_id_function=custom_generate_unique_id,
)
if observability_provider is not None:
    # Use one HTTP instrumentation path so every exported child has its parent.
    app.add_middleware(ObservabilityMiddleware)

if settings.honeybadger_enabled:
    honeybadger.configure(api_key=settings.HONEYBADGER_API_KEY, before_notify=scrub_whatsapp_notice)


def _authentication_error(conn, exc: Exception) -> JSONResponse:
    return JSONResponse(
        {"detail": "Invalid credentials"},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


app.add_middleware(AuthenticationMiddleware, backend=AuthBackend(), on_error=_authentication_error)
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET)
if settings.honeybadger_enabled:
    app.add_middleware(contrib.ASGIHoneybadger)  # type: ignore
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.all_cors_origins,
    allow_origin_regex=settings.ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, tags=["auth"])
app.include_router(analytics_router, tags=["analytics"])
app.include_router(area_router, tags=["areas"])
app.include_router(chat_router, tags=["chat"])
app.include_router(assistant_actions_router, tags=["assistant_actions"])
app.include_router(crm_router, tags=["crm"])
app.include_router(crm_collection_public_router, tags=["public"])
app.include_router(filters_router, tags=["filters"])
app.include_router(listings_router, tags=["listings"])
app.include_router(news_router, tags=["news"])
app.include_router(organization_router, tags=["organization"])
app.include_router(project_router, tags=["projects"])
app.include_router(supply_router, tags=["supply"])
app.include_router(transaction_router, tags=["transactions"])
app.include_router(upload_router, tags=["upload"])
app.include_router(billing_router, tags=["billing"])
app.include_router(billing_webhooks, tags=["webhooks"])
app.include_router(whatsapp_router, tags=["webhooks"])
app.include_router(whatsapp_customer_router, tags=["whatsapp"])
app.include_router(whatsapp_connection_router, tags=["whatsapp"])
app.include_router(whatsapp_admin_router, tags=["admin"])
app.include_router(admin_router, tags=["admin"])
app.include_router(feasibility_router, tags=["feasibility"])


class HealthResponse(BaseModel):
    status: str


@app.get(f"{settings.API_V1_STR}/health", response_model=HealthResponse)
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
