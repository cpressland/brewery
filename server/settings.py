from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://brewery:brewery@localhost/brewery"
    api_key: str = ""

    model_config = {"env_prefix": "BREWERY_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
