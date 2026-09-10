from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="XRB_", env_file=".env", extra="ignore")

    database_url: SecretStr = SecretStr("postgresql+psycopg://xrb:xrb_dev_only@localhost:5432/xrb")
    read_database_url: SecretStr = SecretStr(
        "postgresql+psycopg://xrb_reader:xrb_reader_dev_only@localhost:5432/xrb"
    )
    data_dir: Path = Path("data")
    embedding_backend: Literal["none", "sentence-transformers"] = "none"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_revision: str = "main"
    chunk_max_words: int = Field(default=350, ge=32, le=2000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
