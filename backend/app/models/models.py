from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

STATUS_HELD = "held"
STATUS_RELEASED = "released"


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
    # 仅对「持有中」记录约束同一排列唯一；已释放行保留在表中供对账，可与新持座同坐标共存。
    __table_args__ = (
        Index(
            "uq_hold_span_active",
            "showtime_id",
            "row",
            "start_col",
            "end_col",
            unique=True,
            sqlite_where=text("status = 'held'"),
            postgresql_where=text("status = 'held'"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    showtime_id: Mapped[int] = mapped_column(ForeignKey("showtimes.id"))
    order_code: Mapped[str] = mapped_column(String(40))
    row: Mapped[int] = mapped_column(Integer)
    start_col: Mapped[int] = mapped_column(Integer)
    end_col: Mapped[int] = mapped_column(Integer)
    party_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_HELD)
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
