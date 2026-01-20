from __future__ import annotations

"""American Airlines AAdvantage scraper for PointsMaxxer."""

import re
from datetime import datetime
from typing import Optional

from playwright.async_api import Page

from ..models import Award, CabinClass, FlightAmenities
from ..utils.mouse import HumanMouse
from .base import BaseScraper, register_scraper, ParseError


@register_scraper("aa")
class AAScraper(BaseScraper):
    """Scraper for American Airlines AAdvantage awards."""

    PROGRAM_CODE = "aa"
    PROGRAM_NAME = "American AAdvantage"
    BASE_URL = "https://www.aa.com"

    CABIN_MAP = {
        CabinClass.ECONOMY: "coach",
        CabinClass.PREMIUM_ECONOMY: "premium-economy",
        CabinClass.BUSINESS: "business",
        CabinClass.FIRST: "first",
    }

    async def search_awards(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Search for AA award availability.

        Args:
            origin: Origin airport code.
            destination: Destination airport code.
            date: Search date.
            cabin: Cabin class.

        Returns:
            List of available awards.
        """
        browser = await self._ensure_browser()
        cache = await self._ensure_cache()

        # Check cache first
        cache_key = f"aa_{origin}_{destination}_{date.strftime('%Y-%m-%d')}_{cabin.value}"
        cached = cache.get(cache_key)
        if cached:
            return [Award.model_validate(a) for a in cached]

        awards = []

        async with browser.get_page() as page:
            mouse = HumanMouse(page)

            try:
                # Navigate to award search
                search_url = self._build_search_url(origin, destination, date, cabin)
                await page.goto(search_url, wait_until="networkidle")

                # Wait for results to load
                await page.wait_for_selector(".flight-results, .no-flights-found", timeout=30000)

                # Parse results
                awards = await self._parse_results(page, origin, destination, date, cabin)

                # Cache results
                cache.set(cache_key, [a.model_dump() for a in awards], ttl_hours=6)

            except Exception as e:
                raise ParseError(f"Failed to parse AA results: {e}")

        return awards

    def _build_search_url(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> str:
        """Build AA search URL."""
        date_str = date.strftime("%Y-%m-%d")
        cabin_code = self.CABIN_MAP.get(cabin, "coach")

        return (
            f"{self.BASE_URL}/booking/find-flights"
            f"?origin={origin}"
            f"&destination={destination}"
            f"&departureDate={date_str}"
            f"&tripType=oneWay"
            f"&passengers=1"
            f"&cabin={cabin_code}"
            f"&awardBooking=true"
        )

    async def _parse_results(
        self,
        page: Page,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Parse search results from page."""
        awards = []

        # Check for no results
        no_results = await page.query_selector(".no-flights-found")
        if no_results:
            return []

        # Get all flight cards
        flight_cards = await page.query_selector_all(".flight-card, .flight-row")

        for card in flight_cards:
            try:
                award = await self._parse_flight_card(card, origin, destination, cabin)
                if award:
                    awards.append(award)
            except Exception:
                continue

        return awards

    async def _parse_flight_card(
        self,
        card,
        origin: str,
        destination: str,
        cabin: CabinClass,
    ) -> Optional[Award]:
        """Parse a single flight card."""
        try:
            # Extract flight number
            flight_no_elem = await card.query_selector(".flight-number, [data-flight-number]")
            flight_no = await flight_no_elem.inner_text() if flight_no_elem else "AA???"

            # Extract times
            dep_time_elem = await card.query_selector(".departure-time")
            arr_time_elem = await card.query_selector(".arrival-time")

            dep_time = await dep_time_elem.inner_text() if dep_time_elem else "00:00"
            arr_time = await arr_time_elem.inner_text() if arr_time_elem else "00:00"

            # Extract duration
            duration_elem = await card.query_selector(".duration, .flight-duration")
            duration_text = await duration_elem.inner_text() if duration_elem else "0h 0m"
            duration_minutes = self._parse_duration(duration_text)

            # Extract miles
            miles_elem = await card.query_selector(".miles-value, .award-miles")
            miles_text = await miles_elem.inner_text() if miles_elem else "0"
            miles = self._parse_miles(miles_text)

            if miles <= 0:
                return None

            # Extract fees
            fees_elem = await card.query_selector(".taxes-fees, .cash-price")
            fees_text = await fees_elem.inner_text() if fees_elem else "$0"
            fees = self._parse_price(fees_text)

            # Check if saver award
            is_saver = False
            saver_elem = await card.query_selector(".saver, .milesaver, [data-award-type='saver']")
            if saver_elem:
                is_saver = True

            # Extract aircraft if available
            aircraft_elem = await card.query_selector(".aircraft-type")
            aircraft = await aircraft_elem.inner_text() if aircraft_elem else None

            # Create datetime objects
            departure = self._parse_time(dep_time)
            arrival = self._parse_time(arr_time)

            flight = self.create_flight(
                flight_no=flight_no.strip(),
                airline_code="AA",
                airline_name="American Airlines",
                origin=origin,
                destination=destination,
                departure=departure,
                arrival=arrival,
                duration_minutes=duration_minutes,
                aircraft=aircraft,
            )

            return self.create_award(
                flight=flight,
                miles=miles,
                cabin=cabin,
                cash_fees=fees,
                is_saver=is_saver,
            )

        except Exception:
            return None

    def _parse_duration(self, text: str) -> int:
        """Parse duration text to minutes."""
        match = re.search(r"(\d+)h\s*(\d+)?m?", text)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2)) if match.group(2) else 0
            return hours * 60 + minutes
        return 0

    def _parse_miles(self, text: str) -> int:
        """Parse miles text to integer."""
        cleaned = re.sub(r"[^\d]", "", text)
        return int(cleaned) if cleaned else 0

    def _parse_price(self, text: str) -> float:
        """Parse price text to float."""
        match = re.search(r"\$?([\d,]+(?:\.\d{2})?)", text)
        if match:
            return float(match.group(1).replace(",", ""))
        return 0.0

    def _parse_time(self, text: str) -> datetime:
        """Parse time text to datetime."""
        # Default to today if parsing fails
        now = datetime.now()
        try:
            # Handle formats like "8:30 AM", "14:30"
            text = text.strip().upper()
            if "AM" in text or "PM" in text:
                time_obj = datetime.strptime(text, "%I:%M %p")
            else:
                time_obj = datetime.strptime(text, "%H:%M")
            return now.replace(
                hour=time_obj.hour,
                minute=time_obj.minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            return now
