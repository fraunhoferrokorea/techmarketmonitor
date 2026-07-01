from __future__ import annotations

import json
import logging
import os
import re
import time

from openai import RateLimitError

logger = logging.getLogger(__name__)

REQUEST_DELAY = float(os.getenv("SUMMARIZER_REQUEST_DELAY", "1.0"))
MAX_RETRIES = 5
_TPD_WAIT_RE = re.compile(r"try again in (\d+)m([\d.]+)s", re.I)


def extract_json(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def is_tpd_rate_limit(exc: RateLimitError) -> bool:
    msg = str(exc).lower()
    return "tokens per day" in msg or "tpd" in msg


def sleep_for_tpd_limit(exc: RateLimitError) -> None:
    match = _TPD_WAIT_RE.search(str(exc))
    if match:
        wait = int(match.group(1)) * 60 + float(match.group(2)) + 10
    else:
        wait = 180.0
    logger.warning("Groq TPD limit — waiting %.0fs before retry", wait)
    time.sleep(wait)
