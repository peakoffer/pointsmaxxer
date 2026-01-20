from __future__ import annotations

"""Playwright browser setup with stealth features for PointsMaxxer."""

import asyncio
import random
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


# Common user agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Common viewport sizes
VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 720},
]


async def create_stealth_browser(
    playwright: Playwright,
    headless: bool = True,
    slow_mo: int = 0,
) -> Browser:
    """Create a browser with stealth settings.

    Args:
        playwright: Playwright instance.
        headless: Whether to run headless.
        slow_mo: Slow motion delay in ms.

    Returns:
        Configured Browser instance.
    """
    browser = await playwright.chromium.launch(
        headless=headless,
        slow_mo=slow_mo,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )
    return browser


async def create_stealth_context(
    browser: Browser,
    user_agent: Optional[str] = None,
    viewport: Optional[dict] = None,
) -> BrowserContext:
    """Create a browser context with stealth settings.

    Args:
        browser: Browser instance.
        user_agent: User agent string. Random if not provided.
        viewport: Viewport size. Random if not provided.

    Returns:
        Configured BrowserContext.
    """
    if user_agent is None:
        user_agent = random.choice(USER_AGENTS)

    if viewport is None:
        viewport = random.choice(VIEWPORT_SIZES)

    context = await browser.new_context(
        user_agent=user_agent,
        viewport=viewport,
        locale="en-US",
        timezone_id="America/Los_Angeles",
        geolocation={"latitude": 37.7749, "longitude": -122.4194},
        permissions=["geolocation"],
        color_scheme="light",
        device_scale_factor=1,
    )

    # Add stealth scripts
    await context.add_init_script("""
        // Override webdriver property
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });

        // Override plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });

        // Override languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });

        // Override platform
        Object.defineProperty(navigator, 'platform', {
            get: () => 'MacIntel',
        });

        // Override hardware concurrency
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8,
        });

        // Override deviceMemory
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8,
        });

        // Remove automation indicators
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

        // Override chrome runtime
        window.chrome = {
            runtime: {},
        };

        // Override permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    """)

    return context


class BrowserManager:
    """Manages browser lifecycle and provides stealth pages."""

    def __init__(
        self,
        headless: bool = True,
        slow_mo: int = 0,
        request_delay: float = 2.0,
    ):
        """Initialize browser manager.

        Args:
            headless: Whether to run headless.
            slow_mo: Slow motion delay in ms.
            request_delay: Delay between requests in seconds.
        """
        self.headless = headless
        self.slow_mo = slow_mo
        self.request_delay = request_delay
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self) -> None:
        """Start the browser."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            self._browser = await create_stealth_browser(
                self._playwright,
                headless=self.headless,
                slow_mo=self.slow_mo,
            )

    async def stop(self) -> None:
        """Stop the browser and cleanup."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    @asynccontextmanager
    async def get_page(self) -> AsyncGenerator[Page, None]:
        """Get a new stealth page.

        Yields:
            A configured Page instance.
        """
        if self._browser is None:
            await self.start()

        context = await create_stealth_context(self._browser)
        page = await context.new_page()

        try:
            yield page
        finally:
            await page.close()
            await context.close()

    async def delay(self, min_seconds: Optional[float] = None, max_seconds: Optional[float] = None) -> None:
        """Add a random delay between requests.

        Args:
            min_seconds: Minimum delay. Defaults to request_delay * 0.5.
            max_seconds: Maximum delay. Defaults to request_delay * 1.5.
        """
        if min_seconds is None:
            min_seconds = self.request_delay * 0.5
        if max_seconds is None:
            max_seconds = self.request_delay * 1.5

        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)

    async def __aenter__(self) -> "BrowserManager":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()


async def wait_for_page_load(page: Page, timeout: int = 30000) -> None:
    """Wait for page to fully load.

    Args:
        page: Page instance.
        timeout: Timeout in milliseconds.
    """
    await page.wait_for_load_state("networkidle", timeout=timeout)


async def scroll_page(page: Page, scroll_amount: int = 300) -> None:
    """Scroll page by a random amount to simulate human behavior.

    Args:
        page: Page instance.
        scroll_amount: Base scroll amount in pixels.
    """
    amount = scroll_amount + random.randint(-50, 50)
    await page.evaluate(f"window.scrollBy(0, {amount})")
    await asyncio.sleep(random.uniform(0.1, 0.3))


async def type_like_human(page: Page, selector: str, text: str) -> None:
    """Type text with human-like delays.

    Args:
        page: Page instance.
        selector: Element selector.
        text: Text to type.
    """
    element = await page.query_selector(selector)
    if element:
        await element.click()
        for char in text:
            await page.keyboard.type(char, delay=random.randint(50, 150))
            if random.random() < 0.1:  # 10% chance of extra pause
                await asyncio.sleep(random.uniform(0.1, 0.3))
