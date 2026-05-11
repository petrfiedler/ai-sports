"""Tools exposed to the LLM agents.

For now there is only one: ``SubmitActivityTool``, which the Parser Agent
calls exactly once to hand back the parsed workout. The tool stashes the
agent's structured output into a shared ``SubmitState`` instance so the
calling function can read it after the agent run completes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError
from smolagents import Tool

from src.models.schemas import ACTIVITY_SUMMARY_MAX, ActivitySchema, FollowUpQuestion


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
