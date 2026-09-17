from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

HOLD_STATUS_HELD = "held"
HOLD_STATUS_RELEASED = "released"
HOLD_STATUSES = (HOLD_STATUS_HELD, HOLD_STATUS_RELEASED)


class Hall(Base):
    __tablename__ = "halls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    aisle_cols: Mapped[str] = mapped_column(String(80), default="")  # comma-separated
    showtimes: Mapped[list["Showtime"]] = relationship(back_populates="hall")


class Showtime(Base):
    __tablename__ = "showtimes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    film_title: Mapped[str] = mapped_column(String(120))
    start_at: Mapped[datetime] = mapped_column(DateTime)
    hall: Mapped[Hall] = relationship(back_populates="showtimes")
    holds: Mapped[list["SeatHold"]] = relationship(back_populates="showtime")


class SeatHold(Base):
    __tablename__ = "seat_holds"
    __table_args__ = (
        # 只有「持有中」的格子占位；已释放行保留主键与原排列用于对账，
        # 因此同一坐标允许在旧记录释放后再次写入新持座。
        Index(
            "uq_hold_span_active",
            "showtime_id",
            "row",
            "start_col",
            "end_col",
            unique=True,
            postgresql_where=text("status = 'held'"),
            sqlite_where=text("status = 'held'"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    showtime_id: Mapped[int] = mapped_column(ForeignKey("showtimes.id"))
    order_code: Mapped[str] = mapped_column(String(40))
    row: Mapped[int] = mapped_column(Integer)
    start_col: Mapped[int] = mapped_column(Integer)
    end_col: Mapped[int] = mapped_column(Integer)
    party_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=HOLD_STATUS_HELD)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    showtime: Mapped[Showtime] = relationship(back_populates="holds")


class ConflictLog(Base):
    __tablename__ = "conflict_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    showtime_id: Mapped[int] = mapped_column(ForeignKey("showtimes.id"))
    party_size: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
