from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    database_url: str = "postgresql+psycopg2://seatbond:seatbond@localhost:5442/seatbond"
    seed_on_empty: bool = True
    # 新建持座的默认持有时长（秒），到期后扫描即释放
    hold_ttl_seconds: int = 120


settings = Settings()
