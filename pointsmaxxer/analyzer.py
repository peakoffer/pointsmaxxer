from __future__ import annotations

"""Deal analyzer and CPP calculator for PointsMaxxer."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import Award, Deal, CabinClass, AppConfig
from .portfolio import PortfolioManager


@dataclass
class DealRanking:
    """Ranking criteria for deals."""
    cpp_weight: float = 0.5
    savings_weight: float = 0.3
    saver_bonus: float = 0.1
    availability_weight: float = 0.1


class DealAnalyzer:
    """Analyzes award availability and calculates deal values."""

    def __init__(self, config: AppConfig, portfolio_manager: Optional[PortfolioManager] = None):
        """Initialize analyzer.

        Args:
            config: Application configuration.
            portfolio_manager: Portfolio manager instance. Created if not provided.
        """
        self.config = config
        self.portfolio = portfolio_manager or PortfolioManager(config)
        self.unicorn_threshold = config.settings.unicorn_threshold_cpp

    def calculate_cpp(self, award: Award, cash_price: float) -> float:
        """Calculate cents per point value.

        CPP = (cash_price - fees) / miles * 100

        Args:
            award: The award booking opportunity.
            cash_price: The cash price for equivalent flight.

        Returns:
            Cents per point value.
        """
        if award.miles <= 0:
            return 0.0

        value = cash_price - award.cash_fees
        if value <= 0:
            return 0.0

        return (value / award.miles) * 100

    def is_unicorn(self, cpp: float) -> bool:
        """Check if CPP qualifies as a unicorn deal."""
        return cpp >= self.unicorn_threshold

    def analyze_award(self, award: Award, cash_price: float) -> Deal:
        """Analyze an award and create a Deal object.

        Args:
            award: The award booking opportunity.
            cash_price: The cash price for equivalent flight.

        Returns:
            Deal object with calculated values.
        """
        cpp = self.calculate_cpp(award, cash_price)
        is_unicorn = self.is_unicorn(cpp)

        # Find which programs can transfer to this award's program
        transferable_from = self.portfolio.get_programs_that_transfer_to(award.program)

        # Find best path from user's portfolio
        best_path = self.portfolio.get_best_transfer_path(award.program, award.miles)

        your_cost = None
        your_source_program = None
        if best_path and best_path.can_afford:
            your_cost = best_path.points_needed
            your_source_program = best_path.source_program

        return Deal(
            award=award,
            cash_price=cash_price,
            cpp=cpp,
            is_unicorn=is_unicorn,
            transferable_from=transferable_from,
            your_cost=your_cost,
            your_source_program=your_source_program,
            created_at=datetime.now(),
        )

    def rank_deals(
        self,
        deals: list[Deal],
        ranking: Optional[DealRanking] = None
    ) -> list[Deal]:
        """Rank deals by value and relevance.

        Args:
            deals: List of deals to rank.
            ranking: Ranking criteria weights.

        Returns:
            Sorted list of deals, best first.
        """
        if not deals:
            return []

        if ranking is None:
            ranking = DealRanking()

        def score(deal: Deal) -> float:
            """Calculate composite score for a deal."""
            # Normalize CPP (assume max useful CPP is ~20)
            cpp_score = min(deal.cpp / 20, 1.0)

            # Normalize savings (assume max useful savings is $10000)
            savings_score = min(deal.savings_dollars / 10000, 1.0)

            # Saver bonus
            saver_score = 1.0 if deal.award.is_saver else 0.0

            # Availability bonus (more seats = better)
            avail_score = min(deal.award.availability / 4, 1.0)

            # Bonus for being affordable with user's points
            afford_bonus = 0.2 if deal.your_cost is not None else 0.0

            total = (
                cpp_score * ranking.cpp_weight +
                savings_score * ranking.savings_weight +
                saver_score * ranking.saver_bonus +
                avail_score * ranking.availability_weight +
                afford_bonus
            )

            return total

        return sorted(deals, key=score, reverse=True)

    def filter_deals(
        self,
        deals: list[Deal],
        min_cpp: Optional[float] = None,
        max_cpp: Optional[float] = None,
        unicorns_only: bool = False,
        affordable_only: bool = False,
        saver_only: bool = False,
        cabins: Optional[list[CabinClass]] = None,
        programs: Optional[list[str]] = None,
    ) -> list[Deal]:
        """Filter deals based on criteria.

        Args:
            deals: List of deals to filter.
            min_cpp: Minimum CPP threshold.
            max_cpp: Maximum CPP threshold.
            unicorns_only: Only return unicorn deals.
            affordable_only: Only return deals user can afford.
            saver_only: Only return saver-level awards.
            cabins: Filter by cabin class.
            programs: Filter by program codes.

        Returns:
            Filtered list of deals.
        """
        filtered = []

        for deal in deals:
            # CPP filters
            if min_cpp is not None and deal.cpp < min_cpp:
                continue
            if max_cpp is not None and deal.cpp > max_cpp:
                continue

            # Unicorn filter
            if unicorns_only and not deal.is_unicorn:
                continue

            # Affordable filter
            if affordable_only and deal.your_cost is None:
                continue

            # Saver filter
            if saver_only and not deal.award.is_saver:
                continue

            # Cabin filter
            if cabins and deal.award.cabin not in cabins:
                continue

            # Program filter
            if programs and deal.award.program not in programs:
                continue

            filtered.append(deal)

        return filtered

    def find_best_program_for_route(
        self,
        awards: list[Award],
        cash_price: float
    ) -> Optional[Deal]:
        """Find the best program to book a route through.

        Args:
            awards: List of awards for the same flight from different programs.
            cash_price: Cash price for the flight.

        Returns:
            The best deal, or None if no awards.
        """
        if not awards:
            return None

        deals = [self.analyze_award(award, cash_price) for award in awards]
        ranked = self.rank_deals(deals)

        return ranked[0] if ranked else None

    def compare_programs(
        self,
        origin: str,
        destination: str,
        cabin: CabinClass,
        awards: list[Award],
        cash_price: float
    ) -> list[dict]:
        """Compare different program options for a route.

        Args:
            origin: Origin airport code.
            destination: Destination airport code.
            cabin: Cabin class.
            awards: List of awards from different programs.
            cash_price: Cash price for comparison.

        Returns:
            List of comparison dicts sorted by value.
        """
        comparisons = []

        for award in awards:
            deal = self.analyze_award(award, cash_price)
            path = self.portfolio.get_best_transfer_path(award.program, award.miles)

            comparison = {
                "program": award.program,
                "program_name": award.program_name or self.portfolio.get_program_name(award.program),
                "miles": award.miles,
                "fees": award.cash_fees,
                "cpp": deal.cpp,
                "is_unicorn": deal.is_unicorn,
                "is_saver": award.is_saver,
                "availability": award.availability,
                "can_afford": path.can_afford if path else False,
                "source_program": path.source_program if path else None,
                "source_name": path.source_name if path else None,
                "points_needed": path.points_needed if path else None,
            }
            comparisons.append(comparison)

        # Sort by CPP descending
        comparisons.sort(key=lambda x: x["cpp"], reverse=True)
        return comparisons

    def estimate_route_value(
        self,
        origin: str,
        destination: str,
        cabin: CabinClass
    ) -> dict:
        """Estimate typical value for a route (without actual search).

        Uses historical data and typical award chart values.

        Args:
            origin: Origin airport code.
            destination: Destination airport code.
            cabin: Cabin class.

        Returns:
            Dict with estimated values.
        """
        # Typical award prices by cabin and distance
        # These are rough estimates for planning purposes
        distance_estimates = {
            # Domestic US
            ("US", "US"): {
                CabinClass.ECONOMY: (10000, 200),      # (miles, cash)
                CabinClass.BUSINESS: (25000, 600),
                CabinClass.FIRST: (50000, 1200),
            },
            # Transatlantic
            ("US", "EU"): {
                CabinClass.ECONOMY: (30000, 600),
                CabinClass.BUSINESS: (70000, 4000),
                CabinClass.FIRST: (100000, 8000),
            },
            # Transpacific
            ("US", "ASIA"): {
                CabinClass.ECONOMY: (35000, 800),
                CabinClass.BUSINESS: (85000, 6000),
                CabinClass.FIRST: (110000, 12000),
            },
        }

        # Simplified region detection
        def get_region(code: str) -> str:
            us_airports = {"SFO", "LAX", "JFK", "ORD", "DFW", "SEA", "MIA", "BOS"}
            eu_airports = {"LHR", "CDG", "FRA", "AMS", "FCO", "MAD", "MUC"}
            asia_airports = {"NRT", "HND", "HKG", "SIN", "ICN", "PVG", "BKK"}

            if code in us_airports:
                return "US"
            if code in eu_airports:
                return "EU"
            if code in asia_airports:
                return "ASIA"
            return "OTHER"

        origin_region = get_region(origin)
        dest_region = get_region(destination)

        # Find matching route type
        key = (origin_region, dest_region)
        if key not in distance_estimates:
            key = (dest_region, origin_region)
        if key not in distance_estimates:
            key = ("US", "ASIA")  # Default to transpacific

        estimates = distance_estimates.get(key, distance_estimates[("US", "ASIA")])
        cabin_data = estimates.get(cabin, estimates[CabinClass.BUSINESS])

        typical_miles, typical_cash = cabin_data
        estimated_cpp = (typical_cash / typical_miles) * 100

        return {
            "origin": origin,
            "destination": destination,
            "cabin": cabin.value,
            "typical_miles": typical_miles,
            "typical_cash_price": typical_cash,
            "estimated_cpp": estimated_cpp,
            "unicorn_threshold": self.unicorn_threshold,
            "note": "These are rough estimates. Actual values vary by date and availability.",
        }


class AlertManager:
    """Manages deal alerts."""

    def __init__(self, config: AppConfig):
        """Initialize alert manager."""
        self.config = config
        self.alerts_config = config.alerts

    def should_alert(self, deal: Deal) -> bool:
        """Check if a deal should trigger an alert."""
        return deal.is_unicorn

    def format_terminal_alert(self, deal: Deal) -> str:
        """Format a deal as a terminal alert string."""
        flight = deal.award.flight
        award = deal.award

        lines = [
            f"🦄 UNICORN: {flight.origin}→{flight.destination} {flight.departure.strftime('%b %d')} {flight.airline_name or flight.airline_code}",
            f"   {award.miles:,} {award.program} + ${award.cash_fees:.0f} = ${deal.cash_price:.0f} value ({deal.cpp:.1f} cpp)",
        ]

        if deal.your_source_program:
            source_name = deal.your_source_program
            lines.append(f"   Transfer: {source_name} → {award.program}")

        return "\n".join(lines)

    def get_pending_alerts(self, deals: list[Deal]) -> list[Deal]:
        """Get deals that should be alerted."""
        return [d for d in deals if self.should_alert(d)]
