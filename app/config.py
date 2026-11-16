from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки читаются из переменных окружения или файла .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    keitaro_url: str = "https://tlgk.host"  # адрес трекера без /admin
    keitaro_api_key: str = ""  # ключ из админки Keitaro: Обслуживание → Admin API
    database_url: str = "sqlite:///./wrapper.db"

    # Префикс, который обязателен для названий кампаний (например test_ivanov_)
    campaign_prefix: str = ""
    # Куда отправлять посетителей из выбранной страны
    fallback_url: str = "https://google.com"


settings = Settings()
