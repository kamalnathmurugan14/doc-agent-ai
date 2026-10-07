"""Application settings: one class, read from backend/.env (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    docs_root: Path = Path("./sample_docs")
    data_dir: Path = Path("./data")
    max_upload_mb: int = 25
    allowed_extensions: str = "pdf,docx,txt,md"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    agent_max_steps: int = 12
    agent_step_timeout_s: float = 60.0
    agent_run_timeout_s: float = 600.0
    require_approval: str = "write,move,rename"
    approval_timeout_s: float = 3600.0
    rag_service_url: str = ""
    classifier_service_url: str = ""
    reports_dir: str = "_reports"
    memory_runs: int = 3
    max_tool_output_chars: int = 4000
    cors_origins: str = "http://localhost:5173"

    @property
    def extensions(self) -> set[str]:
        return {e.strip().lower().lstrip(".") for e in self.allowed_extensions.split(",") if e.strip()}

    @property
    def approval_kinds(self) -> set[str]:
        return {k.strip().lower() for k in self.require_approval.split(",") if k.strip()}

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agent.sqlite"

    @property
    def checkpoint_path(self) -> Path:
        return self.data_dir / "checkpoints.sqlite"


@lru_cache
def get_settings() -> Settings:
    return Settings()
