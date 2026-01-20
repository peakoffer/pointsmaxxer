from __future__ import annotations

"""Points portfolio manager for PointsMaxxer."""

from dataclasses import dataclass
from typing import Optional

from .models import AppConfig, PointsProgram, TransferPartner
from .config import TRANSFER_PARTNERS, AIRLINE_PROGRAMS


@dataclass
class TransferPath:
    """A path to transfer points to an airline program."""
    source_program: str
    source_name: str
    target_program: str
    target_name: str
    ratio: float
    points_needed: int
    points_available: int
    is_direct: bool

    @property
    def can_afford(self) -> bool:
        """Check if user has enough points for this transfer."""
        return self.points_available >= self.points_needed

    @property
    def points_after_transfer(self) -> int:
        """Calculate points received after transfer."""
        return int(self.points_needed * self.ratio)


@dataclass
class PortfolioSummary:
    """Summary of a user's points portfolio."""
    total_points: int
    total_estimated_value: float
    programs: list[PointsProgram]
    best_values: dict[str, tuple[str, float]]  # program_code -> (best_use, cpp)


class PortfolioManager:
    """Manages user's points portfolio and transfer calculations."""

    # Typical CPP values for different programs (conservative estimates)
    TYPICAL_CPP = {
        "chase_ur": 1.5,
        "amex_mr": 1.5,
        "cap_one": 1.5,
        "bilt": 1.8,
        "citi_typ": 1.5,
        "aa": 1.5,
        "united": 1.4,
        "delta": 1.2,
        "aeroplan": 1.8,
        "alaska": 1.8,
        "ba_avios": 1.5,
        "virgin_atlantic": 1.8,
        "ana": 2.0,
        "singapore": 1.8,
        "cathay": 1.6,
        "flying_blue": 1.4,
        "turkish": 1.8,
        "emirates": 1.3,
        "etihad": 1.5,
        "qantas": 1.5,
        "jal": 1.6,
        "hyatt": 2.0,
        "southwest": 1.4,
        "iberia": 1.4,
        "avianca": 1.6,
    }

    def __init__(self, config: AppConfig):
        """Initialize portfolio manager.

        Args:
            config: Application configuration containing portfolio data.
        """
        self.config = config
        self._build_transfer_graph()

    def _build_transfer_graph(self) -> None:
        """Build transfer partner graph from config."""
        self.transfer_graph: dict[str, dict[str, float]] = {}

        # Use config transfers if available, otherwise use defaults
        transfers = self.config.transfers if self.config.transfers else TRANSFER_PARTNERS

        for source, partners in transfers.items():
            self.transfer_graph[source] = {}
            if isinstance(partners, list):
                for partner_dict in partners:
                    for partner_code, ratio in partner_dict.items():
                        self.transfer_graph[source][partner_code] = ratio
            elif isinstance(partners, dict):
                for partner_code, ratio in partners.items():
                    self.transfer_graph[source][partner_code] = ratio

    def get_program_name(self, code: str) -> str:
        """Get human-readable name for a program code."""
        # First check user's portfolio
        for program in self.config.portfolio:
            if program.code == code:
                return program.name

        # Then check airline programs
        return AIRLINE_PROGRAMS.get(code, code.upper())

    def get_balance(self, program_code: str) -> int:
        """Get balance for a program."""
        for program in self.config.portfolio:
            if program.code == program_code:
                return program.balance
        return 0

    def get_total_points(self) -> int:
        """Get total points across all programs."""
        return sum(p.balance for p in self.config.portfolio)

    def get_estimated_value(self, program_code: str) -> float:
        """Get estimated dollar value of points in a program."""
        balance = self.get_balance(program_code)
        cpp = self.TYPICAL_CPP.get(program_code, 1.0)
        return (balance * cpp) / 100

    def get_total_estimated_value(self) -> float:
        """Get total estimated value across all programs."""
        total = 0.0
        for program in self.config.portfolio:
            cpp = self.TYPICAL_CPP.get(program.code, 1.0)
            total += (program.balance * cpp) / 100
        return total

    def can_transfer_to(self, source_code: str, target_code: str) -> bool:
        """Check if source can transfer to target."""
        if source_code not in self.transfer_graph:
            return False
        return target_code in self.transfer_graph[source_code]

    def get_transfer_ratio(self, source_code: str, target_code: str) -> float:
        """Get transfer ratio from source to target."""
        if not self.can_transfer_to(source_code, target_code):
            return 0.0
        return self.transfer_graph[source_code][target_code]

    def find_transfer_paths(
        self,
        target_program: str,
        miles_needed: int
    ) -> list[TransferPath]:
        """Find all ways to get points into target program.

        Args:
            target_program: The airline program code to transfer to.
            miles_needed: Number of miles needed in target program.

        Returns:
            List of possible transfer paths, sorted by points needed.
        """
        paths = []

        # Check if user has direct points in target program
        direct_balance = self.get_balance(target_program)
        if direct_balance > 0:
            paths.append(TransferPath(
                source_program=target_program,
                source_name=self.get_program_name(target_program),
                target_program=target_program,
                target_name=self.get_program_name(target_program),
                ratio=1.0,
                points_needed=miles_needed,
                points_available=direct_balance,
                is_direct=True,
            ))

        # Check transfer partners
        for program in self.config.portfolio:
            if program.code == target_program:
                continue

            if self.can_transfer_to(program.code, target_program):
                ratio = self.get_transfer_ratio(program.code, target_program)
                # Calculate how many points needed from source
                points_needed = int(miles_needed / ratio) if ratio > 0 else miles_needed

                paths.append(TransferPath(
                    source_program=program.code,
                    source_name=program.name,
                    target_program=target_program,
                    target_name=self.get_program_name(target_program),
                    ratio=ratio,
                    points_needed=points_needed,
                    points_available=program.balance,
                    is_direct=False,
                ))

        # Sort by points needed (ascending)
        paths.sort(key=lambda p: (not p.can_afford, p.points_needed))
        return paths

    def get_best_transfer_path(
        self,
        target_program: str,
        miles_needed: int
    ) -> Optional[TransferPath]:
        """Get the best (cheapest) transfer path that user can afford.

        Args:
            target_program: The airline program code to transfer to.
            miles_needed: Number of miles needed in target program.

        Returns:
            Best transfer path or None if user can't afford any path.
        """
        paths = self.find_transfer_paths(target_program, miles_needed)

        # First, try to find an affordable path
        for path in paths:
            if path.can_afford:
                return path

        # If none affordable, return the cheapest overall
        return paths[0] if paths else None

    def get_programs_that_transfer_to(self, target_program: str) -> list[str]:
        """Get list of transferable currencies that can reach target."""
        programs = []

        # Check if target program is directly owned
        if self.get_balance(target_program) > 0:
            programs.append(target_program)

        # Check transfer partners
        for source, partners in self.transfer_graph.items():
            if target_program in partners:
                if self.get_balance(source) > 0:
                    programs.append(source)

        return programs

    def get_portfolio_summary(self) -> PortfolioSummary:
        """Get a summary of the user's portfolio."""
        best_values: dict[str, tuple[str, float]] = {}

        for program in self.config.portfolio:
            # Find best use of this program's points
            best_cpp = self.TYPICAL_CPP.get(program.code, 1.0)
            best_use = "Direct redemption"

            # Check transfer partners for better value
            if program.code in self.transfer_graph:
                for partner, ratio in self.transfer_graph[program.code].items():
                    partner_cpp = self.TYPICAL_CPP.get(partner, 1.0) * ratio
                    if partner_cpp > best_cpp:
                        best_cpp = partner_cpp
                        best_use = f"→ {self.get_program_name(partner)}"

            best_values[program.code] = (best_use, best_cpp)

        return PortfolioSummary(
            total_points=self.get_total_points(),
            total_estimated_value=self.get_total_estimated_value(),
            programs=self.config.portfolio,
            best_values=best_values,
        )

    def update_balance(self, program_code: str, new_balance: int) -> bool:
        """Update balance for a program.

        Returns:
            True if program was found and updated.
        """
        for program in self.config.portfolio:
            if program.code == program_code:
                program.balance = new_balance
                return True
        return False

    def add_program(self, program: PointsProgram) -> None:
        """Add a new program to the portfolio."""
        # Check if already exists
        for existing in self.config.portfolio:
            if existing.code == program.code:
                existing.balance = program.balance
                existing.name = program.name
                return

        self.config.portfolio.append(program)

    def remove_program(self, program_code: str) -> bool:
        """Remove a program from the portfolio.

        Returns:
            True if program was found and removed.
        """
        for i, program in enumerate(self.config.portfolio):
            if program.code == program_code:
                del self.config.portfolio[i]
                return True
        return False
