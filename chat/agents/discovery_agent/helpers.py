import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from google.genai import types
from pydantic import ValidationError

from .schema import DiscoveryAgentResponse


logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    text: str = ""
    structured: Optional[dict[str, Any]] = None
    cost: float = 0.0
    total_tokens: int = 0


async def call_agent_async(runner, *, user_id: str, session_id: str, query: str):
    content = types.Content(role="user", parts=[types.Part(text=query)])
    final_text = ""
    prompt_tokens = 0
    output_tokens = 0

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            usage = getattr(event, "usage_metadata", None)
            if usage:
                prompt_tokens = max(prompt_tokens, _safe_int(usage.prompt_token_count))
                output_tokens = max(output_tokens, _safe_int(usage.candidates_token_count))
            event_text = _extract_text(event)
            if event_text:
                final_text = event_text
    except Exception:
        logger.exception("Discovery ADK invocation failed")
        return AgentResponse()

    structured = _parse_response(final_text)
    cost, total_tokens = _calculate_token_price(prompt_tokens, output_tokens)
    return AgentResponse(
        text=(structured or {}).get("message", final_text),
        structured=structured,
        cost=cost,
        total_tokens=total_tokens,
    )


def _extract_text(event):
    parts = getattr(getattr(event, "content", None), "parts", None) or []
    text_parts = [
        part.text.strip()
        for part in parts
        if isinstance(getattr(part, "text", None), str) and part.text.strip()
    ]
    return "\n".join(text_parts)


def _parse_response(raw_text):
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    try:
        return DiscoveryAgentResponse.model_validate(json.loads(cleaned.strip())).model_dump(
            mode="json"
        )
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.warning(
            "Discovery agent returned an invalid structured response: %s",
            type(exc).__name__,
        )
        return None


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _calculate_token_price(input_tokens, output_tokens):
    cost = input_tokens * (0.3 / 1_000_000) + output_tokens * (0.6 / 1_000_000)
    return cost, input_tokens + output_tokens
