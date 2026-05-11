"""Parser Agent — turns free-text workout descriptions into ``ActivitySchema``.

Public entry point: :func:`parse_activity`. Returns a ``ParseResult`` that
the UI can render. Never raises — any failure becomes a
``ParseResult(fallback_message=...)`` so the Streamlit app cannot crash.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Optional

from smolagents import LiteLLMModel, Model, ToolCallingAgent

from src.agents.prompts import parser_system_prompt
from src.agents.tools import SubmitActivityTool, SubmitState
from src.config import get_settings
from src.models.schemas import ParseResult

_DEFAULT_MAX_STEPS = 6


def _build_task(text: str, today: date) -> str:
    return (
        parser_system_prompt(today)
        + "\n\n=== User activity log ===\n"
        + text.strip()
        + "\n=== End of log ===\n\n"
        + "Now call `submit_activity` exactly once, then `final_answer`."
    )


def parse_activity(
    text: str,
    *,
    today: Optional[date] = None,
    model: Optional[Model] = None,
    max_steps: Optional[int] = None,
) -> ParseResult:
    """Parse free-text into a validated ``ActivitySchema``.

    Args:
        text: Raw user input (Czech or English).
        today: Reference date for resolving relative dates. Defaults to
            ``date.today()``.
        model: Optional smolagents ``Model`` override. Production callers
            leave this ``None``; tests inject a stubbed model.
        max_steps: Optional cap on agent steps. Defaults to the value from
            ``Settings`` (or 6 when settings aren't available).

    Returns:
        A ``ParseResult``. On failure, ``activity`` is ``None`` and
        ``fallback_message`` describes the problem.
    """
    if not text or not text.strip():
        return ParseResult(fallback_message="Please describe your workout in a sentence or two.")

    today = today or date.today()
    state = SubmitState()
    tool = SubmitActivityTool(state)

    if model is None:
        try:
            settings = get_settings()
            model = LiteLLMModel(
                model_id=f"anthropic/{settings.llm_model}",
                api_key=settings.anthropic_api_key,
            )
            if max_steps is None:
                max_steps = settings.agent_max_steps
        except Exception as exc:
            return ParseResult(fallback_message=f"Parser unavailable: {exc}")

    if max_steps is None:
        max_steps = _DEFAULT_MAX_STEPS

    agent = ToolCallingAgent(tools=[tool], model=model, max_steps=max_steps)

    try:
        agent.run(_build_task(text, today))
    except Exception:
        if state.activity is None and not state.questions:
            return ParseResult(
                fallback_message=(
                    "I couldn't parse that into a workout. Try rephrasing "
                    "with the sport, duration, and date."
                )
            )

    if state.activity is None and not state.questions:
        return ParseResult(
            fallback_message=(
                "I couldn't parse that into a workout. Try rephrasing with "
                "the sport, duration, and date."
            )
        )

    return ParseResult(activity=state.activity, questions=state.questions)


def _cli() -> int:
    if len(sys.argv) < 2:
        print('Usage: python -m src.agents.parser_agent "your workout text"', file=sys.stderr)
        return 2
    result = parse_activity(" ".join(sys.argv[1:]))
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
