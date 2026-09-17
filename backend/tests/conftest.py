import os

# 测试一律走内存 SQLite（fixture 内自建引擎），避免导入 app 时连接 Postgres。
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_ON_EMPTY", "false")
