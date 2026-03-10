#!/usr/bin/env python3
"""
Usage:
    python -m scripts.cron_sync

Environment variables:
    BACKEND_URL: Base URL of the backend API (required)
    SERVICE_API_KEY: API key for authentication (required)
    LOG_FILE: Path to log file (default: /var/log/vitevue/cron_sync.log)

Cron example (daily at 3 AM):
    0 3 * * * /path/to/venv/bin/python -m scripts.cron_sync
"""

import hashlib
import logging
import os
import random
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.config import settings

SOURCES = [
    "https://www.dubaipulse.gov.ae/data/dld-transactions/dld_transactions-open",
    "https://www.dubaipulse.gov.ae/data/dld-registration/dld_rent_contracts-open",
    "https://www.dubaipulse.gov.ae/data/dld-transactions/dld_lkp_areas-open",
    "https://www.dubaipulse.gov.ae/data/dld-transactions/dld_lkp_transaction_procedures-open",
    "https://www.dubaipulse.gov.ae/data/dld-registration/dld_buildings-open",
    "https://www.dubaipulse.gov.ae/data/dld-registration/dld_units-open",
    "https://www.dubaipulse.gov.ae/data/dld-registration/dld_projects-open",
    "https://www.dubaipulse.gov.ae/data/dld-registration/dld_developers-open",
    "https://www.dubaipulse.gov.ae/data/dld-registration/dld_land_registry-open",
    "https://www.dubaipulse.gov.ae/data/dld-transactions/dld_lkp_transaction_groups-open",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def setup_logging() -> logging.Logger:
    log_file = os.environ.get("LOG_FILE", "./logs/cron_sync.log")
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("cron_sync")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
    logger.addHandler(handler)

    return logger


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
        }
    )
    return session


def get_download_link(
    page_url: str, session: requests.Session, logger: logging.Logger
) -> str | None:
    try:
        response = session.get(page_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        download_anchor = soup.find("a", class_="action-icon-anchor", href=True)
        if download_anchor:
            return urljoin(page_url, str(download_anchor["href"]))
        else:
            logger.error(f"Download link not found on page: {page_url}")
            return None
    except Exception as e:
        logger.error(f"Failed to fetch page {page_url}: {e}")
        return None


def download_file(
    url: str,
    session: requests.Session,
    temp_dir: Path,
    logger: logging.Logger,
) -> tuple[Path | None, str | None]:
    try:
        response = session.get(url, stream=True, timeout=300)
        response.raise_for_status()

        filename = url.split("/")[-1].split("?")[0]
        if "Content-Disposition" in response.headers:
            content_disp = response.headers["Content-Disposition"]
            if "filename=" in content_disp:
                filename = content_disp.split("filename=")[1].strip('"')

        filepath = temp_dir / filename
        total_size = 0

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                total_size += len(chunk)

        logger.info(f"Downloaded: {filename} ({total_size:,} bytes)")
        return filepath, filename

    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        return None, None


def upload_file(
    filepath: Path,
    source_url: str,
    backend_url: str,
    api_key: str,
    logger: logging.Logger,
) -> bool:
    try:
        file_size = filepath.stat().st_size
        max_chunk_size = 90 * 1024 * 1024
        total_chunks = (file_size + max_chunk_size - 1) // max_chunk_size

        # Calculate SHA-256 hash of the entire file
        file_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                file_hash.update(chunk)
        file_hash_hex = file_hash.hexdigest()

        logger.info(
            f"Uploading {filepath.name} in {total_chunks} chunk(s) ({file_size:,} bytes, hash: {file_hash_hex[:16]}...)"
        )

        upload_url = f"{backend_url.rstrip('/')}/api/v1/upload/chunked"
        headers = {"X-API-Key": api_key}

        upload_session_id = f"{filepath.name}_{int(time.time() * 1000)}"

        with open(filepath, "rb") as f:
            for chunk_index in range(total_chunks):
                chunk_start = chunk_index * max_chunk_size
                f.seek(chunk_start)
                chunk_data = f.read(max_chunk_size)

                if not chunk_data:
                    break

                max_retries = 3
                success = False

                for attempt in range(max_retries):
                    try:
                        files = {
                            "chunk": (
                                f"{filepath.name}_chunk_{chunk_index + 1}",
                                chunk_data,
                                "application/octet-stream",
                            )
                        }

                        params = {
                            "source_url": source_url,
                            "upload_session_id": upload_session_id,
                            "chunk_index": chunk_index + 1,
                            "total_chunks": total_chunks,
                            "original_filename": filepath.name,
                            "total_file_size": file_size,
                            "chunk_size": len(chunk_data),
                            "file_hash": file_hash_hex,
                        }

                        response = requests.post(
                            upload_url,
                            files=files,
                            params=params,
                            headers=headers,
                            timeout=600,
                        )

                        if response.status_code in [200, 201]:
                            if chunk_index + 1 == total_chunks:
                                try:
                                    result = response.json()
                                    if result.get("status") == "completed":
                                        logger.info(
                                            f"Upload completed: {filepath.name} -> {result.get('path')}"
                                        )
                                    else:
                                        logger.error(
                                            f"Final chunk uploaded but assembly failed: {result.get('message', 'Unknown error')}"
                                        )
                                        return False
                                except Exception:
                                    logger.warning(
                                        f"Final chunk uploaded but could not parse response for {filepath.name}"
                                    )

                            logger.info(
                                f"Uploaded chunk {chunk_index + 1}/{total_chunks} for {filepath.name}"
                            )
                            success = True
                            break
                        else:
                            logger.warning(
                                f"Chunk {chunk_index + 1}/{total_chunks} upload attempt {attempt + 1} failed: "
                                f"{response.status_code} - {response.text}"
                            )

                    except Exception as e:
                        logger.warning(
                            f"Chunk {chunk_index + 1} upload attempt {attempt + 1} error: {e}"
                        )

                    if attempt < max_retries - 1:
                        time.sleep(1)

                if not success:
                    logger.error(
                        f"Failed to upload chunk {chunk_index + 1} after {max_retries} attempts"
                    )
                    return False

        logger.info(f"Successfully uploaded all chunks for {filepath.name}")
        return True

    except Exception as e:
        logger.error(f"Upload error for {filepath.name}: {e}")
        return False


def main() -> int:
    logger = setup_logging()
    logger.info("=" * 60)
    logger.info(f"Cron sync started at {datetime.now().isoformat()}")

    backend_url = os.environ.get("BACKEND_URL") or settings.FRONTEND_URL.replace(":5173", ":8000")
    api_key = settings.SERVICE_API_KEY

    if not backend_url:
        logger.error("BACKEND_URL environment variable is required")
        return 1

    session = get_session()

    success_count = 0
    error_count = 0

    with tempfile.TemporaryDirectory():
        temp_path = Path("/root/someshit")

        for i, source_url in enumerate(SOURCES, 1):
            logger.info(f"[{i}/{len(SOURCES)}] Processing: {source_url}")

            if i > 1:
                delay = random.uniform(2.0, 5.0)
                time.sleep(delay)

            download_url = get_download_link(source_url, session, logger)
            if not download_url:
                error_count += 1
                continue

            time.sleep(random.uniform(0.5, 1.5))

            filepath, filename = download_file(download_url, session, temp_path, logger)
            if not filepath:
                error_count += 1
                continue

            if upload_file(filepath, source_url, backend_url, api_key, logger):
                success_count += 1
            else:
                error_count += 1

            try:
                filepath.unlink()
            except Exception:
                pass

    logger.info(f"Completed: {success_count} successful, {error_count} errors")
    logger.info("=" * 60)

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
