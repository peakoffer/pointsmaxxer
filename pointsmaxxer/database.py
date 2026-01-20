from __future__ import annotations

"""SQLite database operations for PointsMaxxer."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import desc

from .models import Award, Deal, Flight, FlightAmenities, CabinClass

Base = declarative_base()


class AwardRecord(Base):
    """SQLAlchemy model for award records."""
    __tablename__ = "awards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    flight_no = Column(String(20), nullable=False)
    airline_code = Column(String(10), nullable=False)
    airline_name = Column(String(100))
    origin = Column(String(3), nullable=False)
    destination = Column(String(3), nullable=False)
    departure = Column(DateTime, nullable=False)
    arrival = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    aircraft = Column(String(50))
    stops = Column(Integer, default=0)
    amenities_json = Column(Text)

    program = Column(String(50), nullable=False)
    program_name = Column(String(100))
    miles = Column(Integer, nullable=False)
    cash_fees = Column(Float, default=0.0)
    cabin = Column(String(20), nullable=False)
    booking_class = Column(String(5))
    is_saver = Column(Boolean, default=False)
    availability = Column(Integer, default=1)
    source = Column(String(50))
    scraped_at = Column(DateTime, default=datetime.now)


class DealRecord(Base):
    """SQLAlchemy model for deal records."""
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    award_id = Column(Integer, nullable=False)
    cash_price = Column(Float, nullable=False)
    cpp = Column(Float, nullable=False)
    is_unicorn = Column(Boolean, default=False)
    transferable_from_json = Column(Text)
    your_cost = Column(Integer)
    your_source_program = Column(String(50))
    created_at = Column(DateTime, default=datetime.now)

    # Denormalized flight info for quick queries
    origin = Column(String(3), nullable=False)
    destination = Column(String(3), nullable=False)
    departure = Column(DateTime, nullable=False)
    cabin = Column(String(20), nullable=False)
    program = Column(String(50), nullable=False)
    miles = Column(Integer, nullable=False)


class CashPriceRecord(Base):
    """SQLAlchemy model for cash price records."""
    __tablename__ = "cash_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    origin = Column(String(3), nullable=False)
    destination = Column(String(3), nullable=False)
    departure_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    cabin = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    source = Column(String(50), default="google_flights")
    scraped_at = Column(DateTime, default=datetime.now)


class SearchHistoryRecord(Base):
    """SQLAlchemy model for search history."""
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    origin = Column(String(3), nullable=False)
    destination = Column(String(3), nullable=False)
    cabin = Column(String(20), nullable=False)
    date_start = Column(DateTime, nullable=False)
    date_end = Column(DateTime, nullable=False)
    awards_found = Column(Integer, default=0)
    unicorns_found = Column(Integer, default=0)
    searched_at = Column(DateTime, default=datetime.now)


class Database:
    """Database manager for PointsMaxxer."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database. Defaults to ~/.pointsmaxxer/data.db
        """
        if db_path is None:
            db_path = Path.home() / ".pointsmaxxer" / "data.db"

        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def save_award(self, award: Award) -> int:
        """Save an award to the database.

        Returns:
            The ID of the saved award.
        """
        session = self.Session()
        try:
            record = AwardRecord(
                flight_no=award.flight.flight_no,
                airline_code=award.flight.airline_code,
                airline_name=award.flight.airline_name,
                origin=award.flight.origin,
                destination=award.flight.destination,
                departure=award.flight.departure,
                arrival=award.flight.arrival,
                duration_minutes=award.flight.duration_minutes,
                aircraft=award.flight.aircraft,
                stops=award.flight.stops,
                amenities_json=award.flight.amenities.model_dump_json(),
                program=award.program,
                program_name=award.program_name,
                miles=award.miles,
                cash_fees=award.cash_fees,
                cabin=award.cabin.value,
                booking_class=award.booking_class,
                is_saver=award.is_saver,
                availability=award.availability,
                source=award.source,
                scraped_at=award.scraped_at,
            )
            session.add(record)
            session.commit()
            return record.id
        finally:
            session.close()

    def save_deal(self, deal: Deal, award_id: int) -> int:
        """Save a deal to the database.

        Returns:
            The ID of the saved deal.
        """
        session = self.Session()
        try:
            record = DealRecord(
                award_id=award_id,
                cash_price=deal.cash_price,
                cpp=deal.cpp,
                is_unicorn=deal.is_unicorn,
                transferable_from_json=json.dumps(deal.transferable_from),
                your_cost=deal.your_cost,
                your_source_program=deal.your_source_program,
                created_at=deal.created_at,
                origin=deal.award.flight.origin,
                destination=deal.award.flight.destination,
                departure=deal.award.flight.departure,
                cabin=deal.award.cabin.value,
                program=deal.award.program,
                miles=deal.award.miles,
            )
            session.add(record)
            session.commit()
            return record.id
        finally:
            session.close()

    def save_cash_price(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        cabin: CabinClass,
        price: float,
        source: str = "google_flights"
    ) -> int:
        """Save a cash price to the database."""
        session = self.Session()
        try:
            record = CashPriceRecord(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                cabin=cabin.value,
                price=price,
                source=source,
                scraped_at=datetime.now(),
            )
            session.add(record)
            session.commit()
            return record.id
        finally:
            session.close()

    def get_cash_price(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        cabin: CabinClass,
        max_age_hours: int = 24
    ) -> Optional[float]:
        """Get cached cash price if available and recent."""
        session = self.Session()
        try:
            cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
            record = session.query(CashPriceRecord).filter(
                CashPriceRecord.origin == origin,
                CashPriceRecord.destination == destination,
                CashPriceRecord.departure_date == departure_date,
                CashPriceRecord.cabin == cabin.value,
            ).order_by(desc(CashPriceRecord.scraped_at)).first()

            if record and record.scraped_at.timestamp() > cutoff:
                return record.price
            return None
        finally:
            session.close()

    def get_recent_deals(
        self,
        limit: int = 50,
        unicorns_only: bool = False,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        cabin: Optional[CabinClass] = None,
    ) -> list[Deal]:
        """Get recent deals from the database."""
        session = self.Session()
        try:
            query = session.query(DealRecord, AwardRecord).join(
                AwardRecord, DealRecord.award_id == AwardRecord.id
            )

            if unicorns_only:
                query = query.filter(DealRecord.is_unicorn == True)
            if origin:
                query = query.filter(DealRecord.origin == origin)
            if destination:
                query = query.filter(DealRecord.destination == destination)
            if cabin:
                query = query.filter(DealRecord.cabin == cabin.value)

            query = query.order_by(desc(DealRecord.created_at)).limit(limit)
            results = query.all()

            deals = []
            for deal_record, award_record in results:
                amenities = FlightAmenities.model_validate_json(
                    award_record.amenities_json or "{}"
                )
                flight = Flight(
                    flight_no=award_record.flight_no,
                    airline_code=award_record.airline_code,
                    airline_name=award_record.airline_name or "",
                    origin=award_record.origin,
                    destination=award_record.destination,
                    departure=award_record.departure,
                    arrival=award_record.arrival,
                    duration_minutes=award_record.duration_minutes,
                    aircraft=award_record.aircraft,
                    stops=award_record.stops,
                    amenities=amenities,
                )
                award = Award(
                    id=award_record.id,
                    flight=flight,
                    program=award_record.program,
                    program_name=award_record.program_name or "",
                    miles=award_record.miles,
                    cash_fees=award_record.cash_fees,
                    cabin=CabinClass(award_record.cabin),
                    booking_class=award_record.booking_class,
                    is_saver=award_record.is_saver,
                    availability=award_record.availability,
                    source=award_record.source or "",
                    scraped_at=award_record.scraped_at,
                )
                deal = Deal(
                    id=deal_record.id,
                    award=award,
                    cash_price=deal_record.cash_price,
                    cpp=deal_record.cpp,
                    is_unicorn=deal_record.is_unicorn,
                    transferable_from=json.loads(deal_record.transferable_from_json or "[]"),
                    your_cost=deal_record.your_cost,
                    your_source_program=deal_record.your_source_program,
                    created_at=deal_record.created_at,
                )
                deals.append(deal)

            return deals
        finally:
            session.close()

    def get_unicorn_deals(self, limit: int = 20) -> list[Deal]:
        """Get recent unicorn deals."""
        return self.get_recent_deals(limit=limit, unicorns_only=True)

    def log_search(
        self,
        origin: str,
        destination: str,
        cabin: CabinClass,
        date_start: datetime,
        date_end: datetime,
        awards_found: int,
        unicorns_found: int,
    ) -> None:
        """Log a search to the history."""
        session = self.Session()
        try:
            record = SearchHistoryRecord(
                origin=origin,
                destination=destination,
                cabin=cabin.value,
                date_start=date_start,
                date_end=date_end,
                awards_found=awards_found,
                unicorns_found=unicorns_found,
                searched_at=datetime.now(),
            )
            session.add(record)
            session.commit()
        finally:
            session.close()

    def get_search_history(self, limit: int = 50) -> list[dict]:
        """Get recent search history."""
        session = self.Session()
        try:
            records = session.query(SearchHistoryRecord).order_by(
                desc(SearchHistoryRecord.searched_at)
            ).limit(limit).all()

            return [
                {
                    "origin": r.origin,
                    "destination": r.destination,
                    "cabin": r.cabin,
                    "date_start": r.date_start,
                    "date_end": r.date_end,
                    "awards_found": r.awards_found,
                    "unicorns_found": r.unicorns_found,
                    "searched_at": r.searched_at,
                }
                for r in records
            ]
        finally:
            session.close()

    def clear_old_data(self, days: int = 30) -> int:
        """Clear data older than specified days.

        Returns:
            Number of records deleted.
        """
        session = self.Session()
        try:
            cutoff = datetime.now().timestamp() - (days * 24 * 3600)
            cutoff_dt = datetime.fromtimestamp(cutoff)

            deleted = 0

            # Delete old awards
            result = session.query(AwardRecord).filter(
                AwardRecord.scraped_at < cutoff_dt
            ).delete()
            deleted += result

            # Delete old deals
            result = session.query(DealRecord).filter(
                DealRecord.created_at < cutoff_dt
            ).delete()
            deleted += result

            # Delete old cash prices
            result = session.query(CashPriceRecord).filter(
                CashPriceRecord.scraped_at < cutoff_dt
            ).delete()
            deleted += result

            # Delete old search history
            result = session.query(SearchHistoryRecord).filter(
                SearchHistoryRecord.searched_at < cutoff_dt
            ).delete()
            deleted += result

            session.commit()
            return deleted
        finally:
            session.close()
