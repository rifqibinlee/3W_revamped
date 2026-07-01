from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_dsn: str
    jwt_secret: str
    duckdb_path: str = "./data/analytics.duckdb"
    parquet_dir: str = "./data/parquet"
    raw_data_dir: str = "./data/raw"
    avatar_dir: str = "./data/avatars"
    geoserver_url: str = "http://localhost:8600/geoserver"
    geoserver_admin_user: str = "admin"
    geoserver_admin_password: str = "geoserver"
    geoserver_substations_layer: str = "infra:substations"
    geoserver_buildings_layer: str = "infra:buildings"

    cors_origins: list[str] = [f"http://localhost:{p}" for p in range(5173, 5191)]

    # Claude — required in production, no Ollama fallback.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    # S3 storage — set use_real_s3=true to point at AWS S3 instead of MinIO.
    # On EC2 with an IAM role attached, aws_access_key/secret can be left
    # blank and boto3 will pick up the instance credentials automatically.
    use_real_s3: bool = False
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    aws_region: str = "ap-southeast-1"
    aws_access_key: str = ""
    aws_secret_key: str = ""

    # Bucket and prefix layout for the testing environment.
    s3_bucket: str = "jejak-mappro-demo"
    s3_cell_ref_prefix: str = "3W-data/site-coverage-params/referenceData/"
    s3_location_data_prefix: str = "3W-data/site-coverage-params/locationData/"
    s3_network_data_prefix: str = "3W-data/raw-network-data/"
    s3_train_excel_prefix: str = "3W-data/train-ai-data/excel-data/"
    s3_train_pdf_prefix: str = "3W-data/train-ai-data/pdf-data/"
    s3_processed_prefix: str = "3W-data/processed/"


settings = Settings()
