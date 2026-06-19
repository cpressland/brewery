from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://brewery:brewery@localhost/brewery"
    api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "BREWERY_", "env_file": ".env"}


settings = Settings()
