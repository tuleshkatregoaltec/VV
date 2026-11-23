"""Render one fixed document template to PDF (synchronous; callers run it in a worker thread).

Input values are escaped text. The renderer loads nothing but files bundled in
`document_templates/`: no remote URLs, no other local files, no scripts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError

from app.crm.document_templates import TEMPLATES

TEMPLATE_DIR = Path(__file__).parent / "document_templates"


class RenderError(Exception):
    """The document could not be rendered (bad template input or renderer failure)."""


def _allow_homebrew_libraries() -> None:
    """On macOS hosts, find Pango from Homebrew (not on dyld's default search path).

    `uv run` drops DYLD_* variables, so WeasyPrint's bare-name library lookups fail there.
    Production (Linux image) never takes this path.
    """
    import cffi

    original = cffi.FFI.dlopen
    if getattr(original, "_homebrew_fallback", False):
        return

    def dlopen(self, name, flags=0):
        try:
            return original(self, name, flags)
        except OSError:
            if isinstance(name, str) and name.endswith(".dylib") and "/" not in name:
                for prefix in (
                    os.environ.get("HOMEBREW_PREFIX"),
                    "/opt/homebrew",
                    "/usr/local",
                    "/opt/local",
                ):
                    path = Path(prefix or "") / "lib" / name
                    if prefix and path.exists():
                        return original(self, str(path), flags)
            raise

    dlopen._homebrew_fallback = True  # type: ignore[attr-defined]
    cffi.FFI.dlopen = dlopen


if sys.platform == "darwin":
    _allow_homebrew_libraries()

_jinja = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
    undefined=StrictUndefined,
)


def _fetch_bundled(url: str) -> Any:
    """Serve a file from the template directory; refuse every other URL."""
    parsed = urlparse(url)
    if parsed.scheme != "file":
        raise RenderError("Only bundled template assets can be loaded")
    path = Path(unquote(parsed.path)).resolve()
    if not path.is_relative_to(TEMPLATE_DIR.resolve()) or not path.is_file():
        raise RenderError("Only bundled template assets can be loaded")
    from weasyprint.urls import URLFetcherResponse

    return URLFetcherResponse(url, body=path.read_bytes())


def render_pdf(doc_type: str, snapshot: dict[str, Any]) -> bytes:
    spec = TEMPLATES[doc_type]
    try:
        html = _jinja.get_template(spec.file).render(
            spec=spec, draft=spec.version.startswith("draft"), **snapshot
        )
    except TemplateError as exc:
        raise RenderError(f"Template {spec.file} could not be filled") from exc
    try:
        from weasyprint import HTML
        from weasyprint.urls import URLFetcher
    except (ImportError, OSError) as exc:
        raise RenderError(
            "PDF rendering requires WeasyPrint's system libraries, including Pango"
        ) from exc

    class _BundledOnly(URLFetcher):
        def fetch(self, url, headers=None):
            return _fetch_bundled(url)

    try:
        return HTML(
            string=html, base_url=TEMPLATE_DIR.as_uri() + "/", url_fetcher=_BundledOnly()
        ).write_pdf()
    except Exception as exc:
        raise RenderError("PDF rendering failed") from exc
