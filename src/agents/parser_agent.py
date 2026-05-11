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

from src.agents.prompts import parser_system_prompt, reviser_system_prompt
from src.agents.tools import SubmitActivityTool, SubmitState
from src.config import get_settings
from src.models.schemas import ActivitySchema, ParseResult

_DEFAULT_MAX_STEPS = 6


def _build_task(text: str, today: date) -> str:
    return (
        parser_system_prompt(today)
        + "\n\n=== User activity log ===\n"
        + text.strip()
        + "\n=== End of log ===\n\n"
        + "Now call `submit_activity` exactly once, then `final_answer`."
    )


def _build_revise_task(
    current: ActivitySchema, instruction: str, today: date
) -> str:
    return (
        reviser_system_prompt(today, current.model_dump(mode="json"))
        + "\n\n=== Edit instruction ===\n"
        + instruction.strip()
        + "\n=== End of instruction ===\n\n"
        + "Now call `submit_activity` once with the full revised activity, "
        + "then `final_answer`."
    )


def _resolve_model_and_steps(
    model: Optional[Model], max_steps: Optional[int]
) -> tuple[Optional[Model], int, Optional[str]]:
    """Build the default LLM model + step cap. Returns (model, steps, error)."""
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
            return None, _DEFAULT_MAX_STEPS, f"Parser unavailable: {exc}"

    if max_steps is None:
        max_steps = _DEFAULT_MAX_STEPS
    return model, max_steps, None


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

    model, max_steps, err = _resolve_model_and_steps(model, max_steps)
    if err is not None:
        return ParseResult(fallback_message=err)
    assert model is not None  # narrow for mypy

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


def revise_activity(
    current: ActivitySchema,
    instruction: str,
    *,
    today: Optional[date] = None,
    model: Optional[Model] = None,
    max_steps: Optional[int] = None,
) -> ParseResult:
    """Apply a free-text edit instruction to an existing activity.

    The agent receives the full current activity plus the user's instruction
    and submits a revised ``ActivitySchema``. As with :func:`parse_activity`,
    this function never raises — failures collapse to a ``ParseResult`` with
    a ``fallback_message``.

    Args:
        current: The existing activity to revise.
        instruction: Free-text edit instruction (Czech or English).
        today: Reference date for resolving relative dates. Defaults to
            ``date.today()``.
        model: Optional smolagents ``Model`` override (tests inject one).
        max_steps: Optional cap on agent steps.

    Returns:
        A ``ParseResult``. On success, ``activity`` is the revised activity.
        On failure, ``activity`` is ``None`` and ``fallback_message`` is set.
    """
    if not instruction or not instruction.strip():
        return ParseResult(
            activity=current,
            fallback_message="Tell me what to change in a sentence.",
        )

    today = today or date.today()
    state = SubmitState()
    tool = SubmitActivityTool(state)

    model, max_steps, err = _resolve_model_and_steps(model, max_steps)
    if err is not None:
        return ParseResult(activity=current, fallback_message=err)
    assert model is not None

    agent = ToolCallingAgent(tools=[tool], model=model, max_steps=max_steps)

    try:
        agent.run(_build_revise_task(current, instruction, today))
    except Exception:
        if state.activity is None:
            return ParseResult(
                activity=current,
                fallback_message=(
                    "I couldn't apply that edit. Try rephrasing the change "
                    "you want — e.g. 'change duration to 45 minutes'."
                ),
            )

    if state.activity is None:
        return ParseResult(
            activity=current,
            fallback_message=(
                "I couldn't apply that edit. Try rephrasing the change "
                "you want — e.g. 'change duration to 45 minutes'."
            ),
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
