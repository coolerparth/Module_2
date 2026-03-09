from __future__ import annotations

import asyncio
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests

from ..constants import HEAD_BLOCKED_CODES, MAX_RETRIES, URL_EXECUTOR_WORKERS, URL_HEADERS, URL_TIMEOUT
from ..result import ResultNode, fail, ok

__all__ = ["validate_url_async"]

log = logging.getLogger(__name__)

_executor: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=URL_EXECUTOR_WORKERS, thread_name_prefix="url_check")
        atexit.register(_executor.shutdown, wait=True)
    return _executor


def _sync_fetch(url: str, label: str) -> ResultNode:
    for attempt in range(1 + MAX_RETRIES):
        try:
            with requests.head(
                url,
                timeout=URL_TIMEOUT,
                allow_redirects=True,
                headers=URL_HEADERS,
            ) as resp:
                status = resp.status_code

            if status in HEAD_BLOCKED_CODES:
                with requests.get(
                    url,
                    timeout=URL_TIMEOUT,
                    allow_redirects=True,
                    headers=URL_HEADERS,
                    stream=True,
                ) as resp2:
                    status = resp2.status_code

            if status < 400:
                return ok(url, note=f"Reachable — HTTP {status}.")
            return fail(url, f"{label} returned HTTP {status} — dead or broken link.")

        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                log.warning("[%s] Timeout on attempt %d — retrying...", label, attempt + 1)
                continue
            return fail(url, f"{label} timed out after {URL_TIMEOUT}s — server unreachable.")

        except requests.exceptions.SSLError as exc:
            return fail(url, f"{label} SSL/TLS error — {exc}.")

        except requests.exceptions.ConnectionError as exc:
            if attempt < MAX_RETRIES:
                log.warning("[%s] Connection error on attempt %d — retrying...", label, attempt + 1)
                continue
            return fail(url, f"{label} connection failed — {exc}.")

        except requests.exceptions.RequestException as exc:
            return fail(url, f"{label} request failed — {exc}.")

    return fail(url, f"{label} could not be verified after {1 + MAX_RETRIES} attempt(s).")


async def validate_url_async(url: str | None, label: str) -> ResultNode:
    if not url or not url.strip():
        return ok(None, note=f"{label} not provided — optional field.")

    u = url.strip()
    if not u.startswith(("http://", "https://")):
        return fail(u, f"{label}: URL '{u}' must begin with http:// or https://.")

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), _sync_fetch, u, label)
