from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_dsn: str
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str
    minio_secret_key: str
    jwt_secret: str
    duckdb_path: str = "./data/analytics.duckdb"
    parquet_dir: str = "./data/parquet"


settings = Settings()
