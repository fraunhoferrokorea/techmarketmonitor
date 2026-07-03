from __future__ import annotations

import logging
import os
import re
import zipfile
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
_PLAN_MAX_FILES = int(os.getenv("GOV_PLAN_ATTACHMENT_MAX_FILES", "3"))
_PLAN_MAX_CHARS = int(os.getenv("GOV_PLAN_ATTACHMENT_MAX_CHARS", "50000"))
_USER_AGENT = "TechMarketMonitor/1.0"

_MSIT_FILE_RE = re.compile(
    r"fn_download\('(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\w+)'\)",
    re.I,
)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_ATTACHMENT_EXT_RE = re.compile(r"\.(pdf|hwpx|hwp)(?:\?|$)", re.I)
_DOWNLOAD_HINT_RE = re.compile(r"download\.do|filedown\.do|filedown\.do", re.I)
_HWPX_TEXT_RE = re.compile(r"<hp:t[^>]*>(.*?)</hp:t>", re.S | re.I)


def discover_pdf_urls(html: str, page_url: str) -> list[str]:
    """Find PDF download URLs embedded in a government press-release page."""
    return discover_attachment_urls(html, page_url, include_hwpx=False)


def discover_attachment_urls(
    html: str,
    page_url: str,
    *,
    include_hwpx: bool = True,
) -> list[str]:
    """Find PDF/HWPX/HWP download URLs on government pages."""
    base = str(page_url)
    found: list[str] = []
    allowed_ext = {"pdf", "hwpx", "hwp"} if include_hwpx else {"pdf"}

    for atch_no, file_ord, ext in _MSIT_FILE_RE.findall(html):
        if ext.lower() not in allowed_ext:
            continue
        found.append(
            "https://www.msit.go.kr/ssm/file/fileDown.do"
            f"?atchFileNo={atch_no}&fileOrd={file_ord}"
        )

    for href in _HREF_RE.findall(html):
        link = unescape(href).strip()
        lower = link.lower()
        if not link or link.startswith("#") or link.startswith("javascript:"):
            continue
        if _ATTACHMENT_EXT_RE.search(lower) or _DOWNLOAD_HINT_RE.search(lower):
            found.append(urljoin(base, link))

    return list(dict.fromkeys(found))


def _looks_like_pdf(content: bytes, content_type: str, url: str) -> bool:
    ctype = (content_type or "").lower()
    if "pdf" in ctype:
        return True
    if content[:4] == b"%PDF":
        return True
    return url.lower().split("?")[0].endswith(".pdf")


def _looks_like_hwpx(content: bytes, content_type: str, url: str) -> bool:
    ctype = (content_type or "").lower()
    if "hwpx" in ctype or "zip" in ctype:
        return True
    if content[:2] == b"PK":
        return url.lower().split("?")[0].endswith(".hwpx")
    return url.lower().split("?")[0].endswith(".hwpx")


def extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(text)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def extract_hwpx_text(content: bytes) -> str:
    """Extract plain text from an HWPX (Office Open XML) document."""
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            parts: list[str] = []
            for name in sorted(archive.namelist()):
                if not name.startswith("Contents/") or not name.endswith(".xml"):
                    continue
                xml = archive.read(name).decode("utf-8", errors="replace")
                for match in _HWPX_TEXT_RE.findall(xml):
                    cleaned = re.sub(r"<[^>]+>", " ", match)
                    cleaned = unescape(cleaned).strip()
                    if cleaned:
                        parts.append(cleaned)
            return re.sub(r"\s+", " ", " ".join(parts)).strip()
    except zipfile.BadZipFile:
        return ""


def extract_attachment_text(content: bytes, content_type: str, url: str) -> str:
    if _looks_like_pdf(content, content_type, url):
        return extract_pdf_text(content)
    if _looks_like_hwpx(content, content_type, url):
        return extract_hwpx_text(content)
    return ""


def extract_pdf_from_path(path: Path) -> str:
    return extract_pdf_text(path.read_bytes())


def fetch_pdf_texts(urls: list[str], max_files: int = _MAX_PDF_FILES) -> list[str]:
    """Download PDF attachments and return extracted plain text."""
    return fetch_attachment_texts(urls, max_files=max_files, max_chars=_MAX_PDF_CHARS)


def fetch_attachment_texts(
    urls: list[str],
    *,
    max_files: int = _MAX_PDF_FILES,
    max_chars: int = _MAX_PDF_CHARS,
) -> list[str]:
    """Download PDF/HWPX attachments and return extracted plain text."""
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
            logger.debug("Attachment download failed (%s): %s", url, exc)
            continue

        text = extract_attachment_text(
            response.content,
            response.headers.get("content-type", ""),
            url,
        )
        if not text:
            logger.debug("Skipping unsupported or empty attachment: %s", url)
            continue

        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + "…"

        texts.append(text)
        logger.info("Extracted attachment text (%d chars): %s", len(text), url[:80])

    return texts


def fetch_plan_attachment_texts(urls: list[str]) -> list[str]:
    """Fetch full plan/document attachments (higher file and char limits)."""
    return fetch_attachment_texts(
        urls,
        max_files=_PLAN_MAX_FILES,
        max_chars=_PLAN_MAX_CHARS,
    )
