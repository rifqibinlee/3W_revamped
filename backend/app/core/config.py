from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL
    postgres_dsn: str

    # JWT — use a long random secret in production (e.g. openssl rand -hex 32)
    jwt_secret: str

    # DuckDB / local data directories (overridden in docker-compose to /app/data/*)
    duckdb_path: str = "./data/analytics.duckdb"
    parquet_dir: str = "./data/parquet"
    raw_data_dir: str = "./data/raw"
    avatar_dir:   str = "./data/avatars"

    # GeoServer (optional — only needed if the GeoServer service is running)
    geoserver_url:               str = "http://localhost:8600/geoserver"
    geoserver_admin_user:        str = "admin"
    geoserver_admin_password:    str = "geoserver"
    geoserver_substations_layer: str = "infra:substations"
    geoserver_buildings_layer:   str = "infra:buildings"

    # CORS — Vite dev server ports for local development.
    # In production nginx serves the frontend on the same origin, so CORS is not
    # required for production traffic; the list only needs to include dev origins.
    cors_origins: list[str] = [f"http://localhost:{p}" for p in range(5173, 5191)]

    # Anthropic (required for the AI agent and RAG features)
    anthropic_api_key: str | None = None
    anthropic_model:   str        = "claude-sonnet-4-6"

    # S3 — set use_real_s3=true to use AWS S3 instead of local disk.
    # On EC2 with an IAM role attached, leave aws_access_key/aws_secret_key
    # blank and credentials will be picked up from the instance metadata automatically.
    use_real_s3:    bool = False
    aws_region:     str  = "ap-southeast-1"
    aws_access_key: str  = ""
    aws_secret_key: str  = ""

    # S3 bucket and prefix layout
    s3_bucket:                str = "jejak-mappro-demo"
    s3_cell_ref_prefix:       str = "3W-data/site-coverage-params/referenceData/"
    s3_location_data_prefix:  str = "3W-data/site-coverage-params/locationData/"
    s3_network_data_prefix:   str = "3W-data/raw-network-data/"
    s3_train_excel_prefix:    str = "3W-data/train-ai-data/excel-data/"
    s3_train_pdf_prefix:      str = "3W-data/train-ai-data/pdf-data/"
    s3_processed_prefix:      str = "3W-data/processed/"


settings = Settings()
