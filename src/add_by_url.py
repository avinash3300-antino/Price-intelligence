"""Manual URL-paste flow: fetch a seller PDP with plain httpx, strip to text,
extract one competitor option, and adjudicate whether it's a like-for-like
match for the given Rayna option.

Design constraint (per project owner): free-only scraping. No Firecrawl, no
Playwright. Direct HTTP fetch with browser-like headers. If a seller blocks
us (Cloudflare, JS-only, etc.), the UI falls back to user-pasted raw text.
Only cost is Claude API.

This module is stateless. The backend endpoint owns DB writes + the 409
same-seller-per-Rayna constraint.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx
from anthropic import Anthropic

from src import config, map_options
from src.models import ExtractedOption

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
FETCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
FETCH_TIMEOUT_S = 30
MIN_CONTENT_CHARS = 500  # below this we assume the fetch was blocked / thin


def normalize_seller_domain(url: str) -> str:
    """`https://www.viator.com/tours/...` -> `viator.com`."""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


# ---------- Stdlib HTML -> plain text ----------


class _TextExtractor(HTMLParser):
    """Accumulate visible text, skipping <script>/<style>/<noscript>/<template>."""

    SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
    BLOCK_TAGS = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "nav", "hr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._title_capture = False
        self.title: str | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:  # noqa: ARG002
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._title_capture = True
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._title_capture = False
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._title_capture and self.title is None:
            self.title = data.strip() or None
            return
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)
            self._parts.append(" ")

    def text(self) -> str:
        raw = "".join(self._parts)
        # Collapse runs of whitespace but keep paragraph breaks.
        lines = [ln.strip() for ln in raw.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)


def html_to_text(html: str) -> tuple[str, str | None]:
    """Return (plain_text, title). Stdlib only."""
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001
        # Malformed HTML — return whatever we accumulated
        pass
    return p.text(), p.title


# ---------- Free fetch ----------


class FetchBlockedError(RuntimeError):
    """The seller blocked or returned too-thin content; UI should offer paste-text fallback."""


def _fetch_with_httpx(url: str) -> tuple[int, str]:
    """Plain httpx fetch. Returns (status_code, body_text)."""
    r = httpx.get(
        url,
        headers=FETCH_HEADERS,
        follow_redirects=True,
        timeout=FETCH_TIMEOUT_S,
    )
    return r.status_code, r.text


def _fetch_with_curl_cffi(url: str) -> tuple[int, str] | None:
    """Retry via curl-cffi with a Chrome TLS fingerprint. Bypasses most
    Cloudflare / anti-bot fingerprinting that catches vanilla httpx.
    Returns None if the library isn't installed (never should happen since
    it's in requirements)."""
    try:
        from curl_cffi import requests as cffi_requests  # type: ignore
    except ImportError:
        return None
    r = cffi_requests.get(
        url,
        headers=FETCH_HEADERS,
        impersonate="chrome",  # picks a recent Chrome JA3
        timeout=FETCH_TIMEOUT_S,
        allow_redirects=True,
    )
    return int(r.status_code), r.text


def fetch_url_as_text(url: str) -> tuple[str, str | None]:
    """Return (plain_text, title). Raises FetchBlockedError if we couldn't
    get real content — the caller should ask the user to paste page text
    manually instead.

    Strategy: try plain httpx first (fast, cheap). If that gets blocked
    (4xx/5xx or too-thin body), retry via curl-cffi with a Chrome TLS
    fingerprint — this bypasses Cloudflare on many OTAs (Viator, etc.)
    where vanilla httpx is instantly flagged.
    """
    status: int = 0
    body: str = ""
    fetch_err: Exception | None = None

    # Stage 1: httpx
    try:
        status, body = _fetch_with_httpx(url)
    except httpx.HTTPError as e:
        fetch_err = e

    needs_fallback = (
        fetch_err is not None
        or status >= 400
        or len(html_to_text(body)[0]) < MIN_CONTENT_CHARS
    )

    # Stage 2: curl-cffi (Chrome-impersonated TLS)
    if needs_fallback:
        try:
            fallback = _fetch_with_curl_cffi(url)
        except Exception as e:  # noqa: BLE001
            fallback = None
            fetch_err = e
        if fallback is not None:
            status, body = fallback
            fetch_err = None

    if fetch_err is not None and not body:
        raise FetchBlockedError(
            f"Could not reach {url}: {type(fetch_err).__name__}. "
            "Paste the page content manually instead."
        )
    if status >= 400:
        raise FetchBlockedError(
            f"{url} returned HTTP {status}. Likely blocking automated fetch — "
            "paste the page content manually instead."
        )

    text, title = html_to_text(body)
    if len(text) < MIN_CONTENT_CHARS:
        raise FetchBlockedError(
            f"Only got {len(text)} characters of readable content — the seller likely "
            "needs JavaScript to render. Paste the page content manually instead."
        )
    return text, title


# ---------- Claude: extract one competitor option from text ----------

_EXTRACT_SYSTEM = """You are extracting a single bookable OPTION from a scraped seller \
product page.

Return exactly ONE option — the primary / most-representative variant on the page. \
If the page shows multiple variants (e.g. "with transfer" vs "without transfer"), pick \
the one whose price is most prominently displayed. Do NOT invent options that aren't \
in the text.

Fingerprint rules (same as the rest of the pipeline):

1. `pricing_basis`: per_adult, per_child, private_group, per_vehicle, per_boat, \
per_yacht, or unknown. Most attraction tickets and SIC tours are per_adult.

2. Extract `inclusions` and `exclusions` as short atomic items when the page lists them.

3. `highlights` are marketing bullets ("Skip the line", "Sunset views"). Distinct \
from inclusions.

4. `duration_minutes`: convert cleanly-numeric durations. Use `duration_label` when \
the source string is ambiguous (e.g. "half day").

5. `cancellation_window_hours`: e.g. "Free cancellation up to 24 hours prior" -> 24. \
For non-refundable, leave null and mention in `notes`.

6. `transfer_included` / `meal_included`: only set true/false if explicit.

7. If a field isn't stated on the page, leave it empty. Don't invent.

8. Output ONLY via the `record_option` tool."""


_EXTRACT_USER_TEMPLATE = """SELLER URL: {url}
PAGE TITLE: {title}

PAGE CONTENT (trimmed):
{content}

Extract the single primary bookable option. Use the `record_option` tool."""


def _extract_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "record_option",
            "description": "Record the single primary option extracted from this seller page.",
            "input_schema": ExtractedOption.model_json_schema(),
        }
    ]


def extract_competitor_option(
    client: Anthropic,
    content: str,
    url: str,
    page_title: str | None,
) -> ExtractedOption:
    """Claude extracts one ExtractedOption from raw text (fetched OR pasted)."""
    trimmed = content.strip()
    if len(trimmed) > 32000:
        trimmed = trimmed[:32000]

    user_text = _EXTRACT_USER_TEMPLATE.format(
        url=url,
        title=page_title or "(none)",
        content=trimmed,
    )

    resp = client.messages.create(
        model=config.CLAUDE_ADJUDICATOR_MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _EXTRACT_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=_extract_tools(),
        tool_choice={"type": "tool", "name": "record_option"},
        messages=[{"role": "user", "content": user_text}],
    )

    tool_blocks = [
        b for b in resp.content if b.type == "tool_use" and b.name == "record_option"
    ]
    if not tool_blocks:
        raise RuntimeError(
            f"Claude did not call record_option; stop_reason={resp.stop_reason}"
        )

    raw = dict(tool_blocks[0].input)
    fp = raw.get("fingerprint")
    if isinstance(fp, dict):
        for k, v in list(fp.items()):
            if v == "":
                fp[k] = None
        raw["fingerprint"] = fp
    return ExtractedOption.model_validate(raw)


# ---------- Claude: adjudicate the pair ----------


def adjudicate_pair(
    client: Anthropic,
    rayna_option_row: dict[str, Any],
    competitor_option: dict[str, Any],
    anchor_product: dict[str, Any],
    seller_domain: str,
):
    """Reuses :func:`src.map_options.adjudicate` verbatim so URL-paste lands
    the exact same verdict/confidence/diff_notes as the auto-pipeline."""
    tools = map_options.build_tools()
    return map_options.adjudicate(
        client,
        anchor_product,
        rayna_option_row,
        competitor_option,
        seller_domain,
        tools,
    )
