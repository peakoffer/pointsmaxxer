from __future__ import annotations

"""CLI interface for PointsMaxxer."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import typer
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
from .booking import generate_booking_url_from_deal


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
):
    """Search for award availability on a route."""
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

    console.print(f"\n[bold]Searching {origin} → {destination} ({cabin_class.value})[/]")
    console.print(f"[dim]Dates: {start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}[/]\n")

    # Run search
    asyncio.run(_run_search(config, origin, destination, cabin_class, start_date))


async def _run_search(
    config: AppConfig,
    origin: str,
    destination: str,
    cabin: CabinClass,
    date: datetime,
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
            from .scrapers.base import ScraperRegistry
            from .scrapers.google_flights import get_fallback_price

            all_awards = []
            cash_price = get_fallback_price(origin, destination, cabin)

            scrapers = ScraperRegistry.get_all()
            for program_code, scraper_class in scrapers.items():
                if program_code == "google_flights":
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
        booking_url = generate_booking_url_from_deal(deal)

        panel_content = f"""
[bold white]{flight.airline_name} {flight.flight_no}[/]  {flight.departure.strftime('%b %d')}  {origin}→{destination}  {flight.duration_formatted}  {cabin.value.title()}

[bold]Program      Miles      Fees       Cash Price    CPP      Status[/]
─────────────────────────────────────────────────────────────────────
{award.program:<12} {award.miles:>8,}   ${award.cash_fees:>6.0f}     ${deal.cash_price:>8,.0f}     {deal.cpp:>4.1f}     {'✓ SAVER' if award.is_saver else 'STANDARD'}
"""

        if deal.your_source_program:
            panel_content += f"\n[bold green]YOUR BEST PATH:[/] {deal.your_source_program} → {award.program} ({deal.your_cost:,}) = ${deal.value_dollars:,.0f} value"

        if booking_url:
            panel_content += f"\n\n[bold cyan]BOOK NOW:[/] {booking_url}"

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
    show_links: bool = typer.Option(False, "--links", "-k", help="Show booking links"),
):
    """View deal history."""
    db = get_db()

    deals = db.get_recent_deals(limit=limit, unicorns_only=unicorns)

    if not deals:
        console.print("[yellow]No deals found in history.[/]")
        return

    table = Table(title="Recent Deals", show_header=True)
    table.add_column("#", style="dim")
    table.add_column("Date")
    table.add_column("Route")
    table.add_column("Program")
    table.add_column("Miles", justify="right")
    table.add_column("CPP", justify="right")
    table.add_column("Unicorn")

    for idx, deal in enumerate(deals, 1):
        flight = deal.award.flight
        table.add_row(
            str(idx),
            deal.created_at.strftime("%b %d %H:%M"),
            f"{flight.origin}→{flight.destination}",
            deal.award.program,
            f"{deal.award.miles:,}",
            f"{deal.cpp:.1f}",
            "🦄" if deal.is_unicorn else "",
        )

    console.print(table)

    if show_links:
        console.print("\n[bold cyan]Booking Links:[/]")
        for idx, deal in enumerate(deals, 1):
            flight = deal.award.flight
            booking_url = generate_booking_url_from_deal(deal)
            if booking_url:
                console.print(f"  [{idx}] {flight.origin}→{flight.destination} ({deal.award.program}): {booking_url}")
            else:
                console.print(f"  [{idx}] {flight.origin}→{flight.destination}: [dim]No direct link available[/]")


# ============================================================================
# Booking Commands
# ============================================================================

@app.command()
def book(
    origin: str = typer.Argument(..., help="Origin airport code"),
    destination: str = typer.Argument(..., help="Destination airport code"),
    program: str = typer.Argument(..., help="Program code (aa, united, delta, aeroplan, alaska, ba)"),
    date: str = typer.Argument(..., help="Departure date (YYYY-MM-DD)"),
    cabin: str = typer.Option("business", "--cabin", "-c", help="Cabin class"),
):
    """Generate a booking link for an award flight."""
    from .booking import generate_booking_url
    from .models import Award, Flight, CabinClass

    try:
        cabin_class = CabinClass(cabin.lower())
    except ValueError:
        console.print(f"[red]Invalid cabin: {cabin}. Use economy, premium_economy, business, or first[/]")
        raise typer.Exit(1)

    try:
        departure = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        console.print("[red]Invalid date format. Use YYYY-MM-DD[/]")
        raise typer.Exit(1)

    # Create a minimal flight/award to generate the URL
    flight = Flight(
        flight_no="",
        airline_code=program.upper(),
        origin=origin.upper(),
        destination=destination.upper(),
        departure=departure,
        arrival=departure,
        duration_minutes=0,
    )

    award = Award(
        flight=flight,
        program=program.lower(),
        miles=0,
        cabin=cabin_class,
    )

    url = generate_booking_url(award)

    if url:
        console.print(f"\n[bold cyan]Booking Link for {program.upper()}:[/]")
        console.print(f"  {origin.upper()} → {destination.upper()} on {date} ({cabin_class.value})\n")
        console.print(f"  {url}\n")
    else:
        console.print(f"[yellow]No booking link template available for {program}[/]")
        console.print("Supported programs: aa, united, delta, aeroplan, alaska, ba")


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
