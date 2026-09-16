from ben_common.settings import CommonSettings


class GatewaySettings(CommonSettings):
    service_name: str = "gateway"
    # Role ben_app, không phải owner (ADR-004)
    database_url: str = "postgresql://ben_app:ben_app@localhost:5432/ben"
    redis_url: str = "redis://localhost:6379/0"
    readiness_timeout_s: float = 2.0
