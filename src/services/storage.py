"""GitHub-backed storage for the AI Sports Planner.

Streamlit Community Cloud has an ephemeral filesystem, so we treat a private
GitHub repository as our database. Pydantic models are serialized to YAML
frontmatter and the user's raw text becomes the Markdown body. Each save is
a commit, which also gives us free history.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Union

import frontmatter
from github import Github, GithubException
from github.Repository import Repository

from src.models.schemas import ActivitySchema, PlanSchema, ProfileSchema


_ACTIVITIES_DIR = "activities"
_PLANS_DIR = "plans"
_PROFILE_PATH = "profile.md"


SerializableModel = Union[ActivitySchema, ProfileSchema, PlanSchema]


def _slugify(text: str) -> str:
    """ASCII-only, filesystem-safe slug derived from a title.

    Handles Czech diacritics by decomposing to NFKD and dropping combining
    marks. Non-alphanumeric runs collapse to single dashes. Returns
    ``"untitled"`` for inputs that produce no usable characters.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "untitled"


def _activity_path(activity_date: date, title: str) -> str:
    return f"{_ACTIVITIES_DIR}/{activity_date.isoformat()}-{_slugify(title)}.md"


def _plan_path(week_start: date) -> str:
    iso_year, iso_week, _ = week_start.isocalendar()
    return f"{_PLANS_DIR}/{iso_year}-W{iso_week:02d}-plan.md"


def _dump_frontmatter(model: SerializableModel, body: str) -> str:
    post = frontmatter.Post(body)
    post.metadata = model.model_dump(mode="json", exclude_none=True)
    return frontmatter.dumps(post)


class GitHubStorage:
    """CRUD facade over a private GitHub data repository.

    Construct directly with an injected ``Repository`` (useful for tests) or
    use :meth:`from_token` to build one from credentials at runtime.
    """

    def __init__(self, repo: Repository, branch: str = "main") -> None:
        self._repo = repo
        self._branch = branch

    @classmethod
    def from_token(
        cls, repo_full_name: str, token: str, branch: str = "main"
    ) -> "GitHubStorage":
        client = Github(token)
        return cls(client.get_repo(repo_full_name), branch=branch)

    # --- Low-level file operations -------------------------------------

    def read_file(self, path: str) -> str | None:
        try:
            contents = self._repo.get_contents(path, ref=self._branch)
        except GithubException as exc:
            if exc.status == 404:
                return None
            raise
        if isinstance(contents, list):
            raise ValueError(f"{path!r} is a directory, not a file.")
        return contents.decoded_content.decode("utf-8")

    def write_file(self, path: str, content: str, message: str) -> None:
        try:
            existing = self._repo.get_contents(path, ref=self._branch)
        except GithubException as exc:
            if exc.status != 404:
                raise
            existing = None

        if existing is None:
            self._repo.create_file(path, message, content, branch=self._branch)
            return

        if isinstance(existing, list):
            raise ValueError(f"{path!r} is a directory.")
        self._repo.update_file(
            path, message, content, existing.sha, branch=self._branch
        )

    def delete_file(self, path: str, message: str) -> None:
        existing = self._repo.get_contents(path, ref=self._branch)
        if isinstance(existing, list):
            raise ValueError(f"{path!r} is a directory.")
        self._repo.delete_file(path, message, existing.sha, branch=self._branch)

    def list_dir(self, path: str) -> list[str]:
        try:
            contents = self._repo.get_contents(path, ref=self._branch)
        except GithubException as exc:
            if exc.status == 404:
                return []
            raise
        if not isinstance(contents, list):
            return [contents.path]
        return [c.path for c in contents]

    # --- Activities ----------------------------------------------------

    def save_activity(self, activity: ActivitySchema, body: str) -> str:
        path = _activity_path(activity.activity_date, activity.title)
        self.write_file(path, _dump_frontmatter(activity, body), f"Save activity {path}")
        return path

    def load_activity(self, path: str) -> tuple[ActivitySchema, str] | None:
        raw = self.read_file(path)
        if raw is None:
            return None
        post = frontmatter.loads(raw)
        return ActivitySchema.model_validate(post.metadata), post.content

    def list_activities(self, year: int | None = None) -> list[str]:
        paths = [p for p in self.list_dir(_ACTIVITIES_DIR) if p.endswith(".md")]
        if year is not None:
            prefix = f"{_ACTIVITIES_DIR}/{year}-"
            paths = [p for p in paths if p.startswith(prefix)]
        return sorted(paths, reverse=True)

    def delete_activity(self, path: str) -> None:
        self.delete_file(path, f"Delete activity {path}")

    # --- Profile -------------------------------------------------------

    def load_profile(self) -> ProfileSchema | None:
        raw = self.read_file(_PROFILE_PATH)
        if raw is None:
            return None
        post = frontmatter.loads(raw)
        return ProfileSchema.model_validate(post.metadata)

    def save_profile(self, profile: ProfileSchema) -> None:
        body = profile.narrative or ""
        self.write_file(_PROFILE_PATH, _dump_frontmatter(profile, body), "Update profile")

    # --- Plans ---------------------------------------------------------

    def save_plan(self, plan: PlanSchema, body: str = "") -> str:
        path = _plan_path(plan.week_start)
        self.write_file(path, _dump_frontmatter(plan, body), f"Save plan {path}")
        return path

    def load_plan(self, path: str) -> tuple[PlanSchema, str] | None:
        raw = self.read_file(path)
        if raw is None:
            return None
        post = frontmatter.loads(raw)
        return PlanSchema.model_validate(post.metadata), post.content

    def load_current_plan(self) -> tuple[PlanSchema, str] | None:
        plan_paths = sorted(
            (p for p in self.list_dir(_PLANS_DIR) if p.endswith("-plan.md")),
            reverse=True,
        )
        if not plan_paths:
            return None
        return self.load_plan(plan_paths[0])
