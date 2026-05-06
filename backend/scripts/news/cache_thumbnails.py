from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.news.models import NewsArticle  # noqa: E402
from app.news.service import (  # noqa: E402
    NEWS_THUMBNAIL_PREFIX,
    fetch_news_thumbnail,
    news_thumbnail_cache_path,
)


def load_env() -> None:
    for path in (Path.cwd() / ".env.dev", Path.cwd().parent / ".env.dev"):
        if path.exists():
            load_dotenv(path, override=False)
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warm local news thumbnail cache for demos.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


async def warm_cache(args: argparse.Namespace) -> None:
    engine = create_async_engine(str(settings.DATABASE_URL), echo=False, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            stmt = (
                select(NewsArticle)
                .where(NewsArticle.thumbnail_url.startswith(NEWS_THUMBNAIL_PREFIX))  # type: ignore[union-attr]
                .order_by(NewsArticle.publish_date.desc())
            )
            if args.limit is not None:
                stmt = stmt.limit(args.limit)
            result = await db.exec(stmt)
            articles = list(result.all())

            cached = 0
            built = 0
            failed = 0
            for index, article in enumerate(articles, start=1):
                path = news_thumbnail_cache_path(article)
                was_cached = path.exists()
                if args.force and path.exists():
                    path.unlink()
                    was_cached = False

                try:
                    cached_path, _ = await fetch_news_thumbnail(db, article.id)
                except Exception as exc:
                    failed += 1
                    print(f"{index}/{len(articles)} failed article_id={article.id}: {exc}")
                    continue

                size_kb = cached_path.stat().st_size / 1024
                if was_cached:
                    cached += 1
                    status = "cached"
                else:
                    built += 1
                    status = "built"
                print(
                    f"{index}/{len(articles)} {status} article_id={article.id} size={size_kb:.1f}KB"
                )

            print(f"done total={len(articles)} cached={cached} built={built} failed={failed}")
    finally:
        await engine.dispose()


def main() -> int:
    load_env()
    asyncio.run(warm_cache(parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
