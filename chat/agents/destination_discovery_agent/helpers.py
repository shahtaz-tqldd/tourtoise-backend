import json
import logging
import re
from typing import Optional, Any
from dataclasses import dataclass

from google.genai import types


logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    response_text: Optional[str] = None
    qna_response: Optional[dict[str, Any]] = None
    intention: str = "general"
    cost: float = 0.0
    total_tokens: int = 0


async def call_agent_async(runner, query: str) -> AgentResponse:
    content = types.Content(
        role="user",
        parts=[types.Part(text=query)],
    )

    final_response_text: Optional[str] = None
    current_agent: Optional[str] = None

    total_prompt_tokens = 0
    total_output_tokens = 0

    try:
        async for event in runner.run_async(new_message=content):
            if getattr(event, "usage_metadata", None):
                total_prompt_tokens = max(
                    total_prompt_tokens,
                    _safe_int(event.usage_metadata.prompt_token_count),
                )
                total_output_tokens = max(
                    total_output_tokens,
                    _safe_int(event.usage_metadata.candidates_token_count),
                )

            agent_name = getattr(event, "author", None)
            if agent_name:
                current_agent = agent_name

            # Prefer final response event when available.
            is_final = False
            if hasattr(event, "is_final_response"):
                try:
                    is_final = event.is_final_response()
                except Exception:
                    is_final = False

            response_text = _extract_text_from_event(event)

            if response_text and is_final:
                final_response_text = response_text

            # Fallback for ADK versions/events where is_final_response is not available.
            elif response_text:
                final_response_text = response_text

        cost, total_tokens = _calculate_token_price(
            total_prompt_tokens,
            total_output_tokens,
        )

        parsed_response = _parse_trip_agent_response(final_response_text, agent_name)
        
        if parsed_response is None:
            logger.error(
                "ADK agent call produced no valid structured response. "
                "agent=%s"
                "final_response_preview=%r",
                current_agent,
                (final_response_text or "")[:400],
            )

        return AgentResponse(
            response_text=final_response_text,
            qna_response=parsed_response,
            intention=_define_intention(current_agent or ""),
            cost=cost,
            total_tokens=total_tokens,
        )

    except Exception:
        logger.exception("Error during ADK agent call")
        return AgentResponse()


def _extract_text_from_event(event) -> Optional[str]:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) if content else None

    if not parts:
        return None

    texts: list[str] = []

    for part in parts:
        text = getattr(part, "text", None)
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())

    if not texts:
        return None

    return "\n".join(texts).strip()



def _parse_destination_recommendation_response(raw_text: Optional[str]) -> Optional[dict[str, Any]]:
    data = _parse_json_object(raw_text)
    if data is None:
        return None

    return {
        "destination_ids": _string_list(data.get("destination_ids")),
        "message": str(data.get("message") or "").strip()
    }



def _parse_trip_agent_response(raw_text: Optional[str], agent_name) -> Optional[dict[str, Any]]:
    return _parse_destination_recommendation_response(raw_text)


def _parse_json_object(raw_text: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw_text:
        return None

    cleaned = _strip_json_markdown(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        if cleaned.startswith('"') and not cleaned.startswith("{"):
            try:
                data = json.loads(f"{{{cleaned}}}")
            except json.JSONDecodeError:
                logger.exception(
                    "Agent returned non-JSON response. raw_text_preview=%r cleaned_preview=%r",
                    raw_text[:1000],
                    cleaned[:1000],
                )
                return None
        else:
            logger.exception(
                "Agent returned non-JSON response. raw_text_preview=%r cleaned_preview=%r",
                raw_text[:1000],
                cleaned[:1000],
            )
            return None

    if not isinstance(data, dict):
        logger.error("Agent JSON response is not an object. response_type=%s", type(data).__name__)
        return None

    return data


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strip_json_markdown(text: str) -> str:
    stripped = text.strip()

    fenced_match = re.search(
        r"```(?:json)?\s*(.*?)```",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if fenced_match:
        return fenced_match.group(1).strip()

    return stripped


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _calculate_token_price(
    input_token: int,
    output_token: int,
) -> tuple[float, int]:
    """
    Gemini 2.5 Flash rough token price calculation.
    Adjust if your actual model pricing/config changes.
    """

    input_token_cost = 0.3 / 1_000_000
    output_token_cost = 0.6 / 1_000_000

    total_cost = input_token * input_token_cost + output_token * output_token_cost
    total_tokens = input_token + output_token

    return total_cost, total_tokens


def _define_intention(agent_name: str) -> str:
    mapping = {
        "destination_recommendation_agent": "destination_recommendation",
        "default_agent": "general",
    }

    return mapping.get(agent_name, "general")
