"""LLM adapter. The agent only needs `chat(messages) -> str`; Ollama is one implementation, tests use a scripted fake."""

import httpx

from app.config import Settings
from app.errors import AppError


class ChatLLM:
    model: str = "unknown"

    async def chat(self, messages: list[dict], json_mode: bool = True, temperature: float = 0.1) -> str:
        raise NotImplementedError

    async def ping(self) -> bool:
        return True


class OllamaChat(ChatLLM):
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.model = settings.ollama_model

    async def chat(self, messages: list[dict], json_mode: bool = True, temperature: float = 0.1) -> str:
        body = {"model": self.model, "messages": messages, "stream": False, "options": {"temperature": temperature}}
        if json_mode:
            body["format"] = "json"  # Ollama constrains the output to valid JSON
        hint = f"Make sure Ollama is running (`ollama serve`) and the model is installed: `ollama pull {self.model}`"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.s.agent_step_timeout_s + 5, connect=5.0)) as http:
                r = await http.post(f"{self.s.ollama_base_url}/api/chat", json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise AppError("LLM_UNAVAILABLE", f"Cannot reach Ollama at {self.s.ollama_base_url}. {hint}", 503) from exc
        except httpx.ReadTimeout as exc:
            raise AppError("LLM_TIMEOUT", "The model took too long to respond", 504) from exc
        if r.status_code == 404:
            raise AppError("MODEL_MISSING", f"Model '{self.model}' is not installed. {hint}", 424)
        if r.status_code >= 400:
            raise AppError("LLM_ERROR", f"Ollama returned HTTP {r.status_code}", 502)
        return str((r.json().get("message") or {}).get("content", ""))

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                return (await http.get(f"{self.s.ollama_base_url}/api/tags")).status_code == 200
        except httpx.HTTPError:
            return False
