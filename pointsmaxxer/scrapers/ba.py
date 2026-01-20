from __future__ import annotations

"""British Airways Avios scraper for PointsMaxxer."""

import re
from datetime import datetime
from typing import Optional

from playwright.async_api import Page

from ..models import Award, CabinClass
from ..utils.mouse import HumanMouse
from .base import BaseScraper, register_scraper, ParseError


@register_scraper("ba_avios")
class BAScraper(BaseScraper):
    """Scraper for British Airways Avios awards."""

    PROGRAM_CODE = "ba_avios"
    PROGRAM_NAME = "British Airways Avios"
    BASE_URL = "https://www.britishairways.com"

    CABIN_MAP = {
        CabinClass.ECONOMY: "M",  # World Traveller
        CabinClass.PREMIUM_ECONOMY: "W",  # World Traveller Plus
        CabinClass.BUSINESS: "J",  # Club World
        CabinClass.FIRST: "F",  # First
    }

    async def search_awards(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Search for BA Avios award availability."""
        browser = await self._ensure_browser()
        cache = await self._ensure_cache()

        cache_key = f"ba_{origin}_{destination}_{date.strftime('%Y-%m-%d')}_{cabin.value}"
        cached = cache.get(cache_key)
        if cached:
            return [Award.model_validate(a) for a in cached]

        awards = []

        async with browser.get_page() as page:
            mouse = HumanMouse(page)

            try:
                search_url = self._build_search_url(origin, destination, date, cabin)
                await page.goto(search_url, wait_until="networkidle")

                await page.wait_for_selector(
                    ".flight-list, .no-availability",
                    timeout=30000
                )

                awards = await self._parse_results(page, origin, destination, date, cabin)
                cache.set(cache_key, [a.model_dump() for a in awards], ttl_hours=6)

            except Exception as e:
                raise ParseError(f"Failed to parse BA results: {e}")

        return awards

    def _build_search_url(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> str:
        """Build BA search URL."""
        date_str = date.strftime("%Y-%m-%d")
        cabin_code = self.CABIN_MAP.get(cabin, "M")

        return (
            f"{self.BASE_URL}/travel/redeem/rb_ltsu_reward"
            f"?eId=111079"
            f"&departureCity={origin}"
            f"&arrivalCity={destination}"
            f"&departureDate={date_str}"
            f"&cabin={cabin_code}"
            f"&journeyType=SINGLE"
            f"&adt=1"
            f"&young=0"
            f"&child=0"
            f"&infant=0"
        )

    async def _parse_results(
        self,
        page: Page,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Parse BA search results."""
        awards = []

        no_avail = await page.query_selector(".no-availability")
        if no_avail:
            return []

        flight_rows = await page.query_selector_all(".flight-row, [data-testid='flight-option']")

        for row in flight_rows:
            try:
                award = await self._parse_flight_row(row, origin, destination, cabin)
                if award:
                    awards.append(award)
            except Exception:
                continue

        return awards

    async def _parse_flight_row(
        self,
        row,
        origin: str,
        destination: str,
        cabin: CabinClass,
    ) -> Optional[Award]:
        """Parse a single BA flight row."""
        try:
            flight_no_elem = await row.query_selector(".flight-number")
            flight_no = await flight_no_elem.inner_text() if flight_no_elem else "BA???"

            dep_time_elem = await row.query_selector(".departure-time")
            arr_time_elem = await row.query_selector(".arrival-time")

            dep_time = await dep_time_elem.inner_text() if dep_time_elem else "00:00"
            arr_time = await arr_time_elem.inner_text() if arr_time_elem else "00:00"

            duration_elem = await row.query_selector(".flight-duration")
            duration_text = await duration_elem.inner_text() if duration_elem else "0h 0m"
            duration_minutes = self._parse_duration(duration_text)

            # BA shows Avios
            avios_elem = await row.query_selector(".avios-value, .points-amount")
            avios_text = await avios_elem.inner_text() if avios_elem else "0"
            avios = self._parse_miles(avios_text)

            if avios <= 0:
                return None

            fees_elem = await row.query_selector(".taxes-fees, .cash-amount")
            fees_text = await fees_elem.inner_text() if fees_elem else "£0"
            fees = self._parse_price(fees_text)

            # BA has "Reward" (saver) and "Reward Plus" pricing
            is_saver = False
            reward_type_elem = await row.query_selector(".reward-type")
            if reward_type_elem:
                reward_type = await reward_type_elem.inner_text()
                if "Reward" in reward_type and "Plus" not in reward_type:
                    is_saver = True

            # Determine operating carrier (BA operates with oneworld partners)
            operating_elem = await row.query_selector(".operated-by")
            airline_name = "British Airways"
            airline_code = "BA"
            if operating_elem:
                operating_text = await operating_elem.inner_text()
                carriers = {
                    "American": ("AA", "American Airlines"),
                    "Iberia": ("IB", "Iberia"),
                    "Finnair": ("AY", "Finnair"),
                    "Japan Airlines": ("JL", "Japan Airlines"),
                    "JAL": ("JL", "Japan Airlines"),
                    "Qantas": ("QF", "Qantas"),
                    "Qatar": ("QR", "Qatar Airways"),
                    "Cathay": ("CX", "Cathay Pacific"),
                    "Malaysia": ("MH", "Malaysia Airlines"),
                }
                for carrier_name, (code, full_name) in carriers.items():
                    if carrier_name in operating_text:
                        airline_code = code
                        airline_name = full_name
                        break

            aircraft_elem = await row.query_selector(".aircraft-type")
            aircraft = await aircraft_elem.inner_text() if aircraft_elem else None

            departure = self._parse_time(dep_time)
            arrival = self._parse_time(arr_time)

            flight = self.create_flight(
                flight_no=flight_no.strip(),
                airline_code=airline_code,
                airline_name=airline_name,
                origin=origin,
                destination=destination,
                departure=departure,
                arrival=arrival,
                duration_minutes=duration_minutes,
                aircraft=aircraft,
            )

            return self.create_award(
                flight=flight,
                miles=avios,
                cabin=cabin,
                cash_fees=fees,
                is_saver=is_saver,
            )

        except Exception:
            return None

    def _parse_duration(self, text: str) -> int:
        match = re.search(r"(\d+)h\s*(\d+)?m?", text)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2)) if match.group(2) else 0
            return hours * 60 + minutes
        return 0

    def _parse_miles(self, text: str) -> int:
        cleaned = re.sub(r"[^\d]", "", text)
        return int(cleaned) if cleaned else 0

    def _parse_price(self, text: str) -> float:
        # Handle both $ and £
        match = re.search(r"[£$]?([\d,]+(?:\.\d{2})?)", text)
        if match:
            price = float(match.group(1).replace(",", ""))
            # Convert GBP to USD roughly if £
            if "£" in text:
                price *= 1.27
            return price
        return 0.0

    def _parse_time(self, text: str) -> datetime:
        now = datetime.now()
        try:
            text = text.strip()
            # BA typically uses 24-hour format
            time_obj = datetime.strptime(text, "%H:%M")
            return now.replace(
                hour=time_obj.hour,
                minute=time_obj.minute,
                second=0,
                microsecond=0,
            )
        except ValueError:
            return now
