from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    """Cấu hình chung, đọc từ biến môi trường có tiền tố BEN_."""

    model_config = SettingsConfigDict(env_prefix="BEN_", extra="ignore")

    env: str = "dev"
    service_name: str = "ben"
    log_level: str = "INFO"
    otel_enabled: bool = False
    # Endpoint OTLP/HTTP gốc; exporter tự nối thêm /v1/traces
    otel_endpoint: str = "http://otel-collector:4318"
