import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from honeybadger import contrib, honeybadger
import logging.config

from app.config import settings
from app.routers import (
    auth,
    admin,
    transactions,
    transaction_matching,
    supply,
    analytics,
    filters,
    chat,
    upload,
)
from app.core.logging_config import LOGGING_CONFIG

logging.config.dictConfig(LOGGING_CONFIG)

app = FastAPI(title="Real Estate API", version="1.0.0")

honeybadger.configure(
    api_key=settings.HONEYBADGER_API_KEY,
)

app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(contrib.ASGIHoneybadger)  # type: ignore


app.include_router(auth.router, tags=["auth"])
app.include_router(admin.router, tags=["admin"])
app.include_router(transactions.router, tags=["transactions"])
app.include_router(transaction_matching.router, tags=["transaction-matching"])
app.include_router(supply.router, tags=["supply"])
app.include_router(analytics.router, tags=["analytics"])
app.include_router(filters.router, tags=["filters"])
app.include_router(chat.router, tags=["chat"])
app.include_router(upload.router, tags=["upload"])
app.include_router(upload.health_router, tags=["upload-health"])


@app.get("/api/vi/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
