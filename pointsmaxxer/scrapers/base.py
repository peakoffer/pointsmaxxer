from __future__ import annotations

"""Base scraper class for PointsMaxxer."""

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Type

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..models import Award, CabinClass, Flight, FlightAmenities
from ..utils.browser import BrowserManager
from ..utils.cache import ResponseCache


class ScraperError(Exception):
    """Base exception for scraper errors."""
    pass


class RateLimitError(ScraperError):
    """Raised when rate limited."""
    pass


class AuthenticationError(ScraperError):
    """Raised when authentication fails."""
    pass


class ParseError(ScraperError):
    """Raised when response parsing fails."""
    pass


class BaseScraper(ABC):
    """Base class for airline scrapers."""

    # Override in subclasses
    PROGRAM_CODE = ""
    PROGRAM_NAME = ""
    BASE_URL = ""

    def __init__(
        self,
        browser_manager: Optional[BrowserManager] = None,
        cache: Optional[ResponseCache] = None,
        request_delay: float = 2.0,
    ):
        """Initialize scraper.

        Args:
            browser_manager: Browser manager instance.
            cache: Response cache instance.
            request_delay: Delay between requests in seconds.
        """
        self._browser = browser_manager
        self._cache = cache
        self.request_delay = request_delay
        self._owns_browser = False

    async def _ensure_browser(self) -> BrowserManager:
        """Ensure browser is available."""
        if self._browser is None:
            self._browser = BrowserManager(request_delay=self.request_delay)
            await self._browser.start()
            self._owns_browser = True
        return self._browser

    async def _ensure_cache(self) -> ResponseCache:
        """Ensure cache is available."""
        if self._cache is None:
            self._cache = ResponseCache()
        return self._cache

    @abstractmethod
    async def search_awards(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Search for award availability.

        Args:
            origin: Origin airport code.
            destination: Destination airport code.
            date: Search date.
            cabin: Cabin class.

        Returns:
            List of available awards.
        """
        pass

    async def search_date_range(
        self,
        origin: str,
        destination: str,
        start_date: datetime,
        end_date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Search for awards across a date range.

        Args:
            origin: Origin airport code.
            destination: Destination airport code.
            start_date: Start of search range.
            end_date: End of search range.
            cabin: Cabin class.

        Returns:
            List of all available awards in range.
        """
        all_awards = []
        current_date = start_date

        while current_date <= end_date:
            try:
                awards = await self.search_awards(origin, destination, current_date, cabin)
                all_awards.extend(awards)
            except Exception as e:
                # Log but continue with other dates
                print(f"Error searching {current_date}: {e}")

            # Move to next day
            current_date = datetime(
                current_date.year,
                current_date.month,
                current_date.day + 1
            )

            # Delay between requests
            await asyncio.sleep(self.request_delay)

        return all_awards

    def create_flight(
        self,
        flight_no: str,
        airline_code: str,
        origin: str,
        destination: str,
        departure: datetime,
        arrival: datetime,
        duration_minutes: int,
        aircraft: Optional[str] = None,
        stops: int = 0,
        amenities: Optional[FlightAmenities] = None,
        airline_name: str = "",
    ) -> Flight:
        """Helper to create Flight objects."""
        return Flight(
            flight_no=flight_no,
            airline_code=airline_code,
            airline_name=airline_name,
            origin=origin,
            destination=destination,
            departure=departure,
            arrival=arrival,
            duration_minutes=duration_minutes,
            aircraft=aircraft,
            stops=stops,
            amenities=amenities or FlightAmenities(),
        )

    def create_award(
        self,
        flight: Flight,
        miles: int,
        cabin: CabinClass,
        cash_fees: float = 0.0,
        booking_class: Optional[str] = None,
        is_saver: bool = False,
        availability: int = 1,
    ) -> Award:
        """Helper to create Award objects."""
        return Award(
            flight=flight,
            program=self.PROGRAM_CODE,
            program_name=self.PROGRAM_NAME,
            miles=miles,
            cash_fees=cash_fees,
            cabin=cabin,
            booking_class=booking_class,
            is_saver=is_saver,
            availability=availability,
            scraped_at=datetime.now(),
            source=self.__class__.__name__,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RateLimitError, ParseError)),
    )
    async def _fetch_with_retry(self, fetch_func):
        """Fetch with automatic retry on transient errors."""
        return await fetch_func()

    async def close(self) -> None:
        """Cleanup resources."""
        if self._owns_browser and self._browser:
            await self._browser.stop()
            self._browser = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


class ScraperRegistry:
    """Registry of available scrapers."""

    _scrapers: dict[str, Type[BaseScraper]] = {}

    @classmethod
    def register(cls, program_code: str, scraper_class: Type[BaseScraper]) -> None:
        """Register a scraper."""
        cls._scrapers[program_code] = scraper_class

    @classmethod
    def get(cls, program_code: str) -> Optional[Type[BaseScraper]]:
        """Get a scraper by program code."""
        return cls._scrapers.get(program_code)

    @classmethod
    def get_all(cls) -> dict[str, Type[BaseScraper]]:
        """Get all registered scrapers."""
        return cls._scrapers.copy()

    @classmethod
    def list_programs(cls) -> list[str]:
        """List all registered program codes."""
        return list(cls._scrapers.keys())


def register_scraper(program_code: str):
    """Decorator to register a scraper."""
    def decorator(cls: Type[BaseScraper]) -> Type[BaseScraper]:
        ScraperRegistry.register(program_code, cls)
        return cls
    return decorator
