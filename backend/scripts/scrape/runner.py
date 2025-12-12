"""File downloader runner with incremental updates and anti-blocking measures."""

import logging
import random
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from urllib.parse import urljoin

from .config import (
    FileMetadata,
    calculate_file_hash,
    get_data_paths,
    get_sources_file,
    load_metadata,
    save_metadata,
)


# Realistic user agents to rotate between
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def get_session() -> requests.Session:
    """Create a session with realistic browser headers."""
    session = requests.Session()

    # Set realistic headers that mimic a real browser
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


def random_delay(min_seconds: float = 1.0, max_seconds: float = 3.0):
    """Add a random delay to mimic human behavior."""
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)


def setup_logging(log_dir: Path | None = None) -> logging.Logger:
    """Configure file and console logging."""
    if log_dir is None:
        # backend/scripts/scrape -> backend/scripts/scrape/../../../logs
        script_dir = Path(__file__).parent
        project_root = script_dir.parent.parent.parent
        log_dir = project_root / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("downloader")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fh = logging.FileHandler(
        log_dir / f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def get_download_link(
    page_url: str, session: requests.Session, logger: logging.Logger
) -> str | None:
    """Extract download link from page by finding action-icon-anchor element."""
    try:
        response = session.get(page_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        download_anchor = soup.find("a", class_="action-icon-anchor", href=True)

        if download_anchor:
            download_url = str(download_anchor["href"])
            return urljoin(page_url, download_url)
        else:
            logger.error(f"  ✗ Download link not found on page")
            return None
    except Exception as e:
        logger.error(f"  ✗ Failed to fetch page: {e}")
        return None


def download_file(
    url: str, output_dir: Path, session: requests.Session, logger: logging.Logger
) -> tuple[bool, Path | None]:
    """Download file from URL to output directory with progress bar. Returns (success, filepath)."""
    try:
        response = session.get(url, stream=True, timeout=60)
        response.raise_for_status()

        # Extract filename from URL or Content-Disposition header
        filename = url.split("/")[-1].split("?")[0]
        if "Content-Disposition" in response.headers:
            content_disp = response.headers["Content-Disposition"]
            if "filename=" in content_disp:
                filename = content_disp.split("filename=")[1].strip('"')

        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / filename

        # Get total file size (may not be available)
        total_size = int(response.headers.get("content-length", 0))

        # Download with progress bar
        if total_size > 0:
            # Known size - show percentage progress
            with (
                open(filepath, "wb") as f,
                tqdm(
                    desc=f"  {filename}",
                    total=total_size,
                    unit="iB",
                    unit_scale=True,
                    unit_divisor=1024,
                    bar_format="{desc}: {percentage:3.0f}%|{bar:30}| {n_fmt}/{total_fmt} [{rate_fmt}]",
                ) as progress_bar,
            ):
                for chunk in response.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    progress_bar.update(size)
        else:
            # Unknown size - show bytes downloaded and speed only
            with (
                open(filepath, "wb") as f,
                tqdm(
                    desc=f"  {filename}",
                    unit="iB",
                    unit_scale=True,
                    unit_divisor=1024,
                    bar_format="{desc}: {n_fmt} [{rate_fmt}]",
                ) as progress_bar,
            ):
                for chunk in response.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    progress_bar.update(size)

        file_size = filepath.stat().st_size
        logger.info(f"  ✓ Downloaded: {filename} ({file_size:,} bytes)")
        return True, filepath
    except Exception as e:
        logger.error(f"  ✗ Download failed: {e}")
        return False, None


def archive_previous_file(
    current_file: Path, previous_dir: Path, logger: logging.Logger
):
    """Move current file to previous directory, deleting old version if exists."""
    try:
        previous_dir.mkdir(parents=True, exist_ok=True)
        previous_file = previous_dir / current_file.name

        # Delete old version in previous if it exists
        if previous_file.exists():
            previous_file.unlink()
            logger.info(f"  Removed old version from previous/")

        # Move current to previous
        shutil.move(str(current_file), str(previous_file))
        logger.info(f"  Archived to previous/: {current_file.name}")
    except Exception as e:
        logger.error(f"  ✗ Failed to archive file: {e}")


def load_sources(sources_file: Path, logger: logging.Logger) -> list[str]:
    """Load source URLs from file."""
    try:
        with open(sources_file, "r") as f:
            urls = [line.strip() for line in f if line.strip()]
        return urls
    except FileNotFoundError:
        logger.error(f"  ✗ Sources file not found: {sources_file}")
        return []
    except Exception as e:
        logger.error(f"  ✗ Error reading sources file: {e}")
        return []


def run_downloader(
    sources_file: Path | None = None,
    data_dir: Path | None = None,
    log_dir: Path | None = None,
    test_mode: bool = False,
) -> dict:
    """Run the incremental file downloader pipeline."""
    logger = setup_logging(log_dir)
    logger.info("=" * 70 + "\nIncremental File Downloader\n" + "=" * 70)

    # Set defaults
    if sources_file is None:
        sources_file = get_sources_file()

    current_dir, previous_dir = get_data_paths(data_dir)
    metadata_file = current_dir.parent / "metadata.json"

    # In test mode, use a separate test directory
    if test_mode:
        test_dir = current_dir.parent / "test"
        current_dir = test_dir / "current"
        previous_dir = test_dir / "previous"
        logger.info(f"🧪 TEST MODE: Using temporary test directory")
        logger.info(f"Sources:  {sources_file}\nTest dir: {test_dir}")
    else:
        logger.info(
            f"Sources:  {sources_file}\nCurrent:  {current_dir}\nPrevious: {previous_dir}"
        )

    # Load source URLs and previous metadata
    urls = load_sources(sources_file, logger)
    if not urls:
        logger.error("  ✗ No valid URLs found")
        return {"success": False, "error": "No URLs to process"}

    # Test mode: only process third file (index 2, areas)
    if test_mode:
        if len(urls) < 3:
            logger.error(f"  ✗ Test mode requires at least 3 URLs, found {len(urls)}")
            return {"success": False, "error": "Not enough URLs for test mode"}
        urls = [urls[2]]  # Third line (index 2)
        logger.info(f"Processing: 1 file (areas - line 3)\n")
    else:
        logger.info(f"Found {len(urls)} source(s)\n")

    previous_metadata = load_metadata(metadata_file)

    # Create session with browser-like headers
    session = get_session()
    logger.debug(f"Using User-Agent: {session.headers['User-Agent']}")

    start = time.time()
    results = []
    new_metadata = {}

    for i, page_url in enumerate(urls, 1):
        logger.info(f"{'─' * 60}\n[{i}/{len(urls)}] {page_url}\n{'─' * 60}")

        result = {
            "url": page_url,
            "status": "error",
            "action": None,
            "error": None,
        }

        # Add random delay between requests to mimic human behavior
        if i > 1:
            delay = random.uniform(2.0, 5.0)
            logger.debug(f"  Waiting {delay:.1f}s before next request...")
            time.sleep(delay)

        # Extract download link
        download_url = get_download_link(page_url, session, logger)
        if not download_url:
            result["error"] = "Download link not found"
            results.append(result)
            continue

        logger.info(f"  Found: {download_url}")

        # Check if this is a new/changed file
        prev_meta = previous_metadata.get(page_url)
        if prev_meta and prev_meta.download_url == download_url:
            logger.info(f"  ✓ No change detected (same download URL)")
            result["status"] = "unchanged"
            result["action"] = "skipped"
            new_metadata[page_url] = prev_meta
            results.append(result)
            continue

        # Small delay before downloading
        random_delay(0.5, 1.5)

        # Download new file
        success, filepath = download_file(download_url, current_dir, session, logger)
        if not success or filepath is None:
            result["error"] = "Download failed"
            results.append(result)
            continue

        # Calculate file hash and size
        file_hash = calculate_file_hash(filepath)
        file_size = filepath.stat().st_size

        # Archive previous version if exists (skip in test mode)
        if not test_mode and prev_meta:
            old_file = current_dir / prev_meta.filename
            if old_file.exists() and old_file != filepath:
                archive_previous_file(old_file, previous_dir, logger)
                result["action"] = "updated"
            else:
                result["action"] = "new"
        else:
            result["action"] = "new"

        # Save metadata
        new_metadata[page_url] = FileMetadata(
            source_url=page_url,
            filename=filepath.name,
            download_url=download_url,
            downloaded_at=datetime.now().isoformat(),
            file_hash=file_hash,
            file_size=file_size,
        )

        result["status"] = "success"
        logger.info(f"  Hash: {file_hash[:16]}... ({file_size:,} bytes)")
        results.append(result)

    # Save metadata only if not in test mode
    if test_mode:
        logger.info(f"\n  ⚠️  Test mode: Files saved to {current_dir}")
        logger.info(f"             Metadata NOT saved (test directory is temporary)")
    else:
        save_metadata(metadata_file, new_metadata)
        logger.info(f"\n  Saved metadata: {metadata_file}")

    elapsed = time.time() - start
    new_count = sum(1 for r in results if r.get("action") == "new")
    updated_count = sum(1 for r in results if r.get("action") == "updated")
    unchanged_count = sum(1 for r in results if r.get("action") == "skipped")
    error_count = sum(1 for r in results if r["status"] == "error")

    logger.info(f"\n{'=' * 70}\nDownload Complete\n{'=' * 70}")
    logger.info(
        f"  New: {new_count}\n  Updated: {updated_count}\n  Unchanged: {unchanged_count}\n  Errors: {error_count}\n  Time: {elapsed:.1f}s"
    )

    return {
        "success": error_count == 0,
        "elapsed": elapsed,
        "new_count": new_count,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "error_count": error_count,
        "results": results,
    }


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Incremental File Downloader")
    parser.add_argument(
        "--sources", "-s", type=Path, help="Sources file (default: ./sources.txt)"
    )
    parser.add_argument(
        "--data-dir",
        "-d",
        type=Path,
        help="Data directory (default: <project_root>/data)",
    )
    parser.add_argument(
        "--log-dir",
        "-l",
        type=Path,
        help="Log directory (default: <project_root>/logs)",
    )
    parser.add_argument(
        "--test",
        "-t",
        action="store_true",
        help="Test mode: download to data/test/, process only areas file (line 3)",
    )
    args = parser.parse_args()

    result = run_downloader(
        sources_file=args.sources,
        data_dir=args.data_dir,
        log_dir=args.log_dir,
        test_mode=args.test,
    )
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
