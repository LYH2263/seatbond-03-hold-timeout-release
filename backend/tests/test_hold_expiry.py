"""持座超时释放：扫描改状态、座位图腾空、新锁座落原格、重复扫描幂等。"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import (
    HOLD_STATUS_HELD,
    HOLD_STATUS_RELEASED,
    Hall,
    SeatHold,
    Showtime,
)
from app.services.seed import seed_if_empty


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    return TestClient(app)


_showtime_seq = 0


def _make_showtime(db, rows=6, cols=10, aisle_cols="4,5"):
    global _showtime_seq
    _showtime_seq += 1
    hall = Hall(name=f"测试厅{_showtime_seq}", rows=rows, cols=cols, aisle_cols=aisle_cols)
    db.add(hall)
    db.flush()
    st = Showtime(hall_id=hall.id, film_title="测试片", start_at=datetime.utcnow() + timedelta(hours=2))
    db.add(st)
    db.commit()
    return st.id


def _add_hold(db, showtime_id, row, start, end, party, *, expires_offset, code, created_offset=None):
    now = datetime.utcnow()
    hold = SeatHold(
        showtime_id=showtime_id,
        order_code=code,
        row=row,
        start_col=start,
        end_col=end,
        party_size=party,
        created_at=now + (created_offset or timedelta()),
        expires_at=now + expires_offset,
    )
    db.add(hold)
    db.commit()
    db.refresh(hold)
    return hold


def _occupied_cells(client, sid):
    data = client.get(f"/api/seatmap/{sid}").json()
    return {(c["row"], c["col"]) for c in data["cells"] if c["occupied"]}


def test_scan_marks_expired_as_released(client, db_session):
    sid = _make_showtime(db_session)
    expired = _add_hold(
        db_session, sid, 1, 1, 2, 2,
        expires_offset=timedelta(minutes=-10), code="SB-X1",
        created_offset=timedelta(minutes=-15),
    )
    fresh = _add_hold(
        db_session, sid, 2, 1, 2, 2,
        expires_offset=timedelta(minutes=10), code="SB-X2",
    )

    res = client.post("/api/holds/release-scan", json={"showtime_id": sid})
    assert res.status_code == 200
    body = res.json()
    assert body["released_count"] == 1
    assert body["released_ids"] == [expired.id]

    db_session.expire_all()
    old = db_session.get(SeatHold, expired.id)
    assert old.status == HOLD_STATUS_RELEASED
    assert old.released_at is not None
    # 主键与原排列表意保留：坐标不动，行没有被删除
    assert (old.row, old.start_col, old.end_col) == (1, 1, 2)
    assert db_session.get(SeatHold, fresh.id).status == HOLD_STATUS_HELD

    held = client.get("/api/holds", params={"status": "held"}).json()
    released = client.get("/api/holds", params={"status": "released"}).json()
    assert {h["id"] for h in held} == {fresh.id}
    assert {h["id"] for h in released} == {expired.id}
    assert all("expires_at" in h for h in held + released)


def test_seatmap_cells_freed_after_release(client, db_session):
    sid = _make_showtime(db_session)
    _add_hold(db_session, sid, 1, 1, 2, 2, expires_offset=timedelta(minutes=-1), code="SB-E1")
    _add_hold(db_session, sid, 3, 3, 4, 2, expires_offset=timedelta(minutes=5), code="SB-F1")

    # 扫描（或座位图懒释放）后到期格必须腾空，未到期格继续占用
    client.post("/api/holds/release-scan", json={"showtime_id": sid})
    occupied = _occupied_cells(client, sid)
    assert (1, 1) not in occupied and (1, 2) not in occupied
    assert {(3, 3), (3, 4)}.issubset(occupied)


def test_new_lock_lands_on_released_span(client, db_session):
    sid = _make_showtime(db_session)
    old = _add_hold(db_session, sid, 1, 1, 2, 2, expires_offset=timedelta(minutes=-1), code="SB-E1")

    scan = client.post("/api/holds/release-scan", json={"showtime_id": sid}).json()
    assert scan["released_count"] == 1

    res = client.post("/api/holds", json={"showtime_id": sid, "party_size": 2, "preferred_row": 1})
    assert res.status_code == 200
    new = res.json()
    # 新锁座正好落回刚释放的同坐标
    assert (new["row"], new["start_col"], new["end_col"]) == (1, 1, 2)
    assert new["id"] != old.id
    assert new["status"] == HOLD_STATUS_HELD
    assert new["expires_at"] > res.json()["created_at"]

    db_session.expire_all()
    rows = db_session.scalars(
        select(SeatHold).where(
            SeatHold.showtime_id == sid,
            SeatHold.row == 1,
            SeatHold.start_col == 1,
            SeatHold.end_col == 2,
        )
    ).all()
    # 同一坐标两条记录：旧 released 行保留对账 + 新 held 行，而不是物理删除后重插
    assert len(rows) == 2
    assert {r.status for r in rows} == {HOLD_STATUS_HELD, HOLD_STATUS_RELEASED}
    assert {(1, 1), (1, 2)}.issubset(_occupied_cells(client, sid))


def test_repeat_scan_is_idempotent(client, db_session):
    sid = _make_showtime(db_session)
    old = _add_hold(db_session, sid, 1, 1, 2, 2, expires_offset=timedelta(minutes=-1), code="SB-E1")

    first = client.post("/api/holds/release-scan", json={"showtime_id": sid}).json()
    second = client.post("/api/holds/release-scan", json={"showtime_id": sid}).json()
    assert first["released_ids"] == [old.id]
    assert second["released_count"] == 0 and second["released_ids"] == []

    # 再占同格后扫描：新持座未到期，扫描不会造出第二条持座
    new = client.post(
        "/api/holds", json={"showtime_id": sid, "party_size": 2, "preferred_row": 1}
    ).json()
    third = client.post("/api/holds/release-scan", json={"showtime_id": sid}).json()
    assert third["released_count"] == 0

    db_session.expire_all()
    rows = db_session.scalars(select(SeatHold)).all()
    assert len(rows) == 2
    assert db_session.get(SeatHold, old.id).status == HOLD_STATUS_RELEASED
    new_row = db_session.get(SeatHold, new["id"])
    assert new_row.status == HOLD_STATUS_HELD
    assert new_row.released_at is None


def test_global_scan_releases_across_showtimes(client, db_session):
    s1 = _make_showtime(db_session)
    s2 = _make_showtime(db_session)
    h1 = _add_hold(db_session, s1, 1, 1, 1, 1, expires_offset=timedelta(minutes=-2), code="SB-G1")
    h2 = _add_hold(db_session, s2, 1, 1, 1, 1, expires_offset=timedelta(minutes=-2), code="SB-G2")

    body = client.post("/api/holds/release-scan", json={}).json()
    assert body["showtime_id"] is None
    assert set(body["released_ids"]) == {h1.id, h2.id}
    db_session.expire_all()
    assert db_session.get(SeatHold, h1.id).status == HOLD_STATUS_RELEASED
    assert db_session.get(SeatHold, h2.id).status == HOLD_STATUS_RELEASED


def test_seeded_dirty_row_released_and_reusable(client, db_session):
    # 种子脏数据：创建时间已过期但仍标持有中
    seed_if_empty(db_session)
    dirty = db_session.scalars(
        select(SeatHold).where(SeatHold.order_code == "SB-1004")
    ).one()
    s1 = dirty.showtime_id
    assert dirty.status == HOLD_STATUS_HELD
    assert dirty.expires_at <= datetime.utcnow()

    body = client.post("/api/holds/release-scan", json={"showtime_id": s1}).json()
    assert dirty.id in body["released_ids"]
    assert (1, 1) not in _occupied_cells(client, s1) and (1, 2) not in _occupied_cells(client, s1)

    res = client.post(
        "/api/holds", json={"showtime_id": s1, "party_size": 2, "preferred_row": 1}
    )
    assert res.status_code == 200
    landed = res.json()
    assert (landed["row"], landed["start_col"], landed["end_col"]) == (1, 1, 2)
    assert landed["id"] != dirty.id


def test_hold_status_filter_validation(client, db_session):
    res = client.get("/api/holds", params={"status": "bogus"})
    assert res.status_code == 400


def test_upgrade_schema_replaces_legacy_unique_constraint():
    from sqlalchemy import text

    from app.migrations import upgrade_schema

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE seat_holds ("
            "id INTEGER PRIMARY KEY, showtime_id INTEGER, order_code VARCHAR(40), "
            '"row" INTEGER, start_col INTEGER, end_col INTEGER, party_size INTEGER, '
            "status VARCHAR(20) DEFAULT 'held', created_at DATETIME)"
        ))
        # 基线时代的全列唯一约束（SQLAlchemy 在 sqlite 上建成同名唯一索引）
        conn.execute(text(
            "CREATE UNIQUE INDEX uq_hold_span ON seat_holds "
            '(showtime_id, "row", start_col, end_col)'
        ))
        conn.execute(text(
            "INSERT INTO seat_holds (id, showtime_id, order_code, \"row\", start_col, end_col, "
            "party_size, status, created_at) VALUES (1, 9, 'SB-OLD', 1, 1, 2, 2, 'held', "
            "'2020-01-01 00:00:00')"
        ))

    upgrade_schema(engine)

    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(seat_holds)")).fetchall()}
        assert {"expires_at", "released_at"} <= cols
        old_expires = conn.execute(
            text("SELECT expires_at FROM seat_holds WHERE id = 1")
        ).scalar_one()
        assert str(old_expires).startswith("2020-01-01")
        # 模拟扫描释放后同坐标写入新 held 行：旧唯一约束已不存在，不再报错
        conn.execute(text(
            "UPDATE seat_holds SET status='released' WHERE id=1"
        ))
        conn.execute(text(
            "INSERT INTO seat_holds (showtime_id, order_code, \"row\", start_col, end_col, "
            "party_size, status, created_at, expires_at) "
            "VALUES (9, 'SB-NEW', 1, 1, 2, 2, 'held', '2026-01-01 00:00:00', '2030-01-01 00:00:00')"
        ))
        # 但同一坐标仍持有中时，部分唯一索引依然拦截
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO seat_holds (showtime_id, order_code, \"row\", start_col, end_col, "
                "party_size, status, created_at, expires_at) "
                "VALUES (9, 'SB-DUP', 1, 1, 2, 2, 'held', '2026-01-02 00:00:00', '2030-01-02 00:00:00')"
            ))
