from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import STATUS_HELD, STATUS_RELEASED, Hall, SeatHold, Showtime
from app.services.hold_expiry import active_holds


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    db = TestingSession()
    hall = Hall(name="测试厅", rows=1, cols=4, aisle_cols="")
    db.add(hall)
    db.flush()
    st = Showtime(
        hall_id=hall.id,
        film_title="测试片",
        start_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(st)
    db.flush()
    db.commit()
    try:
        yield db, st
    finally:
        db.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    db, _ = db_session

    def _override():
        # 复用同一内存库连接（StaticPool），独立 Session 保证走真实请求链路。
        TestingSession = sessionmaker(bind=db.bind)
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    # 不用 with TestClient(...)，避免触发 lifespan 去连接真实 Postgres。
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_hold(db, st, *, expires_offset, code="SB-2001", **kw):
    now = datetime.utcnow()
    hold = SeatHold(
        showtime_id=st.id,
        order_code=code,
        row=kw.get("row", 1),
        start_col=kw.get("start_col", 1),
        end_col=kw.get("end_col", 3),
        party_size=kw.get("party_size", 3),
        status=STATUS_HELD,
        created_at=now + expires_offset - timedelta(minutes=10),
        expires_at=now + expires_offset,
    )
    db.add(hold)
    db.commit()
    db.refresh(hold)
    return hold


def test_active_holds_excludes_expired_even_before_scan(db_session):
    db, st = db_session
    dirty = _make_hold(db, st, expires_offset=timedelta(minutes=-1), code="SB-DIRTY")
    fresh = _make_hold(
        db, st, expires_offset=timedelta(minutes=9), code="SB-FRESH", start_col=4, end_col=4, party_size=1
    )
    active = active_holds(db, showtime_id=st.id)
    assert {h.id for h in active} == {fresh.id}
    # 扫描前仍是持有中状态：只有扫描才落状态
    db.refresh(dirty)
    assert dirty.status == STATUS_HELD


def test_scan_marks_expired_released_and_keeps_row(db_session, client):
    db, st = db_session
    dirty = _make_hold(db, st, expires_offset=timedelta(minutes=-1))

    res = client.post("/api/holds/release-expired")
    assert res.status_code == 200
    assert res.json() == {"showtime_id": None, "released": 1}

    db.refresh(dirty)
    assert dirty.status == STATUS_RELEASED
    assert dirty.released_at is not None
    # 主键与原排列保留，禁止物理删除
    assert db.get(SeatHold, dirty.id) is not None
    assert (dirty.row, dirty.start_col, dirty.end_col) == (1, 1, 3)


def test_seatmap_frees_cells_after_scan(db_session, client):
    db, st = db_session
    _make_hold(db, st, expires_offset=timedelta(minutes=-1))

    client.post("/api/holds/release-expired", params={"showtime_id": st.id})
    cells = client.get(f"/api/seatmap/{st.id}").json()["cells"]
    assert all(c["occupied"] is False for c in cells)


def test_new_hold_relinds_on_released_span(db_session, client):
    db, st = db_session
    dirty = _make_hold(db, st, expires_offset=timedelta(minutes=-1))
    client.post("/api/holds/release-expired")

    res = client.post("/api/holds", json={"showtime_id": st.id, "party_size": 3})
    assert res.status_code == 200, res.text
    new = res.json()
    # 一厅一排四座，最左连续块即原脏数据坐标
    assert (new["row"], new["start_col"], new["end_col"]) == (
        dirty.row,
        dirty.start_col,
        dirty.end_col,
    )
    assert new["id"] != dirty.id
    db.expire_all()  # API 用的是另一 Session，需丢弃本会话的身份映射缓存
    rows = db.scalars(select(SeatHold).order_by(SeatHold.id)).all()
    assert len(rows) == 2  # 已释放行仍在，未被覆盖或删除
    assert {r.status for r in rows} == {STATUS_HELD, STATUS_RELEASED}


def test_repeated_scan_is_idempotent(db_session, client):
    db, st = db_session
    _make_hold(db, st, expires_offset=timedelta(minutes=-1))

    first = client.post("/api/holds/release-expired").json()
    second = client.post("/api/holds/release-expired").json()
    assert first["released"] == 1
    assert second["released"] == 0
    # 不会造出第二条持座
    assert len(db.scalars(select(SeatHold)).all()) == 1


def test_scan_scoped_by_showtime(db_session):
    db, st = db_session
    hall2 = Hall(name="第二厅", rows=1, cols=4, aisle_cols="")
    db.add(hall2)
    db.flush()
    st2 = Showtime(hall_id=hall2.id, film_title="另一片", start_at=datetime.utcnow())
    db.add(st2)
    db.flush()
    db.commit()
    _make_hold(db, st, expires_offset=timedelta(minutes=-1), code="SB-A")
    _make_hold(db, st2, expires_offset=timedelta(minutes=-1), code="SB-B")

    from app.services.hold_expiry import release_expired_holds

    count = release_expired_holds(db, showtime_id=st.id)
    assert count == 1
    remaining = db.scalars(
        select(SeatHold).where(SeatHold.status == STATUS_HELD)
    ).all()
    assert [h.order_code for h in remaining] == ["SB-B"]


def test_create_hold_writes_expires_at_from_ttl(db_session, client):
    db, st = db_session
    before = datetime.utcnow()
    res = client.post("/api/holds", json={"showtime_id": st.id, "party_size": 2})
    after = datetime.utcnow()
    assert res.status_code == 200, res.text
    body = res.json()
    exp = datetime.fromisoformat(body["expires_at"])
    created = datetime.fromisoformat(body["created_at"])
    assert timedelta(seconds=599) <= exp - created <= timedelta(seconds=601)
    assert before + timedelta(seconds=599) <= exp <= after + timedelta(seconds=601)


def test_seed_plants_expired_dirty_hold_then_relockable():
    """种子埋的「已过期但仍持有中」脏数据：扫描后释放，同坐标可再落新锁座。"""
    from app.services.seed import seed_if_empty

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    seed_if_empty(db)

    dirty = db.scalars(
        select(SeatHold).where(SeatHold.order_code == "SB-1099")
    ).one()
    dirty_id = dirty.id
    coord = (dirty.showtime_id, dirty.row, dirty.start_col, dirty.end_col)
    assert dirty.status == STATUS_HELD
    assert dirty.expires_at <= datetime.utcnow()

    from app.services.hold_expiry import release_expired_holds

    assert release_expired_holds(db) >= 1
    db.expire_all()
    dirty = db.get(SeatHold, dirty_id)
    assert dirty.status == STATUS_RELEASED
    assert dirty.released_at is not None
    # 行未物理删除，主键与原排列保留
    assert (dirty.showtime_id, dirty.row, dirty.start_col, dirty.end_col) == coord
    db.close()
    Base.metadata.drop_all(engine)


def test_list_holds_filter_by_status(db_session, client):
    db, st = db_session
    _make_hold(db, st, expires_offset=timedelta(minutes=-1), code="SB-OLD")
    _make_hold(
        db, st, expires_offset=timedelta(minutes=5), code="SB-NEW",
        row=1, start_col=4, end_col=4, party_size=1,
    )
    client.post("/api/holds/release-expired")

    released = client.get("/api/holds", params={"status": "released"}).json()
    held = client.get("/api/holds", params={"status": "held"}).json()
    assert [h["order_code"] for h in released] == ["SB-OLD"]
    assert [h["order_code"] for h in held] == ["SB-NEW"]
