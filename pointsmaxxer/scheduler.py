from __future__ import annotations

"""Scheduler for automated award scanning in PointsMaxxer."""

import asyncio
from datetime import datetime, timedelta
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console

from .models import AppConfig, ScanFrequency, CabinClass, Deal
from .config import load_config
from .database import Database
from .portfolio import PortfolioManager
from .analyzer import DealAnalyzer, AlertManager
from .scrapers.base import ScraperRegistry
from .scrapers.google_flights import GoogleFlightsScraper, get_fallback_price


console = Console()


class ScanResult:
    """Result of a scan operation."""

    def __init__(self):
        self.awards_found: int = 0
        self.deals_found: int = 0
        self.unicorns_found: int = 0
        self.errors: list[str] = []
        self.unicorn_deals: list[Deal] = []
        self.started_at: datetime = datetime.now()
        self.completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> float:
        """Get scan duration in seconds."""
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()


class AwardScanner:
    """Scans for award availability across configured routes."""

    def __init__(
        self,
        config: AppConfig,
        db: Optional[Database] = None,
        on_unicorn: Optional[Callable[[Deal], None]] = None,
    ):
        """Initialize award scanner.

        Args:
            config: Application configuration.
            db: Database instance. Created if not provided.
            on_unicorn: Callback when unicorn deal is found.
        """
        self.config = config
        self.db = db or Database()
        self.portfolio = PortfolioManager(config)
        self.analyzer = DealAnalyzer(config, self.portfolio)
        self.alert_manager = AlertManager(config)
        self.on_unicorn = on_unicorn
        self._cash_price_scraper: Optional[GoogleFlightsScraper] = None

    async def scan_all_routes(self) -> ScanResult:
        """Scan all configured routes.

        Returns:
            ScanResult with summary of findings.
        """
        result = ScanResult()

        console.print(f"[bold blue]Starting scan of {len(self.config.routes)} routes...[/]")

        for route in self.config.routes:
            try:
                # Skip wildcard destinations for now
                if route.is_wildcard_destination():
                    continue

                route_result = await self._scan_route(
                    origin=route.origin,
                    destination=route.destination,
                    cabin=route.cabin,
                )

                result.awards_found += route_result.awards_found
                result.deals_found += route_result.deals_found
                result.unicorns_found += route_result.unicorns_found
                result.unicorn_deals.extend(route_result.unicorn_deals)
                result.errors.extend(route_result.errors)

            except Exception as e:
                result.errors.append(f"Error scanning {route.origin}-{route.destination}: {e}")

        result.completed_at = datetime.now()

        # Log search to history
        for route in self.config.routes:
            if not route.is_wildcard_destination():
                self.db.log_search(
                    origin=route.origin,
                    destination=route.destination,
                    cabin=route.cabin,
                    date_start=datetime.now(),
                    date_end=datetime.now() + timedelta(days=self.config.settings.search_window_days),
                    awards_found=result.awards_found,
                    unicorns_found=result.unicorns_found,
                )

        return result

    async def _scan_route(
        self,
        origin: str,
        destination: str,
        cabin: CabinClass,
    ) -> ScanResult:
        """Scan a single route across all programs.

        Args:
            origin: Origin airport.
            destination: Destination airport.
            cabin: Cabin class.

        Returns:
            ScanResult for this route.
        """
        result = ScanResult()

        console.print(f"  Scanning {origin} → {destination} ({cabin.value})...")

        # Calculate date range
        start_date = datetime.now()
        end_date = start_date + timedelta(days=self.config.settings.search_window_days)

        # Get cash price for comparison
        cash_price = await self._get_cash_price(origin, destination, start_date, cabin)

        # Scan each registered scraper
        scrapers = ScraperRegistry.get_all()

        for program_code, scraper_class in scrapers.items():
            if program_code == "google_flights":
                continue  # Skip cash price scraper

            try:
                async with scraper_class() as scraper:
                    awards = await scraper.search_awards(
                        origin=origin,
                        destination=destination,
                        date=start_date,
                        cabin=cabin,
                    )

                    for award in awards:
                        result.awards_found += 1

                        # Save award to database
                        award_id = self.db.save_award(award)

                        # Analyze deal
                        deal = self.analyzer.analyze_award(award, cash_price)
                        result.deals_found += 1

                        if deal.is_unicorn:
                            result.unicorns_found += 1
                            result.unicorn_deals.append(deal)

                            # Save deal to database
                            self.db.save_deal(deal, award_id)

                            # Trigger callback
                            if self.on_unicorn:
                                self.on_unicorn(deal)

                            # Print alert
                            if self.config.alerts.terminal:
                                alert_text = self.alert_manager.format_terminal_alert(deal)
                                console.print(f"\n[bold yellow]{alert_text}[/]\n")

            except Exception as e:
                result.errors.append(f"{program_code}: {e}")

        result.completed_at = datetime.now()
        return result

    async def _get_cash_price(
        self,
        origin: str,
        destination: str,
        date: datetime,
        cabin: CabinClass,
    ) -> float:
        """Get cash price for a route.

        Attempts to scrape from Google Flights, falls back to estimates.
        """
        try:
            if self._cash_price_scraper is None:
                self._cash_price_scraper = GoogleFlightsScraper()

            price = await self._cash_price_scraper.get_cash_price(
                origin=origin,
                destination=destination,
                date=date,
                cabin=cabin,
            )

            if price:
                return price

        except Exception:
            pass

        # Fallback to estimate
        return get_fallback_price(origin, destination, cabin)

    async def close(self) -> None:
        """Cleanup resources."""
        if self._cash_price_scraper:
            await self._cash_price_scraper.close()


class DaemonScheduler:
    """Schedules and runs automated award scans."""

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        on_unicorn: Optional[Callable[[Deal], None]] = None,
    ):
        """Initialize daemon scheduler.

        Args:
            config: Application configuration. Loaded from file if not provided.
            on_unicorn: Callback when unicorn deal is found.
        """
        self.config = config or load_config()
        self.on_unicorn = on_unicorn
        self._scheduler = AsyncIOScheduler()
        self._scanner: Optional[AwardScanner] = None
        self._running = False

    def _get_cron_trigger(self) -> CronTrigger:
        """Get cron trigger based on scan frequency."""
        frequency = self.config.settings.scan_frequency

        if frequency == ScanFrequency.HOURLY:
            return CronTrigger(minute=0)  # Every hour on the hour
        elif frequency == ScanFrequency.TWICE_DAILY:
            return CronTrigger(hour="6,18", minute=0)  # 6 AM and 6 PM
        else:  # DAILY
            return CronTrigger(hour=6, minute=0)  # 6 AM daily

    async def _run_scan(self) -> None:
        """Run a scan job."""
        if self._scanner is None:
            self._scanner = AwardScanner(
                config=self.config,
                on_unicorn=self.on_unicorn,
            )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        console.print(f"\n[dim][{timestamp}] Running scheduled scan...[/]")

        try:
            result = await self._scanner.scan_all_routes()

            console.print(
                f"[dim][{timestamp}] Scan complete: "
                f"{result.awards_found} awards, "
                f"{result.deals_found} deals, "
                f"{result.unicorns_found} unicorns "
                f"({result.duration_seconds:.1f}s)[/]"
            )

            if result.errors:
                console.print(f"[dim red]  Errors: {len(result.errors)}[/]")

        except Exception as e:
            console.print(f"[red]Scan error: {e}[/]")

    def start(self) -> None:
        """Start the daemon scheduler."""
        if self._running:
            return

        trigger = self._get_cron_trigger()
        self._scheduler.add_job(
            self._run_scan,
            trigger=trigger,
            id="award_scan",
            name="Award Availability Scan",
        )

        self._scheduler.start()
        self._running = True

        frequency = self.config.settings.scan_frequency.value
        console.print(f"[green]Daemon started. Scanning {frequency}.[/]")
        console.print("[dim]Press Ctrl+C to stop.[/]")

    def stop(self) -> None:
        """Stop the daemon scheduler."""
        if not self._running:
            return

        self._scheduler.shutdown()
        self._running = False
        console.print("[yellow]Daemon stopped.[/]")

    async def run_once(self) -> ScanResult:
        """Run a single scan immediately.

        Returns:
            ScanResult with summary.
        """
        if self._scanner is None:
            self._scanner = AwardScanner(
                config=self.config,
                on_unicorn=self.on_unicorn,
            )

        return await self._scanner.scan_all_routes()

    async def run_forever(self) -> None:
        """Run the daemon until interrupted."""
        self.start()

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self.stop()

    async def close(self) -> None:
        """Cleanup resources."""
        self.stop()
        if self._scanner:
            await self._scanner.close()
