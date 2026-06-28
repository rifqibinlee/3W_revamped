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
    raw_data_dir: str = "./data/raw"
    avatar_dir: str = "./data/avatars"
    geoserver_url: str = "http://localhost:8600/geoserver"
    # Fixed layer names the Genset/Bitcoin-mining map tools query for
    # substation/building candidates — placeholders until an admin
    # actually publishes layers with these names in GeoServer. Not
    # user-selectable in the UI by design: these tools should always
    # point at the org's one canonical substations/buildings dataset,
    # not an arbitrary layer someone happens to pick.
    geoserver_substations_layer: str = "infra:substations"
    geoserver_buildings_layer: str = "infra:buildings"

    # Vite picks a free port if its default is taken, so this covers the
    # common local-dev range rather than hardcoding one port.
    cors_origins: list[str] = [f"http://localhost:{p}" for p in range(5173, 5191)]

    # Claude is primary; Ollama is the local-dev fallback (no API key
    # needed, no cost) used automatically when anthropic_api_key is unset.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_embedding_model: str = "nomic-embed-text"


settings = Settings()
