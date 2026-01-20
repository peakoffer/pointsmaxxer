from __future__ import annotations

"""Seats.aero API scraper for PointsMaxxer.

Seats.aero is a third-party award search aggregator that provides
API access to award availability across multiple programs.

API Docs: https://developers.seats.aero/reference/overview
"""

from datetime import datetime, timedelta
from typing import Optional

import httpx

from ..models import Award, CabinClass, Flight, FlightAmenities
from .base import BaseScraper, register_scraper, ParseError, RateLimitError


# Cabin code mapping for Seats.aero API
CABIN_CODES = {
    CabinClass.ECONOMY: "Y",
    CabinClass.PREMIUM_ECONOMY: "W",
    CabinClass.BUSINESS: "J",
    CabinClass.FIRST: "F",
}

CABIN_PARAMS = {
    CabinClass.ECONOMY: "economy",
    CabinClass.PREMIUM_ECONOMY: "premium",
    CabinClass.BUSINESS: "business",
    CabinClass.FIRST: "first",
}

# Source (mileage program) mappings
SOURCE_NAMES = {
    "united": "United MileagePlus",
    "american": "American AAdvantage",
    "delta": "Delta SkyMiles",
    "aeroplan": "Air Canada Aeroplan",
    "alaska": "Alaska Mileage Plan",
    "virgin-atlantic": "Virgin Atlantic Flying Club",
    "flying-blue": "Air France/KLM Flying Blue",
    "lifemiles": "Avianca LifeMiles",
    "velocity": "Velocity Frequent Flyer",
    "smiles": "GOL Smiles",
    "aeromexico": "Aeromexico Club Premier",
    "emirates": "Emirates Skywards",
    "etihad": "Etihad Guest",
    "qantas": "Qantas Frequent Flyer",
    "asiamiles": "Cathay Pacific Asia Miles",
    "connecting-partners": "Connecting Partners",
}


@register_scraper("seats_aero")
class SeatsAeroScraper(BaseScraper):
    """Scraper using Seats.aero Partner API.

    Requires a Seats.aero Pro subscription and API key.
    Get your key at: https://seats.aero/apikey
    """

    PROGRAM_CODE = "seats_aero"
    PROGRAM_NAME = "Seats.aero"
    BASE_URL = "https://seats.aero/partnerapi"

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """Initialize Seats.aero scraper.

        Args:
            api_key: Seats.aero API key (from https://seats.aero/apikey)
            **kwargs: Additional arguments passed to BaseScraper.
        """
        super().__init__(**kwargs)
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is available."""
        if self._client is None:
            headers = {
                "Accept": "application/json",
            }
            if self.api_key:
                headers["Partner-Authorization"] = f"Bearer {self.api_key}"

            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    async def search_awards(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
        sources: Optional[list[str]] = None,
    ) -> list[Award]:
        """Search for award availability via Seats.aero cached search API.

        Args:
            origin: Origin airport code (e.g., "SFO")
            destination: Destination airport code (e.g., "NRT")
            date: Search date
            cabin: Cabin class to search
            sources: Optional list of mileage program sources to filter

        Returns:
            List of available awards.
        """
        if not self.api_key:
            raise ParseError("Seats.aero API key required. Get one at https://seats.aero/apikey")

        client = await self._ensure_client()

        try:
            # Build query parameters per API spec
            params = {
                "origin_airport": origin.upper(),
                "destination_airport": destination.upper(),
                "start_date": date.strftime("%Y-%m-%d"),
                "end_date": (date + timedelta(days=1)).strftime("%Y-%m-%d"),
                "take": 100,
            }

            # Add cabin filter
            cabin_param = CABIN_PARAMS.get(cabin)
            if cabin_param:
                params["cabins"] = cabin_param

            # Add source filter if specified
            if sources:
                params["sources"] = ",".join(sources)

            response = await client.get("/search", params=params)

            if response.status_code == 401:
                raise ParseError("Invalid Seats.aero API key")
            if response.status_code == 429:
                raise RateLimitError("Seats.aero rate limit exceeded (1000/day)")
            if response.status_code != 200:
                raise ParseError(f"Seats.aero API error: {response.status_code} - {response.text}")

            data = response.json()
            return self._parse_response(data, cabin)

        except httpx.HTTPError as e:
            raise ParseError(f"Seats.aero request failed: {e}")

    def _parse_response(self, data: dict, requested_cabin: CabinClass) -> list[Award]:
        """Parse Seats.aero API response into Award objects."""
        awards = []
        cabin_code = CABIN_CODES.get(requested_cabin, "J")

        results = data.get("data", [])
        for result in results:
            try:
                award = self._parse_availability(result, requested_cabin, cabin_code)
                if award:
                    awards.append(award)
            except Exception:
                continue

        return awards

    def _parse_availability(
        self,
        result: dict,
        cabin: CabinClass,
        cabin_code: str,
    ) -> Optional[Award]:
        """Parse a single availability result."""
        try:
            # Check if requested cabin is available
            available_key = f"{cabin_code}Available"
            if not result.get(available_key, False):
                return None

            # Get route info
            route = result.get("Route", {})
            origin = route.get("OriginAirport", "???")
            destination = route.get("DestinationAirport", "???")
            source = result.get("Source", route.get("Source", "unknown"))

            # Get mileage cost for cabin
            mileage_key = f"{cabin_code}MileageCost"
            miles_str = result.get(mileage_key, "0")
            try:
                miles = int(miles_str.replace(",", "")) if miles_str else 0
            except (ValueError, AttributeError):
                miles = 0

            if miles <= 0:
                return None

            # Get seat count
            seats_key = f"{cabin_code}RemainingSeats"
            seats = result.get(seats_key, 1) or 1

            # Get airline info
            airlines_key = f"{cabin_code}Airlines"
            airlines = result.get(airlines_key, "")
            airline_code = airlines.split(",")[0] if airlines else "??"

            # Check if direct
            direct_key = f"{cabin_code}Direct"
            is_direct = result.get(direct_key, False)

            # Parse date
            date_str = result.get("Date", "")
            try:
                departure = datetime.strptime(date_str, "%Y-%m-%d")
                # Estimate arrival (we don't have exact times from cached search)
                arrival = departure + timedelta(hours=12)
            except ValueError:
                departure = datetime.now()
                arrival = departure + timedelta(hours=12)

            # Build Flight object
            flight = Flight(
                flight_no=f"{airline_code}*",  # Asterisk indicates multiple possible flights
                airline_code=airline_code,
                airline_name=airlines,
                origin=origin,
                destination=destination,
                departure=departure,
                arrival=arrival,
                duration_minutes=0,  # Not available in cached search
                aircraft=None,
                stops=0 if is_direct else 1,
                amenities=FlightAmenities(),
            )

            # Get program name
            program_name = SOURCE_NAMES.get(source, source)

            return Award(
                flight=flight,
                program=source,
                program_name=program_name,
                miles=miles,
                cash_fees=0.0,  # Not available in cached search
                cabin=cabin,
                booking_class=None,
                is_saver=True,  # Seats.aero shows saver availability
                availability=seats,
                scraped_at=datetime.now(),
                source="seats.aero",
            )

        except Exception:
            return None

    async def search_all_programs(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Search all supported programs via Seats.aero.

        This is the primary method for getting comprehensive award availability.
        """
        return await self.search_awards(
            origin=origin,
            destination=destination,
            date=date,
            cabin=cabin,
            sources=None,  # Search all sources
        )

    async def get_availability_count(
        self,
        origin: str,
        destination: str,
        start_date: datetime,
        end_date: datetime,
        cabin: CabinClass,
    ) -> dict[str, int]:
        """Get count of available dates in a date range.

        Returns:
            Dict mapping date strings to number of available programs
        """
        if not self.api_key:
            return {}

        client = await self._ensure_client()
        cabin_code = CABIN_CODES.get(cabin, "J")

        try:
            params = {
                "origin_airport": origin.upper(),
                "destination_airport": destination.upper(),
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "cabins": CABIN_PARAMS.get(cabin, "business"),
                "take": 500,
            }

            response = await client.get("/search", params=params)
            if response.status_code != 200:
                return {}

            data = response.json()

            # Count available dates
            date_counts: dict[str, int] = {}
            for result in data.get("data", []):
                date_str = result.get("Date", "")
                available_key = f"{cabin_code}Available"
                if result.get(available_key, False) and date_str:
                    date_counts[date_str] = date_counts.get(date_str, 0) + 1

            return date_counts

        except Exception:
            return {}

    async def close(self) -> None:
        """Cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
        await super().close()
