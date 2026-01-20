"""Demo scraper that returns realistic sample award data for testing."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Optional

from ..models import Award, CabinClass, Flight, FlightAmenities
from .base import BaseScraper, register_scraper


# Realistic award pricing data by route type and cabin
AWARD_CHARTS = {
    # Domestic US
    "domestic": {
        CabinClass.ECONOMY: [(12500, "aa"), (15000, "united"), (10000, "delta")],
        CabinClass.BUSINESS: [(25000, "aa"), (30000, "united"), (25000, "delta")],
        CabinClass.FIRST: [(50000, "aa"), (50000, "united"), (50000, "delta")],
    },
    # US to Hawaii
    "hawaii": {
        CabinClass.ECONOMY: [(22500, "aa"), (22500, "united"), (20000, "delta"), (25000, "alaska")],
        CabinClass.BUSINESS: [(45000, "aa"), (45000, "united"), (40000, "delta"), (50000, "alaska")],
        CabinClass.FIRST: [(80000, "aa"), (80000, "united"), (70000, "delta"), (70000, "alaska")],
    },
    # Transatlantic
    "transatlantic": {
        CabinClass.ECONOMY: [(30000, "aeroplan"), (35000, "united"), (40000, "delta"), (26000, "ba_avios")],
        CabinClass.BUSINESS: [(70000, "aeroplan"), (88000, "united"), (85000, "delta"), (60000, "ba_avios")],
        CabinClass.FIRST: [(100000, "aeroplan"), (120000, "united"), (120000, "delta"), (85000, "ba_avios")],
    },
    # Transpacific
    "transpacific": {
        CabinClass.ECONOMY: [(35000, "aeroplan"), (40000, "united"), (45000, "delta"), (35000, "alaska")],
        CabinClass.BUSINESS: [(75000, "aeroplan"), (85000, "ana"), (88000, "united"), (70000, "alaska")],
        CabinClass.FIRST: [(110000, "aeroplan"), (110000, "ana"), (120000, "united"), (70000, "alaska")],
    },
}

# Cash prices for CPP calculation
CASH_PRICES = {
    "domestic": {CabinClass.ECONOMY: 250, CabinClass.BUSINESS: 600, CabinClass.FIRST: 1200},
    "hawaii": {CabinClass.ECONOMY: 450, CabinClass.BUSINESS: 1200, CabinClass.FIRST: 2500},
    "transatlantic": {CabinClass.ECONOMY: 800, CabinClass.BUSINESS: 4500, CabinClass.FIRST: 9000},
    "transpacific": {CabinClass.ECONOMY: 900, CabinClass.BUSINESS: 6000, CabinClass.FIRST: 12000},
}

# Airport region mapping
US_AIRPORTS = {"JFK", "LAX", "SFO", "ORD", "DFW", "MIA", "SEA", "BOS", "ATL", "DEN", "IAH", "PHX", "EWR", "LGA", "DCA", "IAD"}
HAWAII_AIRPORTS = {"HNL", "OGG", "LIH", "KOA"}
EUROPE_AIRPORTS = {"LHR", "CDG", "FRA", "AMS", "FCO", "MAD", "MUC", "BCN", "DUB", "ZRH", "VIE", "CPH"}
ASIA_AIRPORTS = {"NRT", "HND", "HKG", "SIN", "ICN", "PVG", "BKK", "TPE", "KUL", "MNL", "DEL", "BOM"}

# Airlines with flight info
AIRLINES = {
    "aa": ("AA", "American Airlines", ["737", "777", "787"]),
    "united": ("UA", "United Airlines", ["737", "777", "787", "A350"]),
    "delta": ("DL", "Delta Air Lines", ["737", "767", "A330", "A350"]),
    "alaska": ("AS", "Alaska Airlines", ["737", "E175"]),
    "aeroplan": ("AC", "Air Canada", ["737", "777", "787", "A330"]),
    "ana": ("NH", "ANA", ["777", "787", "A380"]),
    "ba_avios": ("BA", "British Airways", ["777", "787", "A380", "A350"]),
}


def get_route_type(origin: str, destination: str) -> str:
    """Determine route type based on airports."""
    origin = origin.upper()
    destination = destination.upper()

    # Hawaii routes
    if (origin in US_AIRPORTS and destination in HAWAII_AIRPORTS) or \
       (origin in HAWAII_AIRPORTS and destination in US_AIRPORTS):
        return "hawaii"

    # Transatlantic
    if (origin in US_AIRPORTS and destination in EUROPE_AIRPORTS) or \
       (origin in EUROPE_AIRPORTS and destination in US_AIRPORTS):
        return "transatlantic"

    # Transpacific
    if (origin in US_AIRPORTS and destination in ASIA_AIRPORTS) or \
       (origin in ASIA_AIRPORTS and destination in US_AIRPORTS):
        return "transpacific"

    # Default to domestic
    return "domestic"


def get_flight_duration(route_type: str) -> int:
    """Get typical flight duration in minutes."""
    durations = {
        "domestic": random.randint(120, 300),
        "hawaii": random.randint(300, 420),
        "transatlantic": random.randint(420, 600),
        "transpacific": random.randint(600, 900),
    }
    return durations.get(route_type, 180)


@register_scraper("demo")
class DemoScraper(BaseScraper):
    """Demo scraper that returns realistic sample award data."""

    PROGRAM_CODE = "demo"
    PROGRAM_NAME = "Demo Data"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.enabled = True

    async def search_awards(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> list[Award]:
        """Generate realistic demo award data."""
        if not self.enabled:
            return []

        route_type = get_route_type(origin, destination)
        awards_data = AWARD_CHARTS.get(route_type, AWARD_CHARTS["domestic"])
        cabin_awards = awards_data.get(cabin, [])

        awards = []
        for miles, program in cabin_awards:
            # Random availability (some programs might not have space)
            if random.random() < 0.7:  # 70% chance of availability
                award = self._create_demo_award(
                    origin=origin,
                    destination=destination,
                    date=date,
                    cabin=cabin,
                    miles=miles,
                    program=program,
                    route_type=route_type,
                )
                awards.append(award)

        return awards

    def _create_demo_award(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
        miles: int,
        program: str,
        route_type: str,
    ) -> Award:
        """Create a demo award with realistic data."""
        airline_info = AIRLINES.get(program, ("XX", "Demo Airline", ["737"]))
        airline_code, airline_name, aircraft_types = airline_info

        # Generate flight details
        flight_no = f"{airline_code}{random.randint(100, 999)}"
        duration = get_flight_duration(route_type)

        # Random departure time
        hour = random.randint(6, 22)
        minute = random.choice([0, 15, 30, 45])
        departure = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        arrival = departure + timedelta(minutes=duration)

        # Fees vary by program
        fees = {
            "aa": random.uniform(5, 50),
            "united": random.uniform(5, 50),
            "delta": random.uniform(5, 50),
            "alaska": random.uniform(5, 50),
            "aeroplan": random.uniform(50, 200),
            "ana": random.uniform(50, 150),
            "ba_avios": random.uniform(200, 600),  # BA has high fees
        }
        cash_fees = fees.get(program, 50)

        # Saver vs standard
        is_saver = random.random() < 0.4  # 40% chance of saver

        # Amenities based on cabin
        amenities = FlightAmenities(
            wifi=random.random() < 0.8,
            lie_flat=cabin in [CabinClass.BUSINESS, CabinClass.FIRST],
            direct_aisle_access=cabin == CabinClass.FIRST or (cabin == CabinClass.BUSINESS and random.random() < 0.7),
            lounge_access=cabin in [CabinClass.BUSINESS, CabinClass.FIRST],
            meal_service=cabin != CabinClass.ECONOMY or route_type in ["transatlantic", "transpacific"],
            entertainment=True,
        )

        flight = Flight(
            flight_no=flight_no,
            airline_code=airline_code,
            airline_name=airline_name,
            origin=origin.upper(),
            destination=destination.upper(),
            departure=departure,
            arrival=arrival,
            duration_minutes=duration,
            aircraft=random.choice(aircraft_types),
            amenities=amenities,
            stops=0 if random.random() < 0.6 else 1,
        )

        # Program names
        program_names = {
            "aa": "American AAdvantage",
            "united": "United MileagePlus",
            "delta": "Delta SkyMiles",
            "alaska": "Alaska Mileage Plan",
            "aeroplan": "Air Canada Aeroplan",
            "ana": "ANA Mileage Club",
            "ba_avios": "British Airways Avios",
        }

        return Award(
            flight=flight,
            program=program,
            program_name=program_names.get(program, program),
            miles=miles,
            cash_fees=round(cash_fees, 2),
            cabin=cabin,
            booking_class="I" if is_saver else "Z",
            is_saver=is_saver,
            availability=random.randint(1, 4),
            scraped_at=datetime.now(),
            source="demo",
        )


def get_demo_cash_price(origin: str, destination: str, cabin: CabinClass) -> float:
    """Get demo cash price for CPP calculation."""
    route_type = get_route_type(origin, destination)
    prices = CASH_PRICES.get(route_type, CASH_PRICES["domestic"])
    base_price = prices.get(cabin, 500)
    # Add some variance
    return base_price * random.uniform(0.8, 1.3)
