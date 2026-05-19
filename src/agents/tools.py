"""Tools exposed to the LLM agents.

Two single-purpose submission tools live here:

* ``SubmitActivityTool`` — the Parser/Reviser Agent uses it to hand back a
  parsed or revised ``ActivitySchema``.
* ``SubmitPlanTool`` — the Planner Agent uses it to hand back a generated
  or revised ``PlanSchema``.

Each tool stashes its structured output into a shared state dataclass so
the calling function can read it after the agent run completes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError
from smolagents import Tool

from src.models.schemas import (
    ACTIVITY_SUMMARY_MAX,
    ActivitySchema,
    FollowUpQuestion,
    PlanSchema,
)


@dataclass
class SubmitState:
    """Container the parser tool writes into.

    Either ``activity`` is populated or ``error`` is set (if the agent
    returned data that failed Pydantic validation). ``questions`` collects
    any follow-ups the agent flagged.
    """

    activity: Optional[ActivitySchema] = None
    questions: list[FollowUpQuestion] = field(default_factory=list)
    error: Optional[str] = None


class SubmitActivityTool(Tool):
    """The single tool the Parser Agent calls to return its result."""

    name = "submit_activity"
    description = (
        "Submit the parsed workout. Call this exactly once per run. "
        "Pass `activity=null` if the input is not a parseable workout. "
        "Use `follow_up_questions` to ask the user for any missing required "
        "information instead of guessing."
    )
    inputs: dict[str, dict[str, Any]] = {
        "activity": {
            "type": "object",
            "description": (
                "ActivitySchema as a JSON object (snake_case keys). Required "
                "fields: title, sport, activity_date (YYYY-MM-DD), "
                "duration_minutes. Pass null when the input cannot be parsed."
            ),
            "nullable": True,
        },
        "follow_up_questions": {
            "type": "array",
            "description": (
                "List of {field, question} objects for missing required data. "
                "Empty list if the activity is complete or unparseable."
            ),
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, state: SubmitState) -> None:
        super().__init__()
        self._state = state

    def forward(
        self,
        activity: Optional[dict[str, Any]],
        follow_up_questions: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        questions_raw = follow_up_questions or []
        parsed_questions: list[FollowUpQuestion] = []
        for q in questions_raw:
            try:
                parsed_questions.append(FollowUpQuestion(**q))
            except (ValidationError, TypeError):
                continue
        self._state.questions = parsed_questions

        if activity is None:
            self._state.activity = None
            return "Recorded: no parseable activity. End the run with final_answer."

        payload = dict(activity)
        payload.pop("follow_up_questions", None)
        summary = payload.get("summary")
        if isinstance(summary, str) and len(summary) > ACTIVITY_SUMMARY_MAX:
            payload["summary"] = summary[: ACTIVITY_SUMMARY_MAX - 1].rstrip() + "…"
        try:
            self._state.activity = ActivitySchema(**payload)
        except ValidationError as exc:
            self._state.activity = None
            self._state.error = str(exc)
            return (
                "Validation failed: " + str(exc) + ". "
                "Do not retry — end the run with final_answer."
            )
        return "Activity recorded. End the run with final_answer."


@dataclass
class SubmitPlanState:
    """Container the planner tool writes into.

    Either ``plan`` is populated or ``error`` is set when the agent
    returned data that failed Pydantic validation (e.g. ``week_start``
    not a Monday).
    """

    plan: Optional[PlanSchema] = None
    error: Optional[str] = None


class SubmitPlanTool(Tool):
    """The single tool the Planner Agent calls to return its result."""

    name = "submit_plan"
    description = (
        "Submit the generated weekly training plan. Call this exactly once "
        "per run. Pass `plan=null` only when no plan can be produced from "
        "the provided context."
    )
    inputs: dict[str, dict[str, Any]] = {
        "plan": {
            "type": "object",
            "description": (
                "PlanSchema as a JSON object (snake_case keys). Required "
                "fields: week_start (YYYY-MM-DD, must be a Monday), "
                "activities (list of {day, sport, title, description, "
                "duration_minutes?, intensity?, completed=false}). "
                "Optional: rationale. Pass null when no plan can be built."
            ),
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, state: SubmitPlanState) -> None:
        super().__init__()
        self._state = state

    def forward(self, plan: Optional[dict[str, Any]]) -> str:
        if plan is None:
            self._state.plan = None
            return "Recorded: no plan generated. End the run with final_answer."

        try:
            self._state.plan = PlanSchema(**plan)
        except ValidationError as exc:
            self._state.plan = None
            self._state.error = str(exc)
            return (
                "Validation failed: " + str(exc) + ". "
                "Do not retry — end the run with final_answer."
            )
        return "Plan recorded. End the run with final_answer."
