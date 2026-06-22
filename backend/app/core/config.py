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

    # Claude is primary; Ollama is the local-dev fallback (no API key
    # needed, no cost) used automatically when anthropic_api_key is unset.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_embedding_model: str = "nomic-embed-text"


settings = Settings()
