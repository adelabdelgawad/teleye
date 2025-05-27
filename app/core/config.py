from dotenv import load_dotenv

load_dotenv(".env")
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    title: str
    description: str
    version: str

    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore")


class TelegramSettings(BaseSettings):
    api_id: int
    api_hash: str
    string_session: str

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", extra="ignore")


class MinioSettings(BaseSettings):
    root_user: str
    root_password: str
    endpoint: str
    use_presigned_urls: bool
    secure: bool

    model_config = SettingsConfigDict(env_prefix="MINIO_", extra="ignore")


class SecuritySettings(BaseSettings):
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int
    admin_username: str
    admin_password: str

    model_config = SettingsConfigDict(env_prefix="SECURITY_", extra="ignore")


class Settings(BaseSettings):
    api: APISettings = APISettings()
    telegram: TelegramSettings = TelegramSettings()
    minio: MinioSettings = MinioSettings()
    security: SecuritySettings = SecuritySettings()
    celery_broker_url: str
    celery_result_backend: str
    flower_port: int
    elasticsearch_connection_url: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="_",
    )


settings = Settings()
