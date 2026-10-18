from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RESEARCH_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
        env_parse_none_str="null",
        populate_by_name=True,
    )
    data_dir: Path = PROJECT_ROOT / "data"
    model_provider: Literal["api", "ollama"] = "api"
    model_name: str = Field(
        default="qwen-plus", validation_alias=AliasChoices("RESEARCH_MODEL_NAME", "SHANIU_MODEL")
    )
    model_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("RESEARCH_MODEL_BASE_URL", "SHANIU_API_BASE"),
    )
    model_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("RESEARCH_MODEL_API_KEY", "SHANIU_API_KEY"),
    )
    credentials_file: Path | None = None
    model_api_key_env: str = ""
    model_timeout: float = 90
    model_max_tokens: int = 8192
    model_extra_body: dict = {}
    openalex_api_key: SecretStr = SecretStr("")
    semantic_scholar_api_key: SecretStr = SecretStr("")
    tool_transport: Literal["stdio", "local"] = "stdio"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dir: Path = PROJECT_ROOT / "data" / "embedding-model"
    browser_enabled: bool = False
    chrome_path: str = ""
    http_timeout: float = 30
    tool_timeout: float = 180
    cache_ttl: int = 86400
    source_requests_per_run: int = 60
    access_token: SecretStr = SecretStr("")
    secure_cookies: bool = False
    max_request_bytes: int = 2_000_000
    max_upload_bytes: int = 50_000_000
    max_parallel_tasks: int = 3

    def prepare(self):
        self.data_dir = (
            self.data_dir if self.data_dir.is_absolute() else PROJECT_ROOT / self.data_dir
        ).resolve()
        self.embedding_dir = (
            self.embedding_dir
            if self.embedding_dir.is_absolute()
            else PROJECT_ROOT / self.embedding_dir
        ).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.credentials_file and not self.model_api_key.get_secret_value():
            import os

            from dotenv import dotenv_values

            path = self.credentials_file
            path = path if path.is_absolute() else PROJECT_ROOT / path
            if not self.model_api_key_env:
                raise ValueError("引用凭据文件时需填写 RESEARCH_MODEL_API_KEY_ENV")
            if not path.is_file():
                raise ValueError("配置的凭据文件不存在")
            value = os.environ.get(self.model_api_key_env) or dotenv_values(path).get(
                self.model_api_key_env
            )
            if not value:
                raise ValueError("凭据文件中未找到配置的模型密钥变量")
            self.model_api_key = SecretStr(value)
        return self


def get_settings() -> Settings:
    return Settings().prepare()
