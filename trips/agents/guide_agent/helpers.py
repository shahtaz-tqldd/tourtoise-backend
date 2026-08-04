import logging
from dataclasses import dataclass
from typing import Any, Optional

from google.genai import types


logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    text_response: Optional[str] = None
    cost: float = 0.0
    total_tokens: int = 0


async def call_agent_async(
    runner,
    user_id: str,
    session_id: str,
    query: str,
) -> AgentResponse:
    content = types.Content(role="user", parts=[types.Part(text=query)])
    final_response_text: Optional[str] = None
    total_prompt_tokens = 0
    total_output_tokens = 0

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            usage = getattr(event, "usage_metadata", None)
            if usage:
                total_prompt_tokens = max(
                    total_prompt_tokens,
                    _safe_int(getattr(usage, "prompt_token_count", 0)),
                )
                total_output_tokens = max(
                    total_output_tokens,
                    _safe_int(getattr(usage, "candidates_token_count", 0)),
                )

            response_text = _extract_text_from_event(event)
            if response_text:
                final_response_text = response_text

        cost, total_tokens = _calculate_token_price(
            total_prompt_tokens,
            total_output_tokens,
        )
        return AgentResponse(
            text_response=final_response_text,
            cost=cost,
            total_tokens=total_tokens,
        )
    except Exception:
        logger.exception(
            "Guide agent call failed. user_id=%s session_id=%s",
            user_id,
            session_id,
        )
        return AgentResponse()


def _extract_text_from_event(event) -> Optional[str]:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) if content else None
    if not parts:
        return None

    texts = []
    for part in parts:
        text = getattr(part, "text", None)
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return "\n".join(texts).strip() or None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _calculate_token_price(input_tokens: int, output_tokens: int) -> tuple[float, int]:
    # Gemini 2.5 Flash pricing used elsewhere in this project.
    input_cost = input_tokens * (0.3 / 1_000_000)
    output_cost = output_tokens * (0.6 / 1_000_000)
    return round(input_cost + output_cost, 8), input_tokens + output_tokens
