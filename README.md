# PointsMaxxer

A self-hosted Python tool that tracks award flight availability, calculates cents-per-point (CPP) value across all your points programs, and alerts you to unicorn deals (7+ CPP).

## Features

- **Portfolio Management**: Track balances across all your points programs (Chase UR, Amex MR, airline miles, etc.)
- **Transfer Partner Awareness**: Automatically calculates the best transfer paths to book awards
- **CPP Calculator**: Compares award costs against cash prices to find real value
- **Unicorn Alerts**: Get notified when deals exceed 7+ CPP (configurable)
- **Multi-Program Search**: Search availability across AA, United, Delta, Aeroplan, Alaska, British Airways
- **Automated Scanning**: Run daily scans with configurable schedules
- **Rich CLI**: Beautiful terminal interface with tables and progress indicators

## Installation

```bash
# Clone or copy the project
cd pointsmaxxer

# Install dependencies
pip install -e .

# Install Playwright browsers (required for scraping)
playwright install chromium
```

## Quick Start

### 1. Initialize Configuration

```bash
pointsmaxxer init
```

This creates a `config.yaml` file. Edit it to add your points balances:

```yaml
portfolio:
  - name: Chase Ultimate Rewards
    code: chase_ur
    balance: 180000

  - name: Amex Membership Rewards
    code: amex_mr
    balance: 95000

routes:
  - origin: SFO
    destination: NRT
    cabin: business
```

### 2. View Your Portfolio

```bash
pointsmaxxer portfolio
```

Output:
```
╭─────────────────── Your Points Portfolio ───────────────────╮
│ Program                    Balance    Best Transfer Value   │
├─────────────────────────────────────────────────────────────┤
│ Chase Ultimate Rewards     180,000    → Aeroplan (2.1 cpp)  │
│ Amex Membership Rewards     95,000    → ANA (2.4 cpp)       │
├─────────────────────────────────────────────────────────────┤
│ TOTAL FIREPOWER            275,000 pts  ~$4,400 value       │
╰─────────────────────────────────────────────────────────────╯
```

### 3. Search for Awards

```bash
pointsmaxxer search SFO NRT --cabin business --dates 2024-03-01:2024-03-15
```

### 4. Run the Daemon

```bash
pointsmaxxer daemon
```

Runs automated scans according to your configured schedule.

## CLI Commands

| Command | Description |
|---------|-------------|
| `pointsmaxxer portfolio` | Display your points portfolio |
| `pointsmaxxer add-program <code> <balance>` | Add/update a program |
| `pointsmaxxer update-balance <code> <balance>` | Update points balance |
| `pointsmaxxer search <origin> <dest>` | Search for award availability |
| `pointsmaxxer scan` | Run a single scan immediately |
| `pointsmaxxer daemon` | Start the background scanner |
| `pointsmaxxer discover --from SFO` | Find high-value routes |
| `pointsmaxxer routes` | List monitored routes |
| `pointsmaxxer add-route <origin> <dest>` | Add a route to monitor |
| `pointsmaxxer history` | View deal history |
| `pointsmaxxer init` | Initialize configuration |

## Configuration

The `config.yaml` file controls all settings:

```yaml
# Your points portfolio
portfolio:
  - name: Chase Ultimate Rewards
    code: chase_ur
    balance: 180000

# Transfer partner mappings
transfers:
  chase_ur:
    - united: 1.0
    - aeroplan: 1.0

# Routes to monitor
routes:
  - origin: SFO
    destination: NRT
    cabin: business

# Settings
settings:
  home_airports: ["SFO", "OAK"]
  unicorn_threshold_cpp: 7.0
  search_window_days: 90
  scan_frequency: daily  # hourly, twice_daily, daily
  max_stops: 1

# Alerts
alerts:
  terminal: true
```

## Supported Programs

### Transferable Currencies
- Chase Ultimate Rewards (`chase_ur`)
- Amex Membership Rewards (`amex_mr`)
- Capital One Miles (`cap_one`)
- Bilt Rewards (`bilt`)
- Citi ThankYou Points (`citi_typ`)

### Airline Programs
- American AAdvantage (`aa`)
- United MileagePlus (`united`)
- Delta SkyMiles (`delta`)
- Air Canada Aeroplan (`aeroplan`)
- Alaska Mileage Plan (`alaska`)
- British Airways Avios (`ba_avios`)
- And more...

## Understanding CPP

**Cents Per Point (CPP)** measures the value you get from points:

```
CPP = (Cash Price - Taxes/Fees) / Points Required × 100
```

Example:
- Flight costs $6,200 cash
- Award: 85,000 miles + $87 fees
- CPP = ($6,200 - $87) / 85,000 × 100 = **7.2 cpp**

### Value Benchmarks
- 1.0 cpp: Baseline (credit card cashback equivalent)
- 1.5-2.0 cpp: Good value
- 2.0-4.0 cpp: Great value
- 5.0-7.0 cpp: Excellent value
- 7.0+ cpp: **Unicorn** 🦄

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run specific test file
pytest tests/test_analyzer.py -v
```

## Architecture

```
pointsmaxxer/
├── cli.py              # CLI entry point
├── config.py           # Configuration loader
├── models.py           # Pydantic data models
├── database.py         # SQLite storage
├── portfolio.py        # Points portfolio manager
├── analyzer.py         # CPP calculator & deal finder
├── scheduler.py        # Automated scan scheduler
├── scrapers/           # Airline-specific scrapers
│   ├── base.py         # Base scraper class
│   ├── aa.py           # American Airlines
│   ├── united.py       # United
│   ├── delta.py        # Delta
│   ├── aeroplan.py     # Air Canada Aeroplan
│   ├── alaska.py       # Alaska
│   ├── ba.py           # British Airways
│   └── google_flights.py  # Cash price baseline
└── utils/
    ├── browser.py      # Playwright stealth browser
    ├── mouse.py        # Human-like mouse movements
    └── cache.py        # Response caching
```

## Disclaimer

This tool is for personal use only. Be respectful of airline websites:
- Don't abuse rate limits
- Cache responses appropriately
- Use reasonable delays between requests

Award availability scraping may violate some airlines' terms of service. Use at your own risk.

## License

MIT
