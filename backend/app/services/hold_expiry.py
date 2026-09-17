"""持座超时释放：扫描到期持座并转为已释放，不做物理删除。

约定以 UTC 的 ``expires_at`` 为准；只有 ``status = held`` 且 ``expires_at > now``
的记录才占座，已释放行保留主键与原排列（row/start_col/end_col）供对账。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import STATUS_HELD, SeatHold


def active_holds(
    db: Session, showtime_id: int | None = None, now: datetime | None = None
) -> list[SeatHold]:
    """返回当前真正占座的持座（持有中且未到期）。"""
    now = now or datetime.utcnow()
    stmt = select(SeatHold).where(
        SeatHold.status == STATUS_HELD,
        SeatHold.expires_at > now,
    )
    if showtime_id is not None:
        stmt = stmt.where(SeatHold.showtime_id == showtime_id)
    return list(db.scalars(stmt).all())


def release_expired_holds(
    db: Session, showtime_id: int | None = None, now: datetime | None = None
) -> int:
    """把到期仍标持有中的记录批量置为已释放。

    ``showtime_id`` 为 None 时全局扫描。幂等：仅命中 ``held`` 且 ``expires_at <= now``
    的行，重复扫描返回 0，不会新增任何持座记录。返回本次释放的行数。
    """
    now = now or datetime.utcnow()
    stmt = select(SeatHold).where(
        SeatHold.status == STATUS_HELD,
        SeatHold.expires_at <= now,
    )
    if showtime_id is not None:
        stmt = stmt.where(SeatHold.showtime_id == showtime_id)
    released = 0
    for hold in db.scalars(stmt).all():
        hold.status = "released"
        hold.released_at = now
        released += 1
    if released:
        db.commit()
    return released
