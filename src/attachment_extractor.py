from __future__ import annotations

import logging
import re
from html import unescape
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import httpx
from pypdf import PdfReader

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0
_MAX_PDF_FILES = 2
_MAX_PDF_CHARS = 6000
_USER_AGENT = "TechMarketMonitor/1.0"

_MSIT_FILE_RE = re.compile(
    r"fn_download\('(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\w+)'\)",
    re.I,
)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def discover_pdf_urls(html: str, page_url: str) -> list[str]:
    """Find PDF download URLs embedded in a government press-release page."""
    base = str(page_url)
    found: list[str] = []

    for atch_no, file_ord, ext in _MSIT_FILE_RE.findall(html):
        if ext.lower() != "pdf":
            continue
        found.append(
            f"https://www.msit.go.kr/ssm/file/fileDown.do"
            f"?atchFileNo={atch_no}&fileOrd={file_ord}"
        )

    for href in _HREF_RE.findall(html):
        link = unescape(href).strip()
        lower = link.lower()
        if not link or link.startswith("#") or link.startswith("javascript:"):
            continue
        if ".pdf" in lower or "download.do" in lower or "filedown.do" in lower:
            found.append(urljoin(base, link))

    # Preserve order, drop duplicates.
    return list(dict.fromkeys(found))


def _looks_like_pdf(content: bytes, content_type: str, url: str) -> bool:
    ctype = (content_type or "").lower()
    if "pdf" in ctype:
        return True
    if content[:4] == b"%PDF":
        return True
    return url.lower().split("?")[0].endswith(".pdf")


def extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(text)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def extract_pdf_from_path(path: Path) -> str:
    return extract_pdf_text(path.read_bytes())


def fetch_pdf_texts(urls: list[str], max_files: int = _MAX_PDF_FILES) -> list[str]:
    """Download PDF attachments and return extracted plain text."""
    texts: list[str] = []
    for url in urls[:max_files]:
        try:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=_TIMEOUT,
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
        except Exception as exc:
            logger.debug("PDF download failed (%s): %s", url, exc)
            continue

        if not _looks_like_pdf(response.content, response.headers.get("content-type", ""), url):
            logger.debug("Skipping non-PDF attachment: %s", url)
            continue

        try:
            text = extract_pdf_text(response.content)
        except Exception as exc:
            logger.debug("PDF parse failed (%s): %s", url, exc)
            continue

        if not text:
            continue

        if len(text) > _MAX_PDF_CHARS:
            text = text[:_MAX_PDF_CHARS].rsplit(" ", 1)[0] + "…"

        texts.append(text)
        logger.info("Extracted PDF text (%d chars): %s", len(text), url[:80])

    return texts
