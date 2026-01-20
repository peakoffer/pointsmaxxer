from __future__ import annotations

"""Price drop detection and alerting for PointsMaxxer."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .models import Award, CabinClass


@dataclass
class PriceDrop:
    """Represents a detected price drop."""

    origin: str
    destination: str
    program: str
    cabin: CabinClass
    departure_date: datetime
    old_miles: int
    new_miles: int
    drop_amount: int
    drop_percent: float
    is_saver_now: bool
    detected_at: datetime
    flight_no: Optional[str] = None
    airline_name: Optional[str] = None

    @property
    def is_significant(self) -> bool:
        """Check if the drop is significant (>= 10% or >= 5000 miles)."""
        return self.drop_percent >= 10.0 or self.drop_amount >= 5000

    @property
    def is_major(self) -> bool:
        """Check if the drop is major (>= 25% or >= 15000 miles)."""
        return self.drop_percent >= 25.0 or self.drop_amount >= 15000

    @property
    def summary(self) -> str:
        """Get a human-readable summary."""
        return (
            f"{self.origin}→{self.destination} on {self.program.upper()}: "
            f"{self.old_miles:,} → {self.new_miles:,} miles "
            f"(-{self.drop_amount:,}, {self.drop_percent:.0f}% off)"
        )


class PriceDropDetector:
    """Detects price drops by comparing current vs historical award prices."""

    def __init__(
        self,
        min_drop_percent: float = 10.0,
        min_drop_miles: int = 5000,
        lookback_days: int = 14,
    ):
        """Initialize the detector.

        Args:
            min_drop_percent: Minimum percentage drop to trigger alert.
            min_drop_miles: Minimum absolute miles drop to trigger alert.
            lookback_days: How far back to look for previous prices.
        """
        self.min_drop_percent = min_drop_percent
        self.min_drop_miles = min_drop_miles
        self.lookback_days = lookback_days

    def detect_drop(
        self,
        current_award: Award,
        historical_miles: int,
    ) -> Optional[PriceDrop]:
        """Compare current award price against historical and detect drops.

        Args:
            current_award: The current award pricing.
            historical_miles: Previous miles price for the same route/program/cabin.

        Returns:
            PriceDrop if a significant drop is detected, None otherwise.
        """
        if historical_miles <= current_award.miles:
            # No drop or price increased
            return None

        drop_amount = historical_miles - current_award.miles
        drop_percent = (drop_amount / historical_miles) * 100

        # Check if drop meets thresholds
        if drop_percent < self.min_drop_percent and drop_amount < self.min_drop_miles:
            return None

        return PriceDrop(
            origin=current_award.flight.origin,
            destination=current_award.flight.destination,
            program=current_award.program,
            cabin=current_award.cabin,
            departure_date=current_award.flight.departure,
            old_miles=historical_miles,
            new_miles=current_award.miles,
            drop_amount=drop_amount,
            drop_percent=drop_percent,
            is_saver_now=current_award.is_saver,
            detected_at=datetime.now(),
            flight_no=current_award.flight.flight_no,
            airline_name=current_award.flight.airline_name,
        )

    def detect_drops_batch(
        self,
        current_awards: list[Award],
        historical_data: dict[str, int],
    ) -> list[PriceDrop]:
        """Detect price drops for multiple awards.

        Args:
            current_awards: List of current award prices.
            historical_data: Dict mapping route keys to historical miles.
                Key format: "{origin}:{destination}:{program}:{cabin}:{date}"

        Returns:
            List of detected price drops.
        """
        drops = []

        for award in current_awards:
            key = self._make_key(award)
            if key in historical_data:
                drop = self.detect_drop(award, historical_data[key])
                if drop:
                    drops.append(drop)

        # Sort by drop percentage descending
        drops.sort(key=lambda d: d.drop_percent, reverse=True)
        return drops

    def _make_key(self, award: Award) -> str:
        """Create a lookup key for an award."""
        date_str = award.flight.departure.strftime("%Y-%m-%d")
        return f"{award.flight.origin}:{award.flight.destination}:{award.program}:{award.cabin.value}:{date_str}"


class PriceDropTracker:
    """Tracks and manages price drop alerts using the database."""

    def __init__(self, db):
        """Initialize with a database connection.

        Args:
            db: Database instance from database.py
        """
        self.db = db
        self.detector = PriceDropDetector()

    def get_historical_prices(
        self,
        origin: str,
        destination: str,
        program: str,
        cabin: CabinClass,
        departure_date: datetime,
        lookback_days: int = 14,
    ) -> list[tuple[int, datetime]]:
        """Get historical award prices for a route.

        Returns list of (miles, scraped_at) tuples.
        """
        from sqlalchemy import and_
        from .database import AwardRecord

        session = self.db.Session()
        try:
            cutoff = datetime.now() - timedelta(days=lookback_days)
            date_str = departure_date.strftime("%Y-%m-%d")

            # Query for historical awards matching the criteria
            records = session.query(AwardRecord).filter(
                and_(
                    AwardRecord.origin == origin,
                    AwardRecord.destination == destination,
                    AwardRecord.program == program,
                    AwardRecord.cabin == cabin.value,
                    AwardRecord.scraped_at >= cutoff,
                )
            ).order_by(AwardRecord.scraped_at.desc()).all()

            # Filter by departure date (same day)
            results = []
            for r in records:
                if r.departure.strftime("%Y-%m-%d") == date_str:
                    results.append((r.miles, r.scraped_at))

            return results
        finally:
            session.close()

    def get_best_historical_price(
        self,
        origin: str,
        destination: str,
        program: str,
        cabin: CabinClass,
        departure_date: datetime,
        lookback_days: int = 14,
    ) -> Optional[int]:
        """Get the lowest historical price we've seen (to compare against current).

        For price drop detection, we want to compare against the HIGHEST
        recent price to show the drop.
        """
        prices = self.get_historical_prices(
            origin, destination, program, cabin, departure_date, lookback_days
        )

        if not prices:
            return None

        # Return the highest price we've seen (to show max drop)
        return max(p[0] for p in prices)

    def check_for_drops(
        self,
        current_awards: list[Award],
        lookback_days: int = 14,
    ) -> list[PriceDrop]:
        """Check a list of current awards for price drops.

        Args:
            current_awards: List of currently available awards.
            lookback_days: How far back to check for price history.

        Returns:
            List of detected price drops.
        """
        drops = []

        for award in current_awards:
            historical_max = self.get_best_historical_price(
                origin=award.flight.origin,
                destination=award.flight.destination,
                program=award.program,
                cabin=award.cabin,
                departure_date=award.flight.departure,
                lookback_days=lookback_days,
            )

            if historical_max:
                drop = self.detector.detect_drop(award, historical_max)
                if drop:
                    drops.append(drop)

        # Sort by drop percentage
        drops.sort(key=lambda d: d.drop_percent, reverse=True)
        return drops

    def get_recent_drops(
        self,
        limit: int = 20,
        min_drop_percent: float = 10.0,
    ) -> list[PriceDrop]:
        """Get recently detected price drops from deal history.

        Compares recent deals against older deals to find drops.
        """
        from sqlalchemy import desc
        from .database import DealRecord

        session = self.db.Session()
        try:
            # Get recent deals grouped by route/program
            recent = session.query(DealRecord).order_by(
                desc(DealRecord.created_at)
            ).limit(500).all()

            # Group by route key
            route_prices: dict[str, list[tuple[int, datetime]]] = {}
            for deal in recent:
                key = f"{deal.origin}:{deal.destination}:{deal.program}:{deal.cabin}"
                if key not in route_prices:
                    route_prices[key] = []
                route_prices[key].append((deal.miles, deal.created_at))

            # Find drops within each route
            drops = []
            for key, prices in route_prices.items():
                if len(prices) < 2:
                    continue

                # Sort by date (newest first)
                prices.sort(key=lambda x: x[1], reverse=True)
                current_miles, current_date = prices[0]

                # Find max older price
                older_prices = [p[0] for p in prices[1:]]
                if not older_prices:
                    continue

                max_older = max(older_prices)
                if max_older <= current_miles:
                    continue

                drop_amount = max_older - current_miles
                drop_percent = (drop_amount / max_older) * 100

                if drop_percent >= min_drop_percent:
                    parts = key.split(":")
                    drops.append(PriceDrop(
                        origin=parts[0],
                        destination=parts[1],
                        program=parts[2],
                        cabin=CabinClass(parts[3]),
                        departure_date=current_date,  # Use detection date as proxy
                        old_miles=max_older,
                        new_miles=current_miles,
                        drop_amount=drop_amount,
                        drop_percent=drop_percent,
                        is_saver_now=False,
                        detected_at=current_date,
                    ))

            # Sort and limit
            drops.sort(key=lambda d: d.drop_percent, reverse=True)
            return drops[:limit]

        finally:
            session.close()


def format_price_drop_alert(drop: PriceDrop) -> str:
    """Format a price drop for terminal display."""
    severity = "MAJOR" if drop.is_major else "SIGNIFICANT"
    saver_badge = " [SAVER]" if drop.is_saver_now else ""

    return f"""
[bold yellow]{'=' * 60}[/]
[bold white]PRICE DROP ALERT - {severity}{saver_badge}[/]
[bold yellow]{'=' * 60}[/]

[bold cyan]Route:[/]      {drop.origin} → {drop.destination}
[bold cyan]Program:[/]    {drop.program.upper()}
[bold cyan]Cabin:[/]      {drop.cabin.value.title()}
[bold cyan]Date:[/]       {drop.departure_date.strftime('%b %d, %Y')}

[bold green]Price Drop:[/]
  Was:       {drop.old_miles:>10,} miles
  Now:       {drop.new_miles:>10,} miles
  Savings:   {drop.drop_amount:>10,} miles ({drop.drop_percent:.0f}% off!)

[dim]Detected: {drop.detected_at.strftime('%Y-%m-%d %H:%M')}[/]
"""
