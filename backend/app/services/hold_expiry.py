"""持座超时释放：扫描持有中且 expires_at 已到的记录，原地改为已释放。

释放只更新状态与 released_at，绝不物理删除行——主键与原排列
（row/start_col/end_col）保留以便对账，格子也随之对座位图与
自动连座搜索重新空闲。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import HOLD_STATUS_HELD, HOLD_STATUS_RELEASED, SeatHold


def active_holds_query(showtime_id: int | None = None, now: datetime | None = None):
    """真实占用座位的持座：状态 held 且尚未到期。

    所有读占用的地方（座位图、连座搜索、冲突判定）都必须走这里，
    这样扫描释放后格子立刻空闲，无需等待缓存刷新。
    """
    now = now or datetime.utcnow()
    q = select(SeatHold).where(
        SeatHold.status == HOLD_STATUS_HELD,
        SeatHold.expires_at > now,
    )
    if showtime_id is not None:
        q = q.where(SeatHold.showtime_id == showtime_id)
    return q


def release_expired_holds(
    db: Session,
    showtime_id: int | None = None,
    now: datetime | None = None,
) -> list[SeatHold]:
    """把到期的持有中记录置为 released。幂等：已释放的不会再被选中，
    重复扫描不会产生第二条持座，也不会重复改 released_at。

    showtime_id 为 None 时全局扫描。
    """
    now = now or datetime.utcnow()
    stmt = select(SeatHold).where(
        SeatHold.status == HOLD_STATUS_HELD,
        SeatHold.expires_at <= now,
    )
    if showtime_id is not None:
        stmt = stmt.where(SeatHold.showtime_id == showtime_id)

    released: list[SeatHold] = []
    for hold in db.scalars(stmt).all():
        hold.status = HOLD_STATUS_RELEASED
        hold.released_at = now
        released.append(hold)
    if released:
        db.commit()
    return released
