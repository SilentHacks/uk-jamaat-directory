"""Playwright fetcher for JavaScript-rendered pages.

Used by the repo-extractor runtime when a target has
``requires_javascript=True``. The browser runs headless, navigates to the
URL, waits for network idle, and returns the fully-rendered HTML.
"""

from __future__ import annotations

from playwright.async_api import async_playwright

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.fetch.types import FetchResult


async def fetch_rendered_html(
    url: str,
    *,
    settings: Settings | None = None,
    wait_until: str = "networkidle",
    timeout_seconds: float = 30.0,
) -> FetchResult:
    """Fetch *url* via a headless Chromium browser and return the rendered
    DOM as HTML bytes.

    Parameters
    ----------
    url:
        The URL to navigate to.
    settings:
        Application settings (used for user-agent if provided).
    wait_until:
        Playwright ``wait_until`` option (``load``, ``domcontentloaded``,
        ``networkidle``, ``commit``). Default is ``networkidle``.
    timeout_seconds:
        Navigation timeout. Default is 30s.

    Returns
    -------
    :class:`~uk_jamaat_directory.ingest.fetch.types.FetchResult`
        The result carries ``status_code=200`` on success, ``body`` is the
        UTF-8 encoded rendered HTML, and ``content_type`` is
        ``text/html; charset=utf-8``.
    """

    cfg = settings
    user_agent = cfg.crawl_user_agent if cfg else None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=user_agent,
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()
            response = await page.goto(
                url,
                wait_until=wait_until,
                timeout=timeout_seconds * 1000,
            )
            status_code = response.status if response else 200
            html = await page.content()
            await browser.close()
    except Exception as exc:
        return FetchResult(
            status_code=None,
            body=b"",
            content_type=None,
            error=f"playwright failed: {exc}",
        )

    return FetchResult(
        status_code=status_code,
        body=html.encode("utf-8"),
        content_type="text/html; charset=utf-8",
        etag=None,
        last_modified=None,
        unchanged=False,
    )
