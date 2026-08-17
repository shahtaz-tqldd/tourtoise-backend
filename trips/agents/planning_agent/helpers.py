import json
import logging
import re
from typing import Optional, Any
from dataclasses import dataclass

from django.conf import settings
from google.genai import types
from trips.choices import PlanningStep


logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    response_text: Optional[str] = None
    qna_response: Optional[dict[str, Any]] = None
    intention: str = "general"
    cost: float = 0.0
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


async def call_agent_async(
    runner,
    user_id: str,
    session_id: str,
    query: str,
    planning_step: PlanningStep = PlanningStep.PREFERENCE,
) -> AgentResponse:
    content = types.Content(
        role="user",
        parts=[types.Part(text=query)],
    )

    final_response_text: Optional[str] = None
    current_agent: Optional[str] = None

    total_prompt_tokens = 0
    total_output_tokens = 0
    counted_usage_events = set()

    try:
        logger.info(
            "Starting ADK agent call. user_id=%s session_id=%s planning_step=%s query_chars=%s",
            user_id,
            session_id,
            planning_step,
            len(query),
        )
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            usage_metadata = getattr(event, "usage_metadata", None)
            usage_event_id = getattr(event, "id", None) or id(event)
            if usage_metadata and usage_event_id not in counted_usage_events:
                counted_usage_events.add(usage_event_id)
                total_prompt_tokens += _safe_int(
                    getattr(usage_metadata, "prompt_token_count", 0)
                )
                total_output_tokens += _safe_int(
                    getattr(usage_metadata, "candidates_token_count", 0)
                ) + _safe_int(getattr(usage_metadata, "thoughts_token_count", 0))

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

            if response_text:
                logger.debug(
                    "Received ADK event text. user_id=%s session_id=%s agent=%s is_final=%s text_preview=%r",
                    user_id,
                    session_id,
                    agent_name,
                    is_final,
                    response_text[:500],
                )

            if response_text and is_final:
                final_response_text = response_text

            # Fallback for ADK versions/events where is_final_response is not available.
            elif response_text:
                final_response_text = response_text

        cost, total_tokens = _calculate_token_price(
            total_prompt_tokens,
            total_output_tokens,
        )

        parsed_response = _parse_trip_agent_response(final_response_text, planning_step)
        if parsed_response is None:
            logger.error(
                "ADK agent call produced no valid structured response. "
                "user_id=%s session_id=%s agent=%s prompt_tokens=%s output_tokens=%s "
                "final_response_preview=%r",
                user_id,
                session_id,
                current_agent,
                total_prompt_tokens,
                total_output_tokens,
                (final_response_text or "")[:1000],
            )
        else:
            logger.info(
                "ADK agent call completed with structured response. "
                "user_id=%s session_id=%s agent=%s prompt_tokens=%s output_tokens=%s "
                "planning_step=%s",
                user_id,
                session_id,
                current_agent,
                total_prompt_tokens,
                total_output_tokens,
                planning_step,
            )

        return AgentResponse(
            response_text=final_response_text,
            qna_response=parsed_response,
            intention=_define_intention(current_agent or ""),
            cost=cost,
            total_tokens=total_tokens,
            input_tokens=total_prompt_tokens,
            output_tokens=total_output_tokens,
        )

    except Exception:
        logger.exception(
            "Error during ADK agent call. user_id=%s session_id=%s planning_step=%s",
            user_id,
            session_id,
            planning_step,
        )
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


def _parse_trip_qna_response(raw_text: Optional[str]) -> Optional[dict[str, Any]]:
    data = _parse_json_object(raw_text)
    if data is None:
        return None

    question = data.get("question")
    is_qna_complete = data.get("is_qna_complete")
    context = data.get("context")

    if not isinstance(is_qna_complete, bool):
        logger.error(
            "Agent JSON response has invalid is_qna_complete. value=%r response=%s",
            is_qna_complete,
            data,
        )
        return None

    if is_qna_complete:
        return {
            "question": None,
            "is_qna_complete": True,
            "context": str(context).strip() if context else "",
        }

    return {
        "question": str(question).strip() if question else "Could you share your travel preferences?",
        "is_qna_complete": False,
        "context": None,
    }


def _parse_trip_recommendations_response(raw_text: Optional[str]) -> Optional[dict[str, Any]]:
    data = _parse_json_object(raw_text)
    if data is None:
        return None

    is_discovery_complete = data.get("is_discovery_complete")
    if not isinstance(is_discovery_complete, bool):
        logger.error(
            "Agent JSON response has invalid is_discovery_complete. value=%r response=%s",
            is_discovery_complete,
            data,
        )
        return None

    messages = data.get("messages") if isinstance(data.get("messages"), dict) else {}
    return {
        "is_discovery_complete": is_discovery_complete,
        "attraction_ids": _string_list(data.get("attraction_ids") or data.get("tour_spot_ids")),
        "activity_ids": _string_list(data.get("activity_ids")),
        "cuisine_ids": _string_list(data.get("cuisine_ids") or data.get("food_item_ids")),
        "messages": {
            "attractions": str(messages.get("attractions") or messages.get("tour_spots") or "").strip(),
            "activities": str(messages.get("activities") or "").strip(),
            "cuisines": str(messages.get("cuisines") or messages.get("foods") or "").strip(),
        },
    }


def _parse_trip_itinerary_response(raw_text: Optional[str]) -> Optional[dict[str, Any]]:
    data = _parse_json_object(raw_text)
    if data is None:
        return None

    is_itinerary_complete = data.get("is_itinerary_complete")
    if not isinstance(is_itinerary_complete, bool):
        logger.error(
            "Agent JSON response has invalid is_itinerary_complete. value=%r response=%s",
            is_itinerary_complete,
            data,
        )
        return None

    rough_budget = data.get("rough_budget") if isinstance(data.get("rough_budget"), dict) else {}
    return {
        "is_itinerary_complete": is_itinerary_complete,
        "title": str(data.get("title") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "day_wise_plan": data.get("day_wise_plan") if isinstance(data.get("day_wise_plan"), list) else [],
        "route_plan": data.get("route_plan") if isinstance(data.get("route_plan"), list) else [],
        "rough_budget": rough_budget,
        "message": str(data.get("message") or "").strip(),
    }


def _parse_trip_preparation_response(raw_text: Optional[str]) -> Optional[dict[str, Any]]:
    data = _parse_json_object(raw_text)
    if data is None:
        return None

    is_preparation_complete = data.get("is_preparation_complete")
    if not isinstance(is_preparation_complete, bool):
        logger.error(
            "Agent JSON response has invalid is_preparation_complete. value=%r response=%s",
            is_preparation_complete,
            data,
        )
        return None

    return {
        "is_preparation_complete": is_preparation_complete,
        "title": str(data.get("title") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "packing_items": _dict_list(data.get("packing_items")),
        "required_documents": _dict_list(data.get("required_documents")),
        "heads_up": _dict_list(data.get("heads_up")),
        "message": str(data.get("message") or "").strip(),
    }


def _parse_trip_agent_response(raw_text: Optional[str], planning_step: PlanningStep) -> Optional[dict[str, Any]]:
    if planning_step == PlanningStep.RECOMMENDATION:
        return _parse_trip_recommendations_response(raw_text)
    if planning_step == PlanningStep.ITINERARY:
        return _parse_trip_itinerary_response(raw_text)
    if planning_step == PlanningStep.PREPARATION:
        return _parse_trip_preparation_response(raw_text)
    return _parse_trip_qna_response(raw_text)


def _parse_json_object(raw_text: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw_text:
        return None

    cleaned = _strip_json_markdown(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # LLMs occasionally append an extra brace, commentary, or a repeated
        # response after an otherwise complete JSON object. Preserve the first
        # complete object instead of discarding the entire itinerary.
        if exc.msg == "Extra data":
            try:
                data, parsed_end = json.JSONDecoder().raw_decode(cleaned)
            except json.JSONDecodeError:
                data = None
            else:
                trailing_text = cleaned[parsed_end:].strip()
                logger.warning(
                    "Agent returned trailing content after a valid JSON value; "
                    "using the first value. trailing_preview=%r",
                    trailing_text[:500],
                )

            if isinstance(data, dict):
                return data

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
    Estimate model token cost from deploy-time pricing settings.

    Tool-specific charges such as paid Google Search grounding are not included.
    """

    input_token_cost = settings.PLANNING_AGENT_INPUT_COST_PER_MILLION / 1_000_000
    output_token_cost = settings.PLANNING_AGENT_OUTPUT_COST_PER_MILLION / 1_000_000

    total_cost = input_token * input_token_cost + output_token * output_token_cost
    total_tokens = input_token + output_token

    return total_cost, total_tokens


def _define_intention(agent_name: str) -> str:
    mapping = {
        "profile_customization_agent": "trip_profile_qna",
        "destination_discovery_agent": "destination_recommendations",
        "itinerary_design_agent": "itinerary_design",
        "trip_preparation_agent": "trip_preparation",
        "default_root_agent": "general",
    }

    return mapping.get(agent_name, "general")
