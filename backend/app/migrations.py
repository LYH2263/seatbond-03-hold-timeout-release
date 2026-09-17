"""极简幂等 DDL 升级：create_all 不会改动已存在的表，
旧库里基线的全列唯一约束 uq_hold_span 会挡住释放后同格重插，
这里把它替换成仅 held 的部分唯一索引并补齐新列。"""

from sqlalchemy import Engine, inspect, text

from app.database import engine as default_engine

_PARTIAL_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_hold_span_active "
    'ON seat_holds (showtime_id, "row", start_col, end_col) '
    "WHERE status = 'held'"
)


def upgrade_schema(engine: Engine | None = None) -> None:
    engine = engine or default_engine
    inspector = inspect(engine)
    if "seat_holds" not in inspector.get_table_names():
        return  # 全新库，create_all 已建好最新结构
    columns = {c["name"] for c in inspector.get_columns("seat_holds")}
    is_pg = engine.dialect.name == "postgresql"
    ts_type = "TIMESTAMP" if is_pg else "DATETIME"
    drop_old = (
        "ALTER TABLE seat_holds DROP CONSTRAINT IF EXISTS uq_hold_span"
        if is_pg
        else "DROP INDEX IF EXISTS uq_hold_span"
    )
    with engine.begin() as conn:
        if "expires_at" not in columns:
            conn.execute(text(f"ALTER TABLE seat_holds ADD COLUMN expires_at {ts_type}"))
            # 存量持座直接视为已到期：下次按场次交互时扫描即释放
            conn.execute(text("UPDATE seat_holds SET expires_at = created_at"))
        if "released_at" not in columns:
            conn.execute(text(f"ALTER TABLE seat_holds ADD COLUMN released_at {ts_type}"))
        conn.execute(text(drop_old))
        conn.execute(text(_PARTIAL_INDEX_SQL))
