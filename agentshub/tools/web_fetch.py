"""
Web Fetch Tool — retrieves and extracts readable text from URLs.

Handles:
  - User-agent rotation to avoid basic blocking
  - Timeout and error handling
  - HTML stripping (scripts, styles, nav removed)
  - Google News redirect URLs (skipped — they don't resolve)
  - Content length limiting to keep token counts manageable
  - Graceful fallback on 403/429/timeout

Usage:
    from agentshub.tools.web_fetch import fetch_article, fetch_articles_parallel

    text = fetch_article("https://example.com/article")
    results = fetch_articles_parallel(["url1", "url2", "url3"])
"""

import re
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# Sites known to block scrapers — skip instead of waiting for timeout
BLOCKED_DOMAINS = [
    "wsj.com", "nytimes.com", "ft.com", "bloomberg.com",
    "paywalled.com", "theathletic.com",
]


def _pick_ua(url: str) -> str:
    """Rotate user-agent based on URL hash for consistency."""
    return USER_AGENTS[hash(url) % len(USER_AGENTS)]


def _is_blocked_domain(url: str) -> bool:
    for domain in BLOCKED_DOMAINS:
        if domain in url:
            return True
    return False


def _is_google_redirect(url: str) -> bool:
    return "news.google.com/rss/articles" in url


def _resolve_google_news_url(url: str, timeout: int = 8) -> str | None:
    """Try to resolve a Google News redirect URL to the actual article URL.

    Google News uses JS redirects, but the response HTML often contains
    the real URL in a meta tag, data attribute, or anchor href.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _pick_ua(url)})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Check if HTTP redirect happened
            final_url = resp.geturl()
            if "news.google.com" not in final_url:
                return final_url

            # Parse HTML for the real URL
            html = resp.read().decode("utf-8", errors="ignore")

            # Look for data-redirect in anchor tags
            match = re.search(r'href="(https?://(?!news\.google\.com)[^"]+)"', html)
            if match:
                return match.group(1)

            # Look for canonical or og:url meta tag
            match = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html)
            if match and "news.google.com" not in match.group(1):
                return match.group(1)

            match = re.search(r'content="(https?://(?!news\.google\.com)[^"]+)"[^>]+property="og:url"', html)
            if not match:
                match = re.search(r'property="og:url"[^>]+content="(https?://(?!news\.google\.com)[^"]+)"', html)
            if match:
                return match.group(1)

    except Exception:
        pass
    return None


def _strip_html(html: str) -> str:
    """Remove scripts, styles, then all tags. Collapse whitespace."""
    html = re.sub(r"<(script|style|noscript|nav|header|footer)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_article(url: str, max_chars: int = 6000, timeout: int = 12) -> dict:
    """
    Fetch a URL and extract readable text.

    Returns dict with:
        url: original URL
        status: "ok" | "blocked" | "redirect" | "error" | "timeout"
        text: extracted text (empty on failure)
        chars: length of extracted text
        source: domain name
    """
    # Extract domain for logging
    domain = re.search(r"https?://(?:www\.)?([^/]+)", url)
    source = domain.group(1) if domain else url[:40]

    if _is_google_redirect(url):
        resolved = _resolve_google_news_url(url)
        if resolved:
            # Recurse with the resolved URL
            result = fetch_article(resolved, max_chars, timeout)
            result["original_url"] = url
            result["resolved_from"] = "google_news_redirect"
            return result
        return {"url": url, "status": "redirect", "text": "", "chars": 0, "source": source,
                "reason": "Google News redirect — could not resolve to actual article URL"}

    if _is_blocked_domain(url):
        return {"url": url, "status": "blocked", "text": "", "chars": 0, "source": source,
                "reason": f"{source} is paywalled or blocks scrapers"}

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _pick_ua(url)})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Check content type — skip PDFs, images, etc.
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return {"url": url, "status": "error", "text": "", "chars": 0, "source": source,
                        "reason": f"non-HTML content: {content_type}"}

            html = resp.read().decode("utf-8", errors="ignore")

        text = _strip_html(html)

        # Skip if too short (probably a redirect page or login wall)
        if len(text) < 200:
            return {"url": url, "status": "error", "text": "", "chars": 0, "source": source,
                    "reason": "page too short after stripping — likely a redirect or login wall"}

        # Trim to max_chars
        text = text[:max_chars]

        return {"url": url, "status": "ok", "text": text, "chars": len(text), "source": source}

    except urllib.error.HTTPError as e:
        status = "blocked" if e.code in (403, 429) else "error"
        return {"url": url, "status": status, "text": "", "chars": 0, "source": source,
                "reason": f"HTTP {e.code}"}

    except Exception as e:
        reason = "timeout" if "timed out" in str(e).lower() else str(e)
        status = "timeout" if "timed out" in str(e).lower() else "error"
        return {"url": url, "status": status, "text": "", "chars": 0, "source": source,
                "reason": reason}


def fetch_articles_parallel(urls: list[str], max_chars: int = 6000, max_workers: int = 5) -> list[dict]:
    """
    Fetch multiple URLs in parallel. Returns list of results in same order as input.
    Skips blocked domains and Google redirects without wasting time on them.
    """
    results = [None] * len(urls)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx = {
            pool.submit(fetch_article, url, max_chars): i
            for i, url in enumerate(urls)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {"url": urls[idx], "status": "error", "text": "", "chars": 0,
                                "source": "", "reason": str(e)}

    return results
