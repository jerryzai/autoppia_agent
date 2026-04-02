"""LLM API client with retry logic, multi-provider support, and cost tracking."""
from __future__ import annotations
import os
import logging
import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config import LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS

logger = logging.getLogger(__name__)

# Cost table: model_name -> (prompt_cost_per_M, completion_cost_per_M)
_COST_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4o-mini":   (0.15,  0.60),
    "gpt-4o":        (2.50, 10.00),
    "gpt-4.1-mini":  (0.40,  1.60),
    "gpt-4.1-nano":  (0.10,  0.40),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku":  (0.25,  1.25),
    "claude-opus":   (15.00, 75.00),
}


def _get_cost_rates(model: str) -> tuple[float, float]:
    """Get prompt and completion cost rates for a model."""
    for key, rates in _COST_TABLE.items():
        if key in model:
            return rates
    return (0.15, 0.60)  # default to gpt-4o-mini rates


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503)
    return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout))


class LLMClient:
    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.model = os.getenv("OPENAI_MODEL", LLM_MODEL)
        self.temperature = float(os.getenv("OPENAI_TEMPERATURE", str(LLM_TEMPERATURE)))
        self.max_tokens = int(os.getenv("OPENAI_MAX_TOKENS", str(LLM_MAX_TOKENS)))
        self._client = httpx.Client(timeout=30.0)
        self._total_cost = 0.0
        self._total_calls = 0

        if self.provider == "anthropic":
            self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
            self.base_url = os.getenv(
                "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
            ).rstrip("/")
            if not self.model or self.model == LLM_MODEL:
                self.model = "claude-haiku-4-5-20251001"
        else:
            self.api_key = os.getenv("OPENAI_API_KEY", "")
            self.base_url = os.getenv(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            ).rstrip("/")

        self._cost_rates = _get_cost_rates(self.model)
        logger.info(f"LLM provider={self.provider} model={self.model}")

    def chat(self, task_id: str, messages: list[dict]) -> str:
        """Dispatch to provider-specific chat method."""
        self._total_calls += 1
        if self.provider == "anthropic":
            return self._chat_anthropic(task_id, messages)
        return self._chat_openai(task_id, messages)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3.0),
        retry=retry_if_exception(_is_retryable),
    )
    def _chat_openai(self, task_id: str, messages: list[dict]) -> str:
        """OpenAI-compatible API call."""
        headers = {
            "Content-Type": "application/json",
            "IWA-Task-ID": task_id,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        resp = self._client.post(
            f"{self.base_url}/chat/completions", json=body, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

        # Cost tracking
        usage = data.get("usage", {})
        self._track_cost(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

        return data["choices"][0]["message"]["content"]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3.0),
        retry=retry_if_exception(_is_retryable),
    )
    def _chat_anthropic(self, task_id: str, messages: list[dict]) -> str:
        """Anthropic Messages API call."""
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        # Convert OpenAI message format to Anthropic format
        system_text = ""
        claude_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg["content"] + "\n"
            else:
                claude_messages.append({"role": msg["role"], "content": msg["content"]})

        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": claude_messages,
        }
        if system_text.strip():
            body["system"] = system_text.strip()

        resp = self._client.post(
            f"{self.base_url}/v1/messages", json=body, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

        # Cost tracking
        usage = data.get("usage", {})
        self._track_cost(usage.get("input_tokens", 0), usage.get("output_tokens", 0))

        content = data.get("content", [])
        return content[0]["text"] if content else ""

    def _track_cost(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Track cost for a single LLM call."""
        p_rate, c_rate = self._cost_rates
        cost = (prompt_tokens * p_rate + completion_tokens * c_rate) / 1_000_000
        self._total_cost += cost
        logger.debug(
            f"LLM call cost=${cost:.6f} total=${self._total_cost:.6f} "
            f"prompt={prompt_tokens} completion={completion_tokens}"
        )

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def total_calls(self) -> int:
        return self._total_calls
