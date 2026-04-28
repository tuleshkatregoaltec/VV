from __future__ import annotations

import argparse
import hashlib
import logging
import mimetypes
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from holocron.platform.s3 import S3Client
from holocron.platform.settings import Settings

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
IMG_TAG_PATTERN = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
ATTR_PATTERN = re.compile(r"([:\w-]+)\s*=\s*(['\"])(.*?)\2", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class FeedArticle:
    source_feed_url: str
    url: str
    headline: str
    publish_date: datetime | None
    thumbnail_source_url: str | None


@dataclass(frozen=True, slots=True)
class NewsSyncResult:
    feeds_processed: int
    articles_seen: int
    created: int
    skipped_existing: int
    failed: int


def parse_feed_urls(raw: str) -> tuple[str, ...]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line in seen:
            continue
        seen.add(line)
        urls.append(line)
    return tuple(urls)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    without_tags = TAG_PATTERN.sub(" ", value)
    normalized = WHITESPACE_PATTERN.sub(" ", unescape(without_tags)).strip()
    return normalized


def parse_publish_date(value: str | None) -> datetime | None:
    if not value:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("news: could not parse publish date %r", value)
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def extract_first_image_url(content_html: str | None) -> str | None:
    if not content_html:
        return None

    first_image: str | None = None
    for tag in IMG_TAG_PATTERN.findall(content_html):
        attrs = {name.lower(): val for name, _, val in ATTR_PATTERN.findall(tag)}
        src = attrs.get("src", "").strip()
        if not src:
            continue
        if first_image is None:
            first_image = src
        css_classes = attrs.get("class", "")
        if "wp-post-image" in css_classes.split():
            return src
    return first_image


def parse_feed(xml_text: str, *, source_feed_url: str) -> list[FeedArticle]:
    root = ET.fromstring(xml_text)
    root_name = _local_name(root.tag)
    if root_name == "rss":
        return _parse_rss_feed(root, source_feed_url=source_feed_url)
    if root_name == "feed":
        return _parse_atom_feed(root, source_feed_url=source_feed_url)
    raise ValueError(f"Unsupported feed root <{root_name}> for {source_feed_url}")


def _parse_rss_feed(root: ET.Element, *, source_feed_url: str) -> list[FeedArticle]:
    channel = next((child for child in root if _local_name(child.tag) == "channel"), root)
    articles: list[FeedArticle] = []
    for item in channel:
        if _local_name(item.tag) != "item":
            continue
        title = clean_text(_first_child_text(item, "title"))
        link = (_first_child_text(item, "link") or "").strip()
        publish_date = parse_publish_date(
            _first_child_text(item, "pubDate")
            or _first_child_text(item, "published")
            or _first_child_text(item, "updated")
            or _first_child_text(item, "date")
        )
        content_html = _first_child_text(item, "encoded") or _first_child_text(item, "description")
        articles.append(
            FeedArticle(
                source_feed_url=source_feed_url,
                url=link,
                headline=title,
                publish_date=publish_date,
                thumbnail_source_url=extract_first_image_url(content_html),
            )
        )
    return articles


def _parse_atom_feed(root: ET.Element, *, source_feed_url: str) -> list[FeedArticle]:
    articles: list[FeedArticle] = []
    for entry in root:
        if _local_name(entry.tag) != "entry":
            continue
        title = clean_text(_first_child_text(entry, "title"))
        link = _atom_link(entry)
        publish_date = parse_publish_date(
            _first_child_text(entry, "published") or _first_child_text(entry, "updated")
        )
        content_html = _first_child_text(entry, "content") or _first_child_text(entry, "summary")
        articles.append(
            FeedArticle(
                source_feed_url=source_feed_url,
                url=link,
                headline=title,
                publish_date=publish_date,
                thumbnail_source_url=extract_first_image_url(content_html),
            )
        )
    return articles


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_child_text(element: ET.Element, *names: str) -> str | None:
    wanted = set(names)
    for child in element:
        if _local_name(child.tag) not in wanted:
            continue
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return None


def _atom_link(entry: ET.Element) -> str:
    fallback = ""
    for child in entry:
        if _local_name(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        rel = (child.attrib.get("rel") or "alternate").strip()
        if href and rel in {"alternate", ""}:
            return href
        if href and not fallback:
            fallback = href
    return fallback


class PlatformNewsWriter:
    def __init__(self, postgres_url: str) -> None:
        self._postgres_url = postgres_url.strip()
        if not self._postgres_url:
            raise ValueError("PLATFORM_POSTGRES_URL is required for news sync")

    def article_exists(self, cursor, url: str) -> bool:
        cursor.execute("SELECT 1 FROM news_articles WHERE url = %s LIMIT 1", (url,))
        return cursor.fetchone() is not None

    def insert_article(self, cursor, article: FeedArticle, *, thumbnail_url: str | None) -> None:
        cursor.execute(
            """
            INSERT INTO news_articles (url, headline, thumbnail_url, thumbnail_base64, publish_date)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                article.url,
                article.headline[:255],
                thumbnail_url[:255] if thumbnail_url else None,
                None,
                article.publish_date,
            ),
        )

    def connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for direct platform news writes. Run `uv sync --dev`."
            ) from exc
        return psycopg.connect(self._postgres_url, autocommit=True)


class NewsSyncService:
    def __init__(self, settings: Settings, *, skip_thumbnail_upload: bool = False) -> None:
        self._settings = settings
        self._skip_thumbnail_upload = skip_thumbnail_upload
        self._writer = PlatformNewsWriter(settings.platform_postgres_url)
        self._s3 = (
            S3Client(settings)
            if settings.s3_bucket and settings.s3_public_url_base and not skip_thumbnail_upload
            else None
        )

    def sync(self, feed_urls: tuple[str, ...]) -> NewsSyncResult:
        seen_urls: set[str] = set()
        created = 0
        skipped_existing = 0
        failed = 0
        articles_seen = 0

        with self._writer.connect() as connection:
            with connection.cursor() as cursor:
                for feed_url in feed_urls:
                    try:
                        xml_text = _download_text(feed_url)
                        articles = parse_feed(xml_text, source_feed_url=feed_url)
                    except Exception:
                        logger.exception("news: failed to fetch or parse feed %s", feed_url)
                        failed += 1
                        continue

                    logger.info("news: fetched %s entries from %s", len(articles), feed_url)
                    for article in articles:
                        if not article.url or not article.headline:
                            continue
                        articles_seen += 1
                        if article.url in seen_urls:
                            skipped_existing += 1
                            continue
                        seen_urls.add(article.url)
                        try:
                            if self._writer.article_exists(cursor, article.url):
                                skipped_existing += 1
                                continue
                            thumbnail_url = self._resolve_thumbnail_url(
                                article.thumbnail_source_url
                            )
                            self._writer.insert_article(
                                cursor,
                                article,
                                thumbnail_url=thumbnail_url,
                            )
                            created += 1
                        except Exception:
                            logger.exception("news: failed to persist article %s", article.url)
                            failed += 1

        return NewsSyncResult(
            feeds_processed=len(feed_urls),
            articles_seen=articles_seen,
            created=created,
            skipped_existing=skipped_existing,
            failed=failed,
        )

    def _resolve_thumbnail_url(self, image_url: str | None) -> str | None:
        if not image_url:
            return None
        if self._s3 is None:
            return image_url

        try:
            image_bytes, content_type = _download_bytes(image_url)
        except Exception:
            logger.warning("news: failed to download thumbnail %s", image_url, exc_info=True)
            return image_url

        extension = _guess_extension(image_url, content_type)
        digest = hashlib.sha256(image_bytes).hexdigest()
        key = f"{self._settings.news_thumbnail_prefix.strip('/')}/{digest}{extension}"
        try:
            self._s3.put_bytes(key=key, payload=image_bytes, content_type=content_type)
        except Exception:
            logger.warning("news: failed to upload thumbnail %s", image_url, exc_info=True)
            return image_url

        return f"{self._settings.s3_public_url_base.rstrip('/')}/{key}"


def _download_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlopen(request, timeout=60) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _download_bytes(url: str) -> tuple[bytes, str | None]:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlopen(request, timeout=60) as response:
        content_type = response.headers.get_content_type()
        payload = response.read()
    return payload, content_type


def _guess_extension(url: str, content_type: str | None) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension(content_type or "")
    return guessed or ".bin"


def _resolve_cli_feed_urls(
    *,
    args: argparse.Namespace,
    settings: Settings,
) -> tuple[str, ...]:
    configured = parse_feed_urls(settings.news_feed_urls)
    cli_urls = tuple(args.feed_url or [])
    file_urls: tuple[str, ...] = ()
    if args.feed_urls_file:
        file_urls = parse_feed_urls(Path(args.feed_urls_file).read_text(encoding="utf-8"))

    combined: list[str] = []
    seen: set[str] = set()
    for url in (*cli_urls, *file_urls, *configured):
        if url in seen:
            continue
        seen.add(url)
        combined.append(url)
    return tuple(combined)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync RSS/Atom news feeds into the platform DB")
    parser.add_argument(
        "--feed-url",
        action="append",
        default=[],
        help="Feed URL to ingest. Repeat to pass multiple feeds.",
    )
    parser.add_argument(
        "--feed-urls-file",
        default="",
        help="Optional text file with one feed URL per line.",
    )
    parser.add_argument(
        "--skip-thumbnail-upload",
        action="store_true",
        help="Leave thumbnail_url pointing at the source image instead of mirroring to S3.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python log level. Defaults to INFO.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO))

    runtime_settings = Settings()
    feed_urls = _resolve_cli_feed_urls(args=args, settings=runtime_settings)
    if not feed_urls:
        parser.error("No feed URLs configured. Set NEWS_FEED_URLS or pass --feed-url.")

    result = NewsSyncService(
        runtime_settings,
        skip_thumbnail_upload=bool(args.skip_thumbnail_upload),
    ).sync(feed_urls)

    logger.info(
        "news: sync complete feeds=%s seen=%s created=%s skipped_existing=%s failed=%s",
        result.feeds_processed,
        result.articles_seen,
        result.created,
        result.skipped_existing,
        result.failed,
    )
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
