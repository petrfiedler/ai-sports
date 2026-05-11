"""Pydantic schemas for the AI Sports Planner.

These models are the single source of truth for the data layer. The Parser
and Planner agents return instances of these models; the storage service
serializes them into YAML Frontmatter and writes them to the private GitHub
data repository.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utcnow() -> datetime:
    """Timezone-aware UTC timestamp (replaces deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


ACTIVITY_SUMMARY_MAX = 160


class SportType(str, Enum):
    RUNNING = "running"
    CYCLING = "cycling"
    SWIMMING = "swimming"
    BOULDERING = "bouldering"
    CLIMBING = "climbing"
    STRENGTH = "strength"
    YOGA = "yoga"
    HIKING = "hiking"
    WALKING = "walking"
    OTHER = "other"


class ActivitySource(str, Enum):
    """Where the activity record originated."""

    MANUAL = "manual"
    STRAVA = "strava"


class Intensity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExerciseSet(BaseModel):
    """A single set within a strength exercise.

    Either rep-based (reps + optional weight) or time-based
    (duration_seconds, e.g. plank), depending on the exercise.
    """

    model_config = ConfigDict(extra="forbid")

    reps: Optional[int] = Field(default=None, ge=1)
    weight_kg: Optional[float] = Field(default=None, ge=0)
    duration_seconds: Optional[int] = Field(default=None, ge=1)
    rest_seconds: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _at_least_one_metric(self) -> "ExerciseSet":
        if self.reps is None and self.duration_seconds is None:
            raise ValueError("ExerciseSet requires either 'reps' or 'duration_seconds'.")
        return self


class Exercise(BaseModel):
    """A named strength exercise with one or more sets."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    sets: list[ExerciseSet] = Field(default_factory=list)
    notes: Optional[str] = None


class EnduranceMetrics(BaseModel):
    """Metrics typical for running, cycling, swimming, hiking.

    Populated either by the Strava sync agent or manually by the user.
    """

    model_config = ConfigDict(extra="forbid")

    distance_km: Optional[float] = Field(default=None, ge=0)
    avg_pace: Optional[str] = Field(default=None, description="e.g. '5:30/km'")
    avg_speed_kmh: Optional[float] = Field(default=None, ge=0)
    avg_heart_rate: Optional[int] = Field(default=None, ge=0, le=250)
    max_heart_rate: Optional[int] = Field(default=None, ge=0, le=250)
    elevation_gain_m: Optional[float] = Field(default=None, ge=0)
    calories: Optional[int] = Field(default=None, ge=0)
    strava_id: Optional[int] = Field(default=None, description="Strava activity ID, if synced.")


class FollowUpQuestion(BaseModel):
    """A clarifying question the Parser Agent asks when data is incomplete."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(..., description="The schema field the answer should populate.")
    question: str = Field(..., min_length=1)


class ActivitySchema(BaseModel):
    """A single logged sports activity.

    Persisted as `activities/YYYY-MM-DD-title.md` in the remote data repo,
    where this model becomes the YAML frontmatter and the user's raw text becomes
    the Markdown body.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    title: str = Field(..., min_length=1)
    sport: SportType
    activity_date: date = Field(..., description="Calendar day the activity took place.")
    duration_minutes: int = Field(..., gt=0)
    source: ActivitySource = ActivitySource.MANUAL

    rpe: Optional[int] = Field(default=None, ge=1, le=10, description="Rate of Perceived Exertion 1-10.")
    intensity: Optional[Intensity] = None
    summary: Optional[str] = Field(
        default=None,
        max_length=ACTIVITY_SUMMARY_MAX,
        description="One-line, dashboard-friendly recap of what the workout contained.",
    )
    notes: Optional[str] = Field(default=None, description="Free-form feelings / commentary.")

    exercises: list[Exercise] = Field(default_factory=list)
    metrics: Optional[EnduranceMetrics] = None

    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ProfileSchema(BaseModel):
    """The user's goals, preferences and constraints.

    Persisted as `profile.md`. The free-form `narrative` field is what the
    Planner Agent reads to understand intent; the structured fields exist so
    the UI can render and edit goals consistently.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    name: Optional[str] = None
    goals: list[str] = Field(
        default_factory=list,
        description="Short bullet-style goals, e.g. 'Half marathon under 2h'.",
    )
    preferred_sports: list[SportType] = Field(default_factory=list)
    weekly_target_hours: Optional[float] = Field(default=None, ge=0)
    constraints: list[str] = Field(
        default_factory=list,
        description="Recurring constraints, e.g. 'No gym on Tuesdays', injuries.",
    )
    narrative: Optional[str] = Field(
        default=None,
        description="Free-text profile description used as context for the Planner agent.",
    )
    updated_at: datetime = Field(default_factory=_utcnow)


class PlannedActivity(BaseModel):
    """A single planned slot in the weekly plan."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    day: date
    sport: SportType
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    duration_minutes: Optional[int] = Field(default=None, gt=0)
    intensity: Optional[Intensity] = None
    completed: bool = False


class PlanSchema(BaseModel):
    """A weekly training plan generated by the Planner Agent.

    Persisted as `plans/YYYY-Www-plan.md` in the remote data repo.
    `week_start` is always the Monday of the target week.
    """

    model_config = ConfigDict(extra="forbid")

    week_start: date = Field(..., description="Monday of the planned week.")
    activities: list[PlannedActivity] = Field(default_factory=list)
    rationale: Optional[str] = Field(
        default=None,
        description="Why the agent structured the week this way; useful for follow-up tweaks.",
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _week_start_is_monday(self) -> "PlanSchema":
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday.")
        return self


class ParseResult(BaseModel):
    """Return type of the Parser Agent.

    Wraps a (possibly partial) `ActivitySchema` together with any follow-up
    questions the agent wants the UI to surface. If `activity` is None, the
    agent could not extract anything useful and the UI should fall back to
    asking the user to rephrase.
    """

    model_config = ConfigDict(extra="forbid")

    activity: Optional[ActivitySchema] = None
    questions: list[FollowUpQuestion] = Field(default_factory=list)
    fallback_message: Optional[str] = None
