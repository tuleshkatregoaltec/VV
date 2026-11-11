from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from app.config import settings

PREVIEW_REGEX = r"^https://[a-z0-9-]+\.vv-pilot\.pages\.dev$"


def test_main_app_passes_origin_regex_setting_to_cors():
    from app.main import app

    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_origin_regex"] == settings.ALLOWED_ORIGIN_REGEX


async def _preflight(origin: str) -> str | None:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://vv-pilot.pages.dev"],
        allow_origin_regex=PREVIEW_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/ping",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
    return response.headers.get("access-control-allow-origin")


async def test_documented_preview_regex_allows_pages_previews():
    assert (
        await _preflight("https://pr-58.vv-pilot.pages.dev") == "https://pr-58.vv-pilot.pages.dev"
    )
    assert await _preflight("https://vv-pilot.pages.dev") == "https://vv-pilot.pages.dev"


async def test_documented_preview_regex_rejects_lookalike_hosts():
    assert await _preflight("https://pr-58.vv-pilot.pages.dev.attacker.example") is None
    assert await _preflight("http://pr-58.vv-pilot.pages.dev") is None
    assert await _preflight("https://evil.example/https://pr-58.vv-pilot.pages.dev") is None
