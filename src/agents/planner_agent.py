"""Planner Agent — generates and revises weekly training plans.

Public entry points:

* :func:`generate_plan` — build a fresh ``PlanSchema`` for a given week from
  the user's profile and the last 14 days of activity.
* :func:`revise_plan` — apply a free-text edit instruction to an existing
  plan and return the new revision.

Both functions follow the same contract as the Parser Agent: they never
raise. Any failure collapses to a return value the UI can render — either
the ``current`` plan (for revisions) or ``None`` (for generation) plus a
``fallback_message``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from smolagents import LiteLLMModel, Model, ToolCallingAgent

from src.agents.prompts import (
    plan_reviser_system_prompt,
    planner_system_prompt,
)
from src.agents.tools import SubmitPlanState, SubmitPlanTool
from src.config import get_settings
from src.models.schemas import ActivitySchema, PlanSchema, ProfileSchema

_DEFAULT_MAX_STEPS = 6
_HISTORY_DAYS = 14


@dataclass
class PlanResult:
    """Return type of the Planner Agent.

    ``plan`` is the new (or revised) plan on success. ``fallback_message``
    explains the failure when ``plan`` is ``None`` (generation) or when the
    edit could not be applied (revision — ``plan`` is then the unchanged
    input).
    """

    plan: Optional[PlanSchema] = None
    fallback_message: Optional[str] = None


def _ensure_monday(d: date) -> date:
    if d.weekday() != 0:
        raise ValueError("week_start must be a Monday.")
    return d


def _summarize_activity(a: ActivitySchema) -> dict[str, Any]:
    """Compact view passed to the LLM so we don't waste tokens on irrelevant fields."""
    summary: dict[str, Any] = {
        "date": a.activity_date.isoformat(),
        "sport": a.sport,
        "title": a.title,
        "duration_minutes": a.duration_minutes,
    }
    if a.intensity:
        summary["intensity"] = a.intensity
    if a.rpe is not None:
        summary["rpe"] = a.rpe
    if a.metrics is not None and a.metrics.distance_km is not None:
        summary["distance_km"] = a.metrics.distance_km
    if a.summary:
        summary["summary"] = a.summary
    return summary


def _filter_recent(
    activities: list[ActivitySchema], today: date, days: int = _HISTORY_DAYS
) -> list[ActivitySchema]:
    cutoff = today - timedelta(days=days)
    recent = [a for a in activities if a.activity_date >= cutoff]
    recent.sort(key=lambda a: a.activity_date, reverse=True)
    return recent


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
            return None, _DEFAULT_MAX_STEPS, f"Planner unavailable: {exc}"

    if max_steps is None:
        max_steps = _DEFAULT_MAX_STEPS
    return model, max_steps, None


def _build_generate_task(
    profile: ProfileSchema,
    recent: list[ActivitySchema],
    week_start: date,
    today: date,
) -> str:
    profile_json = profile.model_dump(mode="json", exclude_none=True)
    recent_json = [_summarize_activity(a) for a in recent]
    return (
        planner_system_prompt(today, week_start, profile_json, recent_json)
        + "\n\nNow call `submit_plan` once with the full weekly plan, then "
        + "`final_answer`."
    )


def _build_revise_task(
    current: PlanSchema,
    instruction: str,
    profile: Optional[ProfileSchema],
    today: date,
) -> str:
    current_json = current.model_dump(mode="json", exclude_none=True)
    profile_json = (
        profile.model_dump(mode="json", exclude_none=True)
        if profile is not None
        else None
    )
    return (
        plan_reviser_system_prompt(today, current_json, profile_json)
        + "\n\n=== Edit instruction ===\n"
        + instruction.strip()
        + "\n=== End of instruction ===\n\n"
        + "Now call `submit_plan` once with the full revised plan, then "
        + "`final_answer`."
    )


def generate_plan(
    profile: ProfileSchema,
    recent_activities: list[ActivitySchema],
    week_start: date,
    *,
    today: Optional[date] = None,
    model: Optional[Model] = None,
    max_steps: Optional[int] = None,
) -> PlanResult:
    """Generate a fresh ``PlanSchema`` for the week starting ``week_start``.

    Args:
        profile: The user's stored profile.
        recent_activities: Recent activity log (any length; the agent only
            sees the last ``_HISTORY_DAYS`` days).
        week_start: Monday of the target week. Must be a Monday.
        today: Reference date for the LLM. Defaults to ``date.today()``.
        model: Optional smolagents ``Model`` override (tests inject one).
        max_steps: Optional cap on agent steps.

    Returns:
        A ``PlanResult``. On success, ``plan`` is populated. On any failure
        ``plan`` is ``None`` and ``fallback_message`` describes the issue.
    """
    try:
        week_start = _ensure_monday(week_start)
    except ValueError as exc:
        return PlanResult(fallback_message=str(exc))

    today = today or date.today()
    recent = _filter_recent(recent_activities, today)

    model, max_steps, err = _resolve_model_and_steps(model, max_steps)
    if err is not None:
        return PlanResult(fallback_message=err)
    assert model is not None

    state = SubmitPlanState()
    tool = SubmitPlanTool(state)
    agent = ToolCallingAgent(tools=[tool], model=model, max_steps=max_steps)

    try:
        agent.run(_build_generate_task(profile, recent, week_start, today))
    except Exception:
        if state.plan is None:
            return PlanResult(
                fallback_message=(
                    "I couldn't generate a plan for that week. "
                    "Try again, or check your profile and recent activities."
                )
            )

    if state.plan is None:
        return PlanResult(
            fallback_message=(
                "I couldn't generate a plan for that week. "
                "Try again, or check your profile and recent activities."
            )
        )

    return PlanResult(plan=state.plan)


def revise_plan(
    current: PlanSchema,
    instruction: str,
    *,
    profile: Optional[ProfileSchema] = None,
    today: Optional[date] = None,
    model: Optional[Model] = None,
    max_steps: Optional[int] = None,
) -> PlanResult:
    """Apply a free-text edit instruction to an existing plan.

    The agent receives the full current plan, the instruction, and the
    profile (if supplied) so constraint checks survive revisions. As with
    :func:`generate_plan`, this function never raises — failures collapse
    to a ``PlanResult`` whose ``plan`` is the unchanged input and whose
    ``fallback_message`` is set.

    Args:
        current: The plan to edit.
        instruction: Free-text edit instruction (Czech or English).
        profile: Optional profile for constraint-aware edits.
        today: Reference date. Defaults to ``date.today()``.
        model: Optional smolagents ``Model`` override (tests inject one).
        max_steps: Optional cap on agent steps.
    """
    if not instruction or not instruction.strip():
        return PlanResult(
            plan=current,
            fallback_message="Tell me what to change in the plan.",
        )

    today = today or date.today()

    model, max_steps, err = _resolve_model_and_steps(model, max_steps)
    if err is not None:
        return PlanResult(plan=current, fallback_message=err)
    assert model is not None

    state = SubmitPlanState()
    tool = SubmitPlanTool(state)
    agent = ToolCallingAgent(tools=[tool], model=model, max_steps=max_steps)

    try:
        agent.run(_build_revise_task(current, instruction, profile, today))
    except Exception:
        if state.plan is None:
            return PlanResult(
                plan=current,
                fallback_message=(
                    "I couldn't apply that edit. Try rephrasing — e.g. "
                    "'move Tuesday's run to Wednesday'."
                ),
            )

    if state.plan is None:
        return PlanResult(
            plan=current,
            fallback_message=(
                "I couldn't apply that edit. Try rephrasing — e.g. "
                "'move Tuesday's run to Wednesday'."
            ),
        )

    return PlanResult(plan=state.plan)
