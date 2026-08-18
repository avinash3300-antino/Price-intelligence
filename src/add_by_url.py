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
from src.models import ExtractedOption, ExtractionResult

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


# ---------- JS-heavy OTA domains ----------
#
# These sellers render per-variant prices client-side (React/Vue hydration).
# httpx/curl-cffi return a rich-looking HTML shell that passes the thin-body
# check, but the option-level prices aren't in the raw markup — Claude ends
# up extracting the option names correctly but leaves price=null for the
# add-on variants.
#
# For these hosts we skip the fast fetchers entirely and jump to the
# JS-rendering path (Playwright → Firecrawl).
_JS_HEAVY_DOMAINS: set[str] = {
    "getyourguide.com",
    "klook.com",
    "viator.com",
    "tiqets.com",
    "musement.com",
    "headout.com",
    "civitatis.com",
    "tripadvisor.com",
}


def _needs_js_render(url: str) -> bool:
    """True when the URL's host (or any parent domain) is on the JS-heavy list."""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return False
    # Match on the eTLD+1 by walking parent domains — catches
    # `ticket.getyourguide.com` etc.
    parts = host.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in _JS_HEAVY_DOMAINS:
            return True
    return False


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


PLAYWRIGHT_TIMEOUT_MS = 60000  # 60s covers Cloudflare's slower challenges


# Bundle of stealth patches that null out the tells Cloudflare/DataDome/
# PerimeterX probe. Applied once before every page navigation. This is a
# hand-rolled subset of the popular playwright-stealth patches — enough
# to pass Viator / GetYourGuide's default bot-management level.
_STEALTH_INIT_SCRIPT = r"""
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
if (!window.chrome) {
    window.chrome = { runtime: {}, loadTimes: () => ({}), csi: () => ({}) };
}
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'PDF Viewer', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer' },
        { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer' },
    ],
});
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(parameters);
}
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
"""


def _fetch_with_playwright(url: str) -> tuple[int, str] | None:
    """Third fallback: real headless Chromium via Playwright, with stealth
    patches to defeat Cloudflare's JS challenge. Used for Viator,
    GetYourGuide, Klook and other JS-gated OTAs.

    Cost: ~5-15s per fetch (browser startup + Cloudflare challenge solve).
    Requires `pip install playwright && playwright install chromium`.
    Returns None if the library or the browser binary isn't available —
    the caller then surfaces FetchBlockedError so the UI shows the
    paste-text textarea fallback.

    Wait strategy: navigate, wait for `domcontentloaded`, then poll for
    real content (body text length > 500 chars). Cloudflare's challenge
    page has almost no visible text, so this filters challenge pages out
    without needing to detect the specific challenge markup.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    locale="en-US",
                    timezone_id="Asia/Dubai",
                    viewport={"width": 1440, "height": 900},
                    java_script_enabled=True,
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": (
                            "text/html,application/xhtml+xml,application/xml;q=0.9,"
                            "image/avif,image/webp,image/apng,*/*;q=0.8"
                        ),
                        "Sec-Ch-Ua": '"Chromium";v="120", "Not:A-Brand";v="24"',
                        "Sec-Ch-Ua-Mobile": "?0",
                        "Sec-Ch-Ua-Platform": '"macOS"',
                        "Upgrade-Insecure-Requests": "1",
                    },
                )
                context.add_init_script(_STEALTH_INIT_SCRIPT)
                page = context.new_page()

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=PLAYWRIGHT_TIMEOUT_MS,
                )

                # Poll for real content. Cloudflare challenge pages have
                # tiny body text (< 500 chars); real product pages are
                # thousands of chars. If we never cross the threshold
                # within ~25s, give up and let the caller show the paste
                # fallback rather than returning junk to Claude.
                deadline_ms = 25000
                interval_ms = 750
                elapsed = 0
                content_len = 0
                while elapsed < deadline_ms:
                    try:
                        content_len = int(
                            page.evaluate("() => document.body.innerText.length")
                        )
                    except Exception:  # noqa: BLE001
                        content_len = 0
                    if content_len >= MIN_CONTENT_CHARS:
                        break
                    page.wait_for_timeout(interval_ms)
                    elapsed += interval_ms

                # One more small settle so lazy-loaded price/description
                # blocks land in the DOM before we snapshot.
                page.wait_for_timeout(1200)
                html = page.content()

                # HTTP status hint — Playwright doesn't cleanly surface
                # the final navigation status; treat any body with > 0
                # chars as 200 and let the downstream length check reject
                # anything that came back thin.
                return 200, html
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        # Any Playwright-side failure (browser not installed, launch failure,
        # navigation timeout) collapses to None so the outer chain raises
        # FetchBlockedError and the UI shows the paste-text fallback.
        print(f"[add_by_url] playwright fallback failed for {url}: {type(e).__name__}: {e}")
        return None


FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"
FIRECRAWL_TIMEOUT_S = 120  # covers a 60s server-side timeout + queue/network


def _canonicalize_for_firecrawl(url: str) -> str:
    """Some sellers serve a JS-only redirect on the bare URL that Firecrawl's
    engines can't follow (SCRAPE_ALL_ENGINES_FAILED). We know a few of these
    up front and rewrite the URL to a canonical form that Firecrawl scrapes
    reliably. This is applied only for stage-4 (Firecrawl) — the httpx /
    curl-cffi / Playwright stages either follow the redirect themselves or
    already work with the bare URL."""
    from urllib.parse import urlparse, urlunparse

    p = urlparse(url)
    host = (p.hostname or "").lower()

    # Klook: bare /activity/{id}-... redirects client-side to /en-XX/activity/
    # which Firecrawl can't handle. Inject en-AE so the scrape lands on the
    # UAE storefront and Klook quotes prices in AED — matches every Rayna
    # target in this project and avoids FX conversion in the gap display.
    if host == "www.klook.com" and p.path.startswith("/activity/"):
        return urlunparse(p._replace(path=f"/en-AE{p.path}"))

    return url


def _fetch_with_firecrawl(url: str) -> tuple[int, str] | None:
    """Fourth fallback: Firecrawl API. Their infrastructure runs real
    residential-fingerprinted browsers with maintained anti-bot patches,
    so it clears Cloudflare on sites (Viator, GetYourGuide, Klook) where
    our DIY Playwright still gets a 403.

    Cost: ~1 API credit per URL (500/mo on the free tier at zero cost;
    $19/mo for 3,000/mo above that). Latency ~3-10s. Reuses the existing
    FIRECRAWL_KEY that the ingest pipeline (src/scrape_competitors.py)
    already uses — no new secret to provision.

    Returns None if the key isn't set or the call errors — the outer
    chain then surfaces FetchBlockedError and the UI shows the
    paste-text fallback."""
    if not getattr(config, "FIRECRAWL_KEY", None):
        return None
    target = _canonicalize_for_firecrawl(url)
    if target != url:
        print(f"[add_by_url] firecrawl canonicalised {url} -> {target}")
    try:
        r = httpx.post(
            FIRECRAWL_ENDPOINT,
            headers={
                "Authorization": f"Bearer {config.FIRECRAWL_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "url": target,
                "formats": ["markdown"],
                # OTAs (Klook, GYG) put the package picker in a sidebar or
                # slide-out modal that Firecrawl's onlyMainContent heuristic
                # strips out. Keep the full page — Claude filters the noise.
                "onlyMainContent": False,
                # Heavy OTA pages (Klook, GYG package pickers) take longer
                # than Firecrawl's 30s default. Give them up to 60s to
                # render before Firecrawl gives up.
                "timeout": 60000,
                "waitFor": 3000,
            },
            # Client-side wait must exceed Firecrawl-side timeout + a buffer
            # for their queue and our network round-trip.
            timeout=FIRECRAWL_TIMEOUT_S,
        )
    except httpx.HTTPError as e:
        print(f"[add_by_url] firecrawl transport error for {url}: {type(e).__name__}: {e}")
        return None
    if r.status_code >= 400:
        print(f"[add_by_url] firecrawl HTTP {r.status_code} for {url}: {r.text[:200]}")
        return None
    try:
        payload = r.json()
    except ValueError:
        print(f"[add_by_url] firecrawl non-JSON response for {url}: {r.text[:200]}")
        return None
    if not payload.get("success"):
        print(f"[add_by_url] firecrawl success=false for {url}: {payload.get('error')}")
        return None
    data = payload.get("data") or {}
    md = data.get("markdown") or ""
    if len(md) < MIN_CONTENT_CHARS:
        # Firecrawl returned success but with too-thin content — treat as
        # a soft failure so the caller can surface the paste fallback.
        print(f"[add_by_url] firecrawl returned only {len(md)} chars for {url}")
        return None
    # html_to_text() expects HTML; wrap the markdown in a <pre> so its
    # parser preserves whitespace and treats it as one text block. The
    # extractor Claude sees this as the page's readable content — same
    # shape as the httpx/playwright paths.
    wrapped = f"<html><head></head><body><pre>{md}</pre></body></html>"
    return 200, wrapped


def fetch_url_as_text(url: str) -> tuple[str, str | None]:
    """Return (plain_text, title). Raises FetchBlockedError if all fetch
    strategies fail — the caller then asks the user to paste page text
    manually instead.

    Strategy (four stages, escalating cost, first-that-works wins):
      1. httpx with Chrome-ish headers          — ~200ms, works for open sites
      2. curl-cffi with Chrome TLS impersonation  — ~500ms, beats TLS fingerprinting
      3. Playwright headless Chromium + stealth  — ~5-15s, beats mid-tier Cloudflare
      4. Firecrawl API                            — ~3-10s, beats enterprise Cloudflare
                                                    (Viator, GetYourGuide, Klook)
    """

    def _is_thin_body(html_body: str) -> bool:
        return len(html_to_text(html_body)[0]) < MIN_CONTENT_CHARS

    status: int = 0
    body: str = ""
    fetch_err: Exception | None = None

    # For JS-heavy OTAs (GYG/Klook/Viator/…) the raw HTML has option names
    # but not per-variant prices — hydration happens in the browser. Skip
    # stages 1-2 and go straight to the JS-rendering path.
    js_heavy = _needs_js_render(url)

    if not js_heavy:
        # Stage 1: httpx
        try:
            status, body = _fetch_with_httpx(url)
        except httpx.HTTPError as e:
            fetch_err = e

    needs_fallback = js_heavy or (
        fetch_err is not None or status >= 400 or _is_thin_body(body)
    )

    # Stage 2: curl-cffi (Chrome-impersonated TLS)
    # Skipped for JS-heavy hosts since it also returns un-hydrated HTML.
    if needs_fallback and not js_heavy:
        try:
            fallback = _fetch_with_curl_cffi(url)
        except Exception as e:  # noqa: BLE001
            fallback = None
            fetch_err = e
        if fallback is not None:
            status, body = fallback
            fetch_err = None
        needs_fallback = (
            fetch_err is not None or status >= 400 or _is_thin_body(body)
        )

    # Stage 3: Playwright headless Chromium — solves Cloudflare JS challenges
    if needs_fallback:
        try:
            fallback = _fetch_with_playwright(url)
        except Exception as e:  # noqa: BLE001
            fallback = None
            fetch_err = e
        if fallback is not None:
            status, body = fallback
            fetch_err = None
        needs_fallback = (
            fetch_err is not None or status >= 400 or _is_thin_body(body)
        )

    # Stage 4: Firecrawl API — beats enterprise Cloudflare (Viator, GYG, Klook)
    if needs_fallback:
        try:
            fallback = _fetch_with_firecrawl(url)
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


# ---------- Claude: extract ALL bookable options from text ----------

_EXTRACT_SYSTEM = """You are extracting every distinct bookable OPTION from a scraped \
seller product page.

Pages on Klook, GetYourGuide, Viator, Headout, and similar OTAs often list many \
packages on one URL — different group sizes, adult/child combos, tiers, times, \
add-ons. Extract EACH ONE as its own option. Do NOT collapse them into one \
representative variant. Do NOT invent options that aren't in the text.

CRITICAL — ALWAYS NORMALISE TO PER SINGLE ADULT
=================================================
Rayna's catalog stores every option on a per-adult basis so the workspace \
can compare like-for-like. You MUST match that convention:

  • `pricing_basis` should be "per_adult" whenever the option can be \
priced per single adult ticket.
  • `price` must be the price for ONE adult.
  • If the seller quotes a bundle price (e.g. "Group of 3: $186.75" or \
"Family pack for 2 adults + 2 kids: $250"), DIVIDE it out to a per-adult \
equivalent and mention the division in `notes` (e.g. "Group price $186.75 \
for 3 adults; per_adult = $62.25").
  • If a package genuinely can't be split down (e.g. a private safari \
priced per-vehicle regardless of headcount), set `pricing_basis` to \
"private_group" / "per_vehicle" / "per_boat" as appropriate, keep the \
bundle price as-is, and flag it in `notes` so the reviewer knows the \
price is not directly comparable to a per-adult Rayna option.
  • If the same option is offered on multiple dates but the price is \
identical, extract ONCE. If prices differ by date, extract the primary \
"from" price and mention the date range in `notes`.

Fingerprint rules (same as the rest of the pipeline):

1. `pricing_basis`: per_adult, per_child, private_group, per_vehicle, per_boat, \
per_yacht, or unknown. Default to per_adult; only use the others when the \
option genuinely can't be priced per single adult (see rule above).

2. Extract `inclusions` and `exclusions` as short atomic items when the page lists them.

3. `highlights` are marketing bullets ("Skip the line", "Sunset views"). Distinct \
from inclusions.

4. `duration_minutes`: convert cleanly-numeric durations. Use `duration_label` when \
the source string is ambiguous (e.g. "half day").

5. `cancellation_window_hours`: e.g. "Free cancellation up to 24 hours prior" -> 24. \
For non-refundable, leave null and mention in `notes`.

6. `transfer_included` / `meal_included`: only set true/false if explicit.

7. If a field isn't stated on the page for a given option, leave it empty. Don't \
invent. Some options may share fields (e.g. cancellation) — repeat the value on each.

8. Each option's `name` must be distinct and disambiguate it from the others \
(e.g. "1-day ticket standard adult" vs "1-day ticket express-lane adult"). \
When you derive a per-adult price from a bundle, keep the bundle wording in \
the name so a reviewer can trace it (e.g. "Group of 3 (per adult, derived)").

9. If the page shows only one option, return a single-element list.

10. Output ONLY via the `record_options` tool. You MUST always include the \
`options` key in your tool input, even if the list is empty. If the page \
genuinely has no visible bookable options (e.g. it's a listing/category page \
or the content is blank), call the tool with `{"options": []}` — never call \
it with a bare `{}`."""


_EXTRACT_USER_TEMPLATE = """SELLER URL: {url}
PAGE TITLE: {title}

PAGE CONTENT (trimmed):
{content}

Extract every distinct bookable option on the page. Use the `record_options` tool."""


def _extract_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "record_options",
            "description": (
                "Record ALL distinct bookable options extracted from this seller "
                "page. One entry per option/package/variant."
            ),
            "input_schema": ExtractionResult.model_json_schema(),
        }
    ]


import re as _re

# Firecrawl's markdown output on image-heavy OTA pages (Klook especially) is
# ~40% base64/CDN image URLs that carry zero pricing signal but eat the
# extractor's char budget. Strip them before Claude sees the content so the
# package picker further down the page actually makes the cut.
_MD_IMAGE_RE = _re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_URL_RE = _re.compile(r"\((https?://[^)]{80,})\)")


def _compact_for_extraction(content: str) -> str:
    """Drop markdown image references and long inline URLs, collapse blank lines.
    Keeps the visible text and short/named links; strips the CDN noise."""
    stripped = _MD_IMAGE_RE.sub("", content)
    stripped = _MD_LINK_URL_RE.sub("()", stripped)
    # Collapse 3+ blank lines to a single blank line.
    stripped = _re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def extract_competitor_options(
    client: Anthropic,
    content: str,
    url: str,
    page_title: str | None,
) -> list[ExtractedOption]:
    """Claude extracts every distinct bookable option from the raw text.

    Returns a list — empty is impossible in practice (Claude falls back to
    a single-element list if the page has only one option). If Claude fails
    to call the tool, raises RuntimeError so the caller can surface the
    paste-text fallback."""
    compacted = _compact_for_extraction(content)
    # Sonnet 4.6 handles 200K context; we can afford a generous window so
    # bloated OTA markdown (Klook, GYG) doesn't get truncated before the
    # package picker further down the page.
    MAX_CHARS = 120000
    if len(compacted) > MAX_CHARS:
        trimmed = compacted[:MAX_CHARS]
    else:
        trimmed = compacted
    print(
        f"[add_by_url] extractor input: raw={len(content)} chars -> "
        f"compacted={len(compacted)} -> sent={len(trimmed)}"
    )

    user_text = _EXTRACT_USER_TEMPLATE.format(
        url=url,
        title=page_title or "(none)",
        content=trimmed,
    )

    resp = client.messages.create(
        model=config.CLAUDE_ADJUDICATOR_MODEL,
        # Klook / GYG pages list 20-40 packages once you include group-size
        # variants; 4096 tokens truncates mid-tool-call and Anthropic returns
        # an empty tool_use (stop_reason=max_tokens). Sonnet 4.6 supports up
        # to 64K output tokens natively — 16K is plenty of headroom for the
        # busiest OTA pages while staying well under limits.
        max_tokens=16000,
        system=[
            {
                "type": "text",
                "text": _EXTRACT_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=_extract_tools(),
        tool_choice={"type": "tool", "name": "record_options"},
        messages=[{"role": "user", "content": user_text}],
    )

    tool_blocks = [
        b for b in resp.content if b.type == "tool_use" and b.name == "record_options"
    ]
    if not tool_blocks:
        raise RuntimeError(
            f"Claude did not call record_options; stop_reason={resp.stop_reason}"
        )

    raw = dict(tool_blocks[0].input)
    # Claude occasionally abstains and calls the tool with `{}` — accept that
    # as "no options found" instead of surfacing a Pydantic ValidationError.
    if "options" not in raw or raw.get("options") is None:
        print(
            f"[add_by_url] extractor returned no options key (raw keys={list(raw.keys())}); "
            f"stop_reason={resp.stop_reason}"
        )
        raw["options"] = []
    # Same defensive coercion the enricher does — Sonnet sometimes emits "" for
    # Optional[int] fields which Pydantic rejects.
    for opt in raw.get("options") or []:
        if not isinstance(opt, dict):
            continue
        fp = opt.get("fingerprint")
        if isinstance(fp, dict):
            for k, v in list(fp.items()):
                if v == "":
                    fp[k] = None
    parsed = ExtractionResult.model_validate(raw)
    return list(parsed.options)


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
