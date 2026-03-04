import logfire
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.authentication import AuthenticationMiddleware
from honeybadger import contrib, honeybadger
import logging.config
from contextlib import asynccontextmanager

from app.config import settings
from app.clickhouse import close_clickhouse
from app.postgres import close_postgres

from app.analytics.router import router as analytics_router
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.filters.router import router as filters_router
from app.news.router import router as news_router
from app.organization.router import router as organization_router
from app.project.router import router as project_router
from app.supply.router import router as supply_router
from app.transaction.router import router as transaction_router
from app.upload.router import router as upload_router
from app.upload.router import health_router
from app.billing.router import router as billing_router
from app.billing.webhooks import router as billing_webhooks
from app.admin.router import router as admin_router
from app.feasibility.router import router as feasibility_router

from app.providers.auth.auth_backend import AuthBackend

from app.core.logging_config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    yield
    await close_clickhouse()
    await close_postgres()


logfire.configure()
logfire.instrument_pydantic_ai()

app = FastAPI(title="Real Estate API", version="1.0.0", lifespan=lifespan)
logfire.instrument_fastapi(app)

honeybadger.configure(
    api_key=settings.HONEYBADGER_API_KEY,
)

app.add_middleware(AuthenticationMiddleware, backend=AuthBackend())
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET)
app.add_middleware(contrib.ASGIHoneybadger)  # type: ignore
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, tags=["auth"])
app.include_router(analytics_router, tags=["analytics"])
app.include_router(chat_router, tags=["chat"])
app.include_router(filters_router, tags=["filters"])
app.include_router(news_router, tags=["news"])
app.include_router(organization_router, tags=["organization"])
app.include_router(project_router, tags=["projects"])
app.include_router(supply_router, tags=["supply"])
app.include_router(transaction_router, tags=["transactions"])
app.include_router(upload_router, tags=["upload"])
app.include_router(health_router, tags=["upload"])
app.include_router(billing_router, tags=["billing"])
app.include_router(billing_webhooks, tags=["webhooks"])
app.include_router(admin_router, tags=["admin"])
app.include_router(feasibility_router, tags=["feasibility"])


@app.get("/api/v1/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
