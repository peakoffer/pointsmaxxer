from __future__ import annotations

"""Pydantic data models for PointsMaxxer."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class CabinClass(str, Enum):
    """Cabin class options."""
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class ScanFrequency(str, Enum):
    """Scan frequency options."""
    HOURLY = "hourly"
    TWICE_DAILY = "twice_daily"
    DAILY = "daily"


class FlightAmenities(BaseModel):
    """Amenities available on a flight."""
    wifi: bool = False
    lie_flat: bool = False
    direct_aisle_access: bool = False
    lounge_access: bool = False
    meal_service: bool = False
    entertainment: bool = False


class PointsProgram(BaseModel):
    """A points/miles program in the user's portfolio."""
    name: str = Field(..., description="Human-readable program name")
    code: str = Field(..., description="Internal code identifier")
    balance: int = Field(default=0, ge=0, description="Current points balance")
    transfer_partners: list[str] = Field(default_factory=list, description="List of transfer partner codes")
    transfer_ratio: float = Field(default=1.0, gt=0, description="Transfer ratio (e.g., 1.0 for 1:1)")


class TransferPartner(BaseModel):
    """A transfer partner with its ratio."""
    partner_code: str
    ratio: float = Field(default=1.0, gt=0)


class Route(BaseModel):
    """A route to monitor for award availability."""
    origin: str = Field(..., min_length=3, max_length=3, description="Origin airport code")
    destination: str = Field(..., description="Destination airport code or '*' for any")
    cabin: CabinClass = Field(default=CabinClass.ECONOMY)
    flexible_dates: bool = Field(default=True, description="Search +/- flexible_days")

    def is_wildcard_destination(self) -> bool:
        """Check if this route has a wildcard destination."""
        return self.destination == "*"


class Flight(BaseModel):
    """A specific flight segment."""
    flight_no: str = Field(..., description="Flight number (e.g., 'NH7')")
    airline_code: str = Field(..., description="Operating airline code")
    airline_name: str = Field(default="", description="Operating airline name")
    origin: str = Field(..., min_length=3, max_length=3)
    destination: str = Field(..., min_length=3, max_length=3)
    departure: datetime
    arrival: datetime
    duration_minutes: int = Field(..., ge=0)
    aircraft: Optional[str] = None
    amenities: FlightAmenities = Field(default_factory=FlightAmenities)
    stops: int = Field(default=0, ge=0)

    @computed_field
    @property
    def duration_formatted(self) -> str:
        """Format duration as 'Xh Ym'."""
        hours = self.duration_minutes // 60
        minutes = self.duration_minutes % 60
        return f"{hours}h{minutes:02d}m"


class Award(BaseModel):
    """An award booking opportunity."""
    id: Optional[int] = None
    flight: Flight
    program: str = Field(..., description="Program code (e.g., 'aeroplan')")
    program_name: str = Field(default="", description="Human-readable program name")
    miles: int = Field(..., gt=0, description="Miles/points required")
    cash_fees: float = Field(default=0.0, ge=0, description="Cash fees/taxes")
    cabin: CabinClass
    booking_class: Optional[str] = Field(None, description="Booking class code (e.g., 'I')")
    is_saver: bool = Field(default=False, description="Whether this is saver/lowest level award")
    availability: int = Field(default=1, ge=0, description="Number of seats available")
    scraped_at: datetime = Field(default_factory=datetime.now)
    source: str = Field(default="", description="Source of the data (scraper name)")

    @computed_field
    @property
    def total_cost_description(self) -> str:
        """Describe the total cost."""
        return f"{self.miles:,} miles + ${self.cash_fees:.2f}"


class Deal(BaseModel):
    """A calculated deal with CPP value."""
    id: Optional[int] = None
    award: Award
    cash_price: float = Field(..., gt=0, description="Cash price from Google Flights")
    cpp: float = Field(..., description="Cents per point value")
    is_unicorn: bool = Field(default=False, description="Whether CPP >= threshold")
    transferable_from: list[str] = Field(default_factory=list, description="Programs that can transfer to this")
    your_cost: Optional[int] = Field(None, description="Points cost from your portfolio")
    your_source_program: Optional[str] = Field(None, description="Which of your programs to use")
    created_at: datetime = Field(default_factory=datetime.now)

    @computed_field
    @property
    def value_dollars(self) -> float:
        """Calculate the dollar value of the redemption."""
        return (self.cpp * self.award.miles) / 100

    @computed_field
    @property
    def savings_dollars(self) -> float:
        """Calculate savings compared to cash price."""
        return self.cash_price - self.award.cash_fees


class SearchRequest(BaseModel):
    """A search request for award availability."""
    origin: str = Field(..., min_length=3, max_length=3)
    destination: str = Field(..., min_length=3, max_length=3)
    cabin: CabinClass = Field(default=CabinClass.ECONOMY)
    date_start: datetime
    date_end: datetime
    flexible_days: int = Field(default=3, ge=0)
    max_stops: int = Field(default=1, ge=0)
    programs: list[str] = Field(default_factory=list, description="Programs to search, empty for all")


class SearchResult(BaseModel):
    """Results from a search operation."""
    request: SearchRequest
    awards: list[Award] = Field(default_factory=list)
    deals: list[Deal] = Field(default_factory=list)
    cash_prices: dict[str, float] = Field(default_factory=dict, description="Cash prices by date")
    searched_at: datetime = Field(default_factory=datetime.now)
    errors: list[str] = Field(default_factory=list)


class AlertConfig(BaseModel):
    """Configuration for alerts."""
    terminal: bool = True
    email: Optional[str] = None
    slack_webhook: Optional[str] = None
    discord_webhook: Optional[str] = None


class Settings(BaseModel):
    """Application settings."""
    home_airports: list[str] = Field(default_factory=lambda: ["SFO"])
    unicorn_threshold_cpp: float = Field(default=7.0, gt=0)
    search_window_days: int = Field(default=90, gt=0)
    flexible_days: int = Field(default=3, ge=0)
    scan_frequency: ScanFrequency = Field(default=ScanFrequency.DAILY)
    max_stops: int = Field(default=1, ge=0)
    cache_ttl_hours: int = Field(default=6, gt=0)
    request_delay_seconds: float = Field(default=2.0, ge=0)
    # API keys for data sources
    seats_aero_api_key: Optional[str] = Field(default=None, description="Seats.aero API key for real award data")


class AppConfig(BaseModel):
    """Complete application configuration."""
    portfolio: list[PointsProgram] = Field(default_factory=list)
    transfers: dict[str, list[dict[str, float]]] = Field(default_factory=dict)
    routes: list[Route] = Field(default_factory=list)
    settings: Settings = Field(default_factory=Settings)
    alerts: AlertConfig = Field(default_factory=AlertConfig)

    def get_transfer_partners(self, program_code: str) -> list[TransferPartner]:
        """Get transfer partners for a given program."""
        partners = []
        if program_code in self.transfers:
            for partner_dict in self.transfers[program_code]:
                for partner_code, ratio in partner_dict.items():
                    partners.append(TransferPartner(partner_code=partner_code, ratio=ratio))
        return partners

    def get_program_by_code(self, code: str) -> Optional[PointsProgram]:
        """Get a program by its code."""
        for program in self.portfolio:
            if program.code == code:
                return program
        return None

    def get_total_points(self) -> int:
        """Get total points across all programs."""
        return sum(p.balance for p in self.portfolio)
