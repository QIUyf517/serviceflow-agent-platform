from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = (
        "postgresql+psycopg://serviceflow:serviceflow_local@localhost:5432/serviceflow_demo"
    )
    agent_provider: Literal["mock", "openai_compatible"] = "mock"
    agent_model: str = "gpt-4.1-mini"
    agent_base_url: str = "https://api.openai.com/v1"
    agent_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    llm_api_key: SecretStr | None = None
    llm_model_id: str | None = None
    llm_base_url: str | None = None
    agent_timeout_seconds: float = 30.0
    agent_max_tool_calls: int = 6
    agent_temperature: float = 0.0
    agent_seed: int | None = 42
    agent_input_usd_per_million: float | None = None
    agent_output_usd_per_million: float | None = None

    @property
    def effective_model(self) -> str:
        return (self.agent_model if "agent_model" in self.model_fields_set
                else self.llm_model_id or self.agent_model)

    @property
    def effective_base_url(self) -> str:
        return (self.agent_base_url if "agent_base_url" in self.model_fields_set
                else self.llm_base_url or self.agent_base_url)

    @property
    def effective_key(self) -> SecretStr | None:
        return self.agent_api_key or self.openai_api_key or self.llm_api_key
