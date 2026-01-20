from __future__ import annotations

"""CLI interface for PointsMaxxer."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import __version__
from .config import load_config, save_config, get_config_path, AIRLINE_PROGRAMS
from .database import Database
from .models import AppConfig, CabinClass, PointsProgram, Route
from .portfolio import PortfolioManager
from .analyzer import DealAnalyzer
from .scheduler import DaemonScheduler, AwardScanner


app = typer.Typer(
    name="pointsmaxxer",
    help="Local flight points tracker - find unicorn award deals",
    no_args_is_help=True,
)

console = Console()


def get_config() -> AppConfig:
    """Load configuration."""
    return load_config()


def get_db() -> Database:
    """Get database instance."""
    return Database()


# ============================================================================
# Portfolio Commands
# ============================================================================

@app.command()
def portfolio():
    """Display your points portfolio."""
    config = get_config()
    manager = PortfolioManager(config)
    summary = manager.get_portfolio_summary()

    # Create portfolio table
    table = Table(title="Your Points Portfolio", show_header=True, header_style="bold cyan")
    table.add_column("Program", style="white")
    table.add_column("Balance", justify="right", style="green")
    table.add_column("Best Transfer Value", style="yellow")

    for program in summary.programs:
        best_use, best_cpp = summary.best_values.get(program.code, ("Direct", 1.0))
        table.add_row(
            program.name,
            f"{program.balance:,}",
            f"{best_use} ({best_cpp:.1f} cpp)"
        )

    # Add totals
    table.add_section()
    table.add_row(
        "[bold]TOTAL FIREPOWER[/]",
        f"[bold]{summary.total_points:,} pts[/]",
        f"[bold]~${summary.total_estimated_value:,.0f} value[/]"
    )

    console.print(Panel(table, border_style="blue"))


@app.command()
def add_program(
    code: str = typer.Argument(..., help="Program code (e.g., chase_ur, aa)"),
    balance: int = typer.Argument(..., help="Current points balance"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Program name"),
):
    """Add or update a points program in your portfolio."""
    config = get_config()

    # Get name from known programs or use provided
    if name is None:
        name = AIRLINE_PROGRAMS.get(code, code.upper())

    program = PointsProgram(name=name, code=code, balance=balance)
    manager = PortfolioManager(config)
    manager.add_program(program)

    save_config(config, get_config_path())
    console.print(f"[green]Added/updated {name} with {balance:,} points[/]")


@app.command()
def update_balance(
    code: str = typer.Argument(..., help="Program code"),
    balance: int = typer.Argument(..., help="New points balance"),
):
    """Update points balance for a program."""
    config = get_config()
    manager = PortfolioManager(config)

    if manager.update_balance(code, balance):
        save_config(config, get_config_path())
        console.print(f"[green]Updated {code} to {balance:,} points[/]")
    else:
        console.print(f"[red]Program '{code}' not found in portfolio[/]")
        raise typer.Exit(1)


# ============================================================================
# Search Commands
# ============================================================================

@app.command()
def search(
    origin: str = typer.Argument(..., help="Origin airport code (e.g., SFO)"),
    destination: str = typer.Argument(..., help="Destination airport code (e.g., NRT)"),
    cabin: str = typer.Option("business", "--cabin", "-c", help="Cabin class: economy, premium_economy, business, first"),
    dates: Optional[str] = typer.Option(None, "--dates", "-d", help="Date range: YYYY-MM-DD:YYYY-MM-DD"),
    program: Optional[str] = typer.Option(None, "--program", "-p", help="Specific program to search"),
    live: bool = typer.Option(False, "--live", "-l", help="Use real data (requires seats.aero API key)"),
):
    """Search for award availability on a route.

    Uses demo data by default. For real award data, set your Seats.aero API key:
      - In config.yaml: seats_aero_api_key: "your-key"
      - Or env var: SEATS_AERO_API_KEY=your-key

    Then use --live flag to search real availability.
    """
    config = get_config()

    # Parse cabin
    try:
        cabin_class = CabinClass(cabin.lower())
    except ValueError:
        console.print(f"[red]Invalid cabin: {cabin}. Use economy, premium_economy, business, or first[/]")
        raise typer.Exit(1)

    # Parse dates
    if dates:
        try:
            start_str, end_str = dates.split(":")
            start_date = datetime.strptime(start_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_str, "%Y-%m-%d")
        except ValueError:
            console.print("[red]Invalid date format. Use YYYY-MM-DD:YYYY-MM-DD[/]")
            raise typer.Exit(1)
    else:
        start_date = datetime.now()
        end_date = start_date + timedelta(days=config.settings.search_window_days)

    console.print(f"\n[bold]Searching {origin.upper()} → {destination.upper()} ({cabin_class.value})[/]")
    console.print(f"[dim]Dates: {start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}[/]")

    if live and not config.settings.seats_aero_api_key:
        console.print("[yellow]No Seats.aero API key configured.[/]")
        console.print("[dim]Set via: pointsmaxxer set-api-key YOUR_KEY[/]")
        console.print("[dim]Or get a key at: https://seats.aero[/]")
        console.print("[dim]Falling back to demo data...[/]")
        live = False  # Fall back to demo
    elif not live:
        console.print("[dim]Using demo data (use --live for real searches)[/]")

    console.print()

    # Run search
    asyncio.run(_run_search(config, origin.upper(), destination.upper(), cabin_class, start_date, use_demo=not live))


async def _run_search(
    config: AppConfig,
    origin: str,
    destination: str,
    cabin: CabinClass,
    date: datetime,
    use_demo: bool = True,
):
    """Run async search."""
    scanner = AwardScanner(config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Searching...", total=None)

        try:
            all_awards = []
            cash_price = None

            # Check if we have seats.aero API key configured
            has_seats_aero = bool(config.settings.seats_aero_api_key)

            if has_seats_aero and not use_demo:
                # Use Seats.aero for real data
                from .scrapers.seats_aero import SeatsAeroScraper
                from .scrapers.google_flights import get_fallback_price

                progress.update(task, description="Searching Seats.aero...")
                try:
                    scraper = SeatsAeroScraper(api_key=config.settings.seats_aero_api_key)
                    awards = await scraper.search_all_programs(origin, destination, date, cabin)
                    all_awards.extend(awards)
                    await scraper.close()
                except Exception as e:
                    console.print(f"[yellow]Seats.aero error: {e}[/]")

                cash_price = get_fallback_price(origin, destination, cabin)

            elif use_demo:
                # Use demo scraper for realistic sample data
                from .scrapers.demo import DemoScraper, get_demo_cash_price

                progress.update(task, description="Generating award options...")
                scraper = DemoScraper()
                awards = await scraper.search_awards(origin, destination, date, cabin)
                all_awards.extend(awards)
                cash_price = get_demo_cash_price(origin, destination, cabin)
            else:
                # Use live scrapers (fallback)
                from .scrapers.base import ScraperRegistry
                from .scrapers.google_flights import get_fallback_price

                cash_price = get_fallback_price(origin, destination, cabin)

                scrapers = ScraperRegistry.get_all()
                for program_code, scraper_class in scrapers.items():
                    if program_code in ["google_flights", "demo"]:
                        continue

                    progress.update(task, description=f"Searching {program_code}...")

                    try:
                        async with scraper_class() as scraper:
                            awards = await scraper.search_awards(origin, destination, date, cabin)
                            all_awards.extend(awards)
                    except Exception:
                        pass

            progress.update(task, description="Analyzing results...")

            # Analyze deals
            analyzer = DealAnalyzer(config)
            deals = []
            for award in all_awards:
                deal = analyzer.analyze_award(award, cash_price)
                deals.append(deal)

            # Sort by CPP
            deals.sort(key=lambda d: d.cpp, reverse=True)

            progress.update(task, visible=False)

            # Display results
            _display_search_results(deals, origin, destination, cabin)

        finally:
            await scanner.close()


def _display_search_results(deals: list, origin: str, destination: str, cabin: CabinClass):
    """Display search results."""
    if not deals:
        console.print("[yellow]No award availability found.[/]")
        return

    unicorns = [d for d in deals if d.is_unicorn]
    regular = [d for d in deals if not d.is_unicorn]

    # Display unicorns first
    for deal in unicorns:
        flight = deal.award.flight
        award = deal.award

        panel_content = f"""
[bold white]{flight.airline_name} {flight.flight_no}[/]  {flight.departure.strftime('%b %d')}  {origin}→{destination}  {flight.duration_formatted}  {cabin.value.title()}

[bold]Program      Miles      Fees       Cash Price    CPP      Status[/]
─────────────────────────────────────────────────────────────────────
{award.program:<12} {award.miles:>8,}   ${award.cash_fees:>6.0f}     ${deal.cash_price:>8,.0f}     {deal.cpp:>4.1f}     {'✓ SAVER' if award.is_saver else 'STANDARD'}
"""

        if deal.your_source_program:
            panel_content += f"\n[bold green]YOUR BEST PATH:[/] {deal.your_source_program} → {award.program} ({deal.your_cost:,}) = ${deal.value_dollars:,.0f} value"

        console.print(Panel(
            panel_content.strip(),
            title="🦄 UNICORN ALERT",
            border_style="yellow",
        ))
        console.print()

    # Display regular deals in a table
    if regular:
        table = Table(title="Other Available Awards", show_header=True)
        table.add_column("Flight", style="white")
        table.add_column("Date")
        table.add_column("Program")
        table.add_column("Miles", justify="right")
        table.add_column("Fees", justify="right")
        table.add_column("CPP", justify="right")
        table.add_column("Status")

        for deal in regular[:10]:  # Show top 10
            flight = deal.award.flight
            award = deal.award
            table.add_row(
                f"{flight.airline_code}{flight.flight_no}",
                flight.departure.strftime("%b %d"),
                award.program,
                f"{award.miles:,}",
                f"${award.cash_fees:.0f}",
                f"{deal.cpp:.1f}",
                "✓ SAVER" if award.is_saver else "",
            )

        console.print(table)

    console.print(f"\n[dim]Found {len(deals)} total awards, {len(unicorns)} unicorns[/]")


@app.command()
def best(
    destination: str = typer.Argument(..., help="Destination airport code"),
    cabin: str = typer.Option("business", "--cabin", "-c", help="Cabin class"),
):
    """Find the best award option for a route from your home airports."""
    config = get_config()

    try:
        cabin_class = CabinClass(cabin.lower())
    except ValueError:
        console.print(f"[red]Invalid cabin: {cabin}[/]")
        raise typer.Exit(1)

    home_airports = config.settings.home_airports
    if not home_airports:
        console.print("[red]No home airports configured. Add them to config.yaml[/]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Finding best awards to {destination.upper()} ({cabin_class.value})[/]")
    console.print(f"[dim]From: {', '.join(home_airports)}[/]\n")

    async def find_best():
        from .scrapers.demo import DemoScraper, get_demo_cash_price

        all_deals = []
        analyzer = DealAnalyzer(config)
        scraper = DemoScraper()

        for origin in home_airports:
            awards = await scraper.search_awards(origin, destination.upper(), datetime.now(), cabin_class)
            cash_price = get_demo_cash_price(origin, destination.upper(), cabin_class)

            for award in awards:
                deal = analyzer.analyze_award(award, cash_price)
                all_deals.append((origin, deal))

        # Sort by CPP
        all_deals.sort(key=lambda x: x[1].cpp, reverse=True)

        if not all_deals:
            console.print("[yellow]No availability found.[/]")
            return

        # Show best options
        table = Table(title=f"Best Awards to {destination.upper()}", show_header=True)
        table.add_column("From")
        table.add_column("Program")
        table.add_column("Miles", justify="right")
        table.add_column("Fees", justify="right")
        table.add_column("CPP", justify="right")
        table.add_column("Value", justify="right")
        table.add_column("")

        for origin, deal in all_deals[:8]:
            award = deal.award
            is_unicorn = "🦄" if deal.is_unicorn else ""
            table.add_row(
                origin,
                award.program,
                f"{award.miles:,}",
                f"${award.cash_fees:.0f}",
                f"{deal.cpp:.1f}",
                f"${deal.value_dollars:,.0f}",
                is_unicorn,
            )

        console.print(table)

    asyncio.run(find_best())


@app.command()
def compare(
    origin: str = typer.Argument(..., help="Origin airport"),
    destination: str = typer.Argument(..., help="Destination airport"),
    cabin: str = typer.Option("business", "--cabin", "-c", help="Cabin class"),
    days: int = typer.Option(7, "--days", "-d", help="Number of days to compare"),
):
    """Compare award availability across multiple dates."""
    config = get_config()

    try:
        cabin_class = CabinClass(cabin.lower())
    except ValueError:
        console.print(f"[red]Invalid cabin: {cabin}[/]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Comparing {origin.upper()} → {destination.upper()} ({cabin_class.value})[/]")
    console.print(f"[dim]Next {days} days[/]\n")

    async def compare_dates():
        from .scrapers.demo import DemoScraper, get_demo_cash_price

        scraper = DemoScraper()
        analyzer = DealAnalyzer(config)

        table = Table(title="Award Availability by Date", show_header=True)
        table.add_column("Date")
        table.add_column("Best Program")
        table.add_column("Miles", justify="right")
        table.add_column("CPP", justify="right")
        table.add_column("Cash Price", justify="right")
        table.add_column("")

        for i in range(days):
            date = datetime.now() + timedelta(days=i)
            awards = await scraper.search_awards(origin.upper(), destination.upper(), date, cabin_class)
            cash_price = get_demo_cash_price(origin.upper(), destination.upper(), cabin_class)

            if awards:
                # Find best deal for this date
                deals = [analyzer.analyze_award(a, cash_price) for a in awards]
                best_deal = max(deals, key=lambda d: d.cpp)
                award = best_deal.award

                is_unicorn = "🦄" if best_deal.is_unicorn else ""
                table.add_row(
                    date.strftime("%a %b %d"),
                    award.program,
                    f"{award.miles:,}",
                    f"{best_deal.cpp:.1f}",
                    f"${cash_price:,.0f}",
                    is_unicorn,
                )
            else:
                table.add_row(date.strftime("%a %b %d"), "-", "-", "-", "-", "")

        console.print(table)

    asyncio.run(compare_dates())


# ============================================================================
# Watch Commands
# ============================================================================

@app.command()
def watch(
    origin: str = typer.Argument(..., help="Origin airport"),
    destination: str = typer.Argument(..., help="Destination airport"),
    cabin: str = typer.Option("business", "--cabin", "-c", help="Cabin class"),
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Target date (YYYY-MM-DD)"),
    min_cpp: float = typer.Option(0.0, "--min-cpp", help="Alert when CPP exceeds this value"),
    max_miles: Optional[int] = typer.Option(None, "--max-miles", help="Alert when miles below this value"),
):
    """Add a route to your watch list for price tracking."""
    db = get_db()

    try:
        cabin_class = CabinClass(cabin.lower())
    except ValueError:
        console.print(f"[red]Invalid cabin: {cabin}[/]")
        raise typer.Exit(1)

    target_date = None
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            console.print("[red]Invalid date format. Use YYYY-MM-DD[/]")
            raise typer.Exit(1)

    watch_id = db.add_watch(
        origin=origin,
        destination=destination,
        cabin=cabin_class,
        target_date=target_date,
        min_cpp=min_cpp,
        max_miles=max_miles,
    )

    console.print(f"[green]Watch #{watch_id} created:[/] {origin.upper()} → {destination.upper()} ({cabin})")
    if min_cpp > 0:
        console.print(f"  Alert when CPP ≥ {min_cpp}")
    if max_miles:
        console.print(f"  Alert when miles ≤ {max_miles:,}")
    if target_date:
        console.print(f"  Target date: {target_date.strftime('%b %d, %Y')}")


@app.command()
def watches():
    """List all active watches."""
    db = get_db()
    watch_list = db.get_watches(active_only=True)

    if not watch_list:
        console.print("[yellow]No active watches.[/]")
        console.print("Use 'pointsmaxxer watch SFO NRT' to add one.")
        return

    table = Table(title="Active Watches", show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("Route")
    table.add_column("Cabin")
    table.add_column("Target Date")
    table.add_column("Min CPP", justify="right")
    table.add_column("Max Miles", justify="right")
    table.add_column("Last Checked")

    for w in watch_list:
        target = w["target_date"].strftime("%b %d") if w["target_date"] else "Any"
        last_checked = w["last_checked"].strftime("%b %d %H:%M") if w["last_checked"] else "Never"
        max_miles_str = f"{w['max_miles']:,}" if w["max_miles"] else "-"
        min_cpp_str = f"{w['min_cpp']:.1f}" if w["min_cpp"] > 0 else "-"

        table.add_row(
            str(w["id"]),
            f"{w['origin']} → {w['destination']}",
            w["cabin"],
            target,
            min_cpp_str,
            max_miles_str,
            last_checked,
        )

    console.print(table)


@app.command()
def unwatch(
    watch_id: int = typer.Argument(..., help="Watch ID to remove"),
):
    """Remove a watch from your watch list."""
    db = get_db()

    if db.remove_watch(watch_id):
        console.print(f"[green]Watch #{watch_id} removed.[/]")
    else:
        console.print(f"[red]Watch #{watch_id} not found.[/]")
        raise typer.Exit(1)


@app.command()
def check_watches():
    """Check all watches for matching deals."""
    db = get_db()
    config = get_config()
    watch_list = db.get_watches(active_only=True)

    if not watch_list:
        console.print("[yellow]No active watches to check.[/]")
        return

    console.print(f"[bold]Checking {len(watch_list)} watches...[/]\n")

    async def check_all():
        from .scrapers.demo import DemoScraper, get_demo_cash_price

        scraper = DemoScraper()
        analyzer = DealAnalyzer(config)
        alerts = []

        for w in watch_list:
            cabin_class = CabinClass(w["cabin"])
            search_date = w["target_date"] or datetime.now()

            awards = await scraper.search_awards(
                w["origin"], w["destination"], search_date, cabin_class
            )
            cash_price = get_demo_cash_price(w["origin"], w["destination"], cabin_class)

            matching_deals = []
            for award in awards:
                deal = analyzer.analyze_award(award, cash_price)

                # Check if deal matches watch criteria
                meets_cpp = w["min_cpp"] <= 0 or deal.cpp >= w["min_cpp"]
                meets_miles = w["max_miles"] is None or award.miles <= w["max_miles"]

                if meets_cpp and meets_miles:
                    if w["min_cpp"] > 0 or w["max_miles"]:  # Only alert if criteria set
                        matching_deals.append(deal)

            db.update_watch_checked(w["id"], alerted=len(matching_deals) > 0)

            if matching_deals:
                alerts.append((w, matching_deals))

        return alerts

    alerts = asyncio.run(check_all())

    if alerts:
        console.print(f"[bold yellow]🔔 {len(alerts)} watches have matching deals![/]\n")

        for watch_info, deals in alerts:
            console.print(f"[bold]{watch_info['origin']} → {watch_info['destination']} ({watch_info['cabin']})[/]")
            for deal in deals[:3]:  # Show top 3
                award = deal.award
                console.print(f"  {award.program}: {award.miles:,} miles @ {deal.cpp:.1f} cpp")
            console.print()
    else:
        console.print("[green]All watches checked. No alerts triggered.[/]")


# ============================================================================
# Daemon Commands
# ============================================================================

@app.command()
def daemon():
    """Start the background scanning daemon."""
    config = get_config()

    console.print(Panel(
        f"[bold]PointsMaxxer Daemon[/]\n\n"
        f"Scanning: {config.settings.scan_frequency.value}\n"
        f"Routes: {len(config.routes)}\n"
        f"Unicorn threshold: {config.settings.unicorn_threshold_cpp}+ cpp",
        border_style="blue",
    ))

    def on_unicorn(deal):
        console.print(f"\n[bold yellow]🦄 UNICORN FOUND![/]")

    scheduler = DaemonScheduler(config, on_unicorn=on_unicorn)

    try:
        asyncio.run(scheduler.run_forever())
    except KeyboardInterrupt:
        console.print("\n[yellow]Daemon stopped.[/]")


@app.command()
def scan():
    """Run a single scan immediately."""
    config = get_config()

    console.print("[bold]Running single scan...[/]\n")

    def on_unicorn(deal):
        pass  # Alerts handled by scanner

    async def run():
        scheduler = DaemonScheduler(config, on_unicorn=on_unicorn)
        result = await scheduler.run_once()

        console.print(f"\n[bold green]Scan Complete[/]")
        console.print(f"  Awards found: {result.awards_found}")
        console.print(f"  Deals analyzed: {result.deals_found}")
        console.print(f"  Unicorns: {result.unicorns_found}")
        console.print(f"  Duration: {result.duration_seconds:.1f}s")

        if result.errors:
            console.print(f"\n[yellow]Errors ({len(result.errors)}):[/]")
            for error in result.errors[:5]:
                console.print(f"  - {error}")

        await scheduler.close()

    asyncio.run(run())


# ============================================================================
# Discovery Commands
# ============================================================================

@app.command()
def discover(
    origin: str = typer.Option(..., "--from", "-f", help="Origin airport"),
    cabin: str = typer.Option("first", "--cabin", "-c", help="Cabin class"),
    min_cpp: float = typer.Option(8.0, "--min-cpp", help="Minimum CPP threshold"),
):
    """Discover high-value routes from an airport."""
    config = get_config()
    analyzer = DealAnalyzer(config)

    console.print(f"\n[bold]Discovering high-value {cabin} routes from {origin}...[/]\n")

    try:
        cabin_class = CabinClass(cabin.lower())
    except ValueError:
        console.print(f"[red]Invalid cabin: {cabin}[/]")
        raise typer.Exit(1)

    # High-value destinations to check
    destinations = ["NRT", "HND", "LHR", "CDG", "SIN", "HKG", "FRA", "SYD", "DOH", "DXB"]

    table = Table(title=f"Top Value Routes ({min_cpp}+ CPP)", show_header=True)
    table.add_column("Route")
    table.add_column("Best Program")
    table.add_column("Typical Miles", justify="right")
    table.add_column("Typical Cash", justify="right")
    table.add_column("Est. CPP", justify="right")

    for dest in destinations:
        estimate = analyzer.estimate_route_value(origin, dest, cabin_class)

        if estimate["estimated_cpp"] >= min_cpp:
            table.add_row(
                f"{origin} → {dest}",
                "Various",
                f"{estimate['typical_miles']:,}",
                f"${estimate['typical_cash_price']:,}",
                f"{estimate['estimated_cpp']:.1f}",
            )

    console.print(table)
    console.print(f"\n[dim]Note: {estimate['note']}[/]")


# ============================================================================
# History Commands
# ============================================================================

@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of deals to show"),
    unicorns: bool = typer.Option(False, "--unicorns", "-u", help="Only show unicorns"),
):
    """View deal history."""
    db = get_db()

    deals = db.get_recent_deals(limit=limit, unicorns_only=unicorns)

    if not deals:
        console.print("[yellow]No deals found in history.[/]")
        return

    table = Table(title="Recent Deals", show_header=True)
    table.add_column("Date")
    table.add_column("Route")
    table.add_column("Program")
    table.add_column("Miles", justify="right")
    table.add_column("CPP", justify="right")
    table.add_column("Unicorn")

    for deal in deals:
        flight = deal.award.flight
        table.add_row(
            deal.created_at.strftime("%b %d %H:%M"),
            f"{flight.origin}→{flight.destination}",
            deal.award.program,
            f"{deal.award.miles:,}",
            f"{deal.cpp:.1f}",
            "🦄" if deal.is_unicorn else "",
        )

    console.print(table)


# ============================================================================
# Route Management Commands
# ============================================================================

@app.command()
def routes():
    """List monitored routes."""
    config = get_config()

    if not config.routes:
        console.print("[yellow]No routes configured.[/]")
        console.print("Use 'pointsmaxxer add-route' to add routes.")
        return

    table = Table(title="Monitored Routes", show_header=True)
    table.add_column("Origin")
    table.add_column("Destination")
    table.add_column("Cabin")
    table.add_column("Flexible")

    for route in config.routes:
        table.add_row(
            route.origin,
            route.destination,
            route.cabin.value,
            "Yes" if route.flexible_dates else "No",
        )

    console.print(table)


@app.command()
def add_route(
    origin: str = typer.Argument(..., help="Origin airport code"),
    destination: str = typer.Argument(..., help="Destination airport code (or * for any)"),
    cabin: str = typer.Option("business", "--cabin", "-c", help="Cabin class"),
):
    """Add a route to monitor."""
    config = get_config()

    try:
        cabin_class = CabinClass(cabin.lower())
    except ValueError:
        console.print(f"[red]Invalid cabin: {cabin}[/]")
        raise typer.Exit(1)

    route = Route(
        origin=origin.upper(),
        destination=destination.upper(),
        cabin=cabin_class,
        flexible_dates=True,
    )

    config.routes.append(route)
    save_config(config, get_config_path())

    console.print(f"[green]Added route: {origin} → {destination} ({cabin})[/]")


# ============================================================================
# Utility Commands
# ============================================================================

@app.command()
def status():
    """Show configuration and data source status."""
    config = get_config()
    path = get_config_path()

    console.print("\n[bold]PointsMaxxer Status[/]\n")

    # Config file
    if path.exists():
        console.print(f"  Config file: [green]{path}[/]")
    else:
        console.print(f"  Config file: [yellow]Not found (using defaults)[/]")

    # Portfolio
    total_points = sum(p.balance for p in config.portfolio)
    console.print(f"  Portfolio: [cyan]{len(config.portfolio)} programs, {total_points:,} points[/]")

    # Routes
    console.print(f"  Routes: [cyan]{len(config.routes)} monitored[/]")

    # Data sources
    console.print("\n[bold]Data Sources[/]\n")

    if config.settings.seats_aero_api_key:
        # Mask the API key for display
        key = config.settings.seats_aero_api_key
        masked = key[:4] + "..." + key[-4:] if len(key) > 8 else "****"
        console.print(f"  Seats.aero API: [green]Configured[/] ({masked})")
        console.print(f"    → Use [bold]--live[/] flag for real award searches")
    else:
        console.print(f"  Seats.aero API: [yellow]Not configured[/]")
        console.print(f"    → Get API key at [link]https://seats.aero[/link]")
        console.print(f"    → Set via: config.yaml or SEATS_AERO_API_KEY env var")

    console.print()


@app.command()
def set_api_key(
    key: str = typer.Argument(..., help="Your Seats.aero API key"),
):
    """Set your Seats.aero API key for real award data."""
    config = get_config()
    path = get_config_path()

    # Read existing config file if it exists
    if path.exists():
        with open(path, "r") as f:
            raw_config = yaml.safe_load(f) or {}
    else:
        raw_config = {}

    # Update the settings
    if "settings" not in raw_config:
        raw_config["settings"] = {}
    raw_config["settings"]["seats_aero_api_key"] = key

    # Write back
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(raw_config, f, default_flow_style=False, sort_keys=False)

    console.print(f"[green]API key saved to {path}[/]")
    console.print("You can now use [bold]pointsmaxxer search --live[/] for real data.")


@app.command()
def config_path():
    """Show configuration file path."""
    path = get_config_path()
    console.print(f"Config file: {path}")


@app.command()
def version():
    """Show version information."""
    console.print(f"PointsMaxxer v{__version__}")


@app.command()
def init():
    """Initialize configuration file."""
    path = get_config_path()

    if path.exists():
        console.print(f"[yellow]Config already exists at {path}[/]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit()

    config = AppConfig()
    save_config(config, path)
    console.print(f"[green]Created config at {path}[/]")
    console.print("Edit this file to add your points portfolio and routes.")


if __name__ == "__main__":
    app()
