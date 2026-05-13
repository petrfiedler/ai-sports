# Roadmap: AI Sports Planner & Tracker

A concrete, phase-by-phase plan from the current state (Pydantic schemas + scaffolding committed) to a working deployment on Streamlit Community Cloud.

Each phase lists: **Goal**, **Touches** (files), **Steps**, and **Done when** (concrete acceptance criteria). Phases are ordered so each one produces something testable on top of the previous.

---

## Current State (Phase 0 — done)

- Folder layout: `src/{agents,models,services,ui}`, `tests/`.
- `requirements.txt` with all chosen dependencies.
- `src/models/schemas.py` — Pydantic v2 schemas: `ActivitySchema`, `ProfileSchema`, `PlanSchema`, plus `Exercise`, `ExerciseSet`, `EnduranceMetrics`, `PlannedActivity`, `FollowUpQuestion`, `ParseResult`, and enums (`SportType`, `ActivitySource`, `Intensity`).
- Initial commit `13391b5` (1 ahead of `origin/main`, not yet pushed).

---

## Phase 1 — Storage service (private GitHub repo as DB)

**Goal:** Read/write Pydantic models as Markdown + YAML frontmatter files in a private GitHub data repository. This is the foundation everything else depends on, so it lands before any agent or UI.

**Touches**
- `src/services/storage.py` (new)
- `src/services/__init__.py` (re-export `GitHubStorage`)
- `tests/test_storage.py` (new)

**Steps**
1. Create the private repo manually on GitHub (e.g. `petr1fiedler/ai-sports-data`) with an initial `README.md` so the default branch exists.
2. Generate a fine-grained Personal Access Token scoped only to that repo (contents: read/write).
3. Implement `GitHubStorage` class in `storage.py`:
   - Constructor takes `(repo_full_name: str, token: str, branch: str = "main")`.
   - `read_file(path) -> str | None` (returns `None` on 404).
   - `write_file(path, content, message) -> None` (creates or updates).
   - `list_dir(path) -> list[str]`.
   - `delete_file(path, message)`.
4. Add high-level helpers that speak Pydantic, not bytes:
   - `load_profile() -> ProfileSchema | None`
   - `save_profile(p: ProfileSchema)`
   - `save_activity(a: ActivitySchema, body: str)` → path `activities/{date}-{slug}.md`, frontmatter = `a.model_dump(mode="json")`, body = raw user text.
   - `load_activity(path) -> tuple[ActivitySchema, str]`
   - `list_activities(year: int | None = None) -> list[str]`
   - `save_plan(p: PlanSchema)` / `load_current_plan()` → `plans/{YYYY-Www}-plan.md`.
5. Use `python-frontmatter` for the serialization round-trip; convert dates/datetimes to ISO strings explicitly so YAML stays clean.
6. Tests: monkeypatch the PyGithub client; verify slug generation, frontmatter round-trip (`load(save(x)) == x`), and that `save_activity` chooses the expected path.

**Done when:** From a Python shell I can call `storage.save_activity(...)` and see a real commit appear in the data repo, and `storage.load_activity(path)` returns an equivalent `ActivitySchema`.

---

## Phase 2 — Config & secrets plumbing

**Goal:** One single place to read every secret, both locally and on Streamlit Cloud, so no module reaches into `os.environ` or `st.secrets` directly.

**Touches**
- `src/config.py` (new)
- `.streamlit/secrets.toml.example` (new, committed; the real `secrets.toml` is already gitignored)
- `tests/test_config.py` (new)

**Steps**
1. Define a `Settings` Pydantic model with the fields we actually need:
   - `anthropic_api_key`, `github_token`, `github_data_repo`, `app_password`,
   - Strava: `strava_client_id`, `strava_client_secret`, `strava_refresh_token` (filled in Phase 7),
   - optional: `default_branch`, `llm_model` (default `"claude-sonnet-4-6"`), `agent_max_steps` (default `6`).
2. `get_settings()` loads from `st.secrets` if running under Streamlit, else from environment variables — cached with `functools.lru_cache`.
3. Write `secrets.toml.example` documenting every key.

**Done when:** `from src.config import get_settings; get_settings()` works both in `streamlit run` and `python -c`, and missing required keys raise a clear `ValueError` instead of `KeyError`.

---

## Phase 3 — Parser Agent

**Goal:** Turn free-text input (Czech or English) into a validated `ActivitySchema`, with follow-up questions when key fields are missing.

**Touches**
- `src/agents/parser_agent.py` (new)
- `src/agents/tools.py` (new, minimal at this stage)
- `src/agents/prompts.py` (new — keep system prompts out of the code)
- `tests/test_parser_agent.py` (new — uses recorded fixtures, not live API)

**Steps**
1. Pick the smolagents flavor: a `ToolCallingAgent` with an Anthropic backend (via the `anthropic` SDK or smolagents' `LiteLLMModel` pointed at Claude).
2. Single tool exposed to the agent: `submit_activity(activity: ActivitySchema, questions: list[FollowUpQuestion]) -> None`. The agent's job is to call it exactly once.
3. System prompt covers:
   - Today's date (passed in at runtime) so "yesterday" / "minulý čtvrtek" resolve correctly.
   - Sport list and what counts as required per sport (e.g. running needs duration, optionally distance; strength needs at least one exercise).
   - Rule: never invent data. Missing → `follow_up_questions`, not a guess.
4. Public function `parse_activity(text: str, *, today: date | None = None) -> ParseResult`. Wraps the agent in `try/except`, caps `max_steps` from `Settings`, returns `ParseResult(fallback_message=...)` on any failure.
5. Tests:
   - One golden case per sport (running, bouldering, strength, swim) using a stubbed model that replays a canned JSON response — verifies our schema mapping, not Claude.
   - One "garbage input" case → `activity is None`, `fallback_message` set.

**Done when:** A short script `python -m src.agents.parser_agent "Yesterday bouldering 90 min, V4-V5 overhangs"` prints a populated `ActivitySchema` JSON.

---

## Phase 4 — UI bootstrap + password gate + nav

**Goal:** A Streamlit app that boots, requires the app password, and renders empty placeholder pages. No business logic yet — just the shell.

**Touches**
- `src/ui/app.py` (new, entry point)
- `src/ui/auth.py` (new)
- `src/ui/components.py` (new, empty placeholder helpers)
- `src/ui/pages/1_Dashboard.py` (new, stub)
- `src/ui/pages/2_Activity_Detail.py` (new, stub)
- `src/ui/pages/3_Weekly_Plan.py` (new, stub)
- `src/ui/pages/__init__.py` (new)
- `.streamlit/config.toml` (new — theme, `server.runOnSave = true` for dev)

**Steps**
1. `auth.require_password()` — reads `app_password` from `Settings`, stores `st.session_state["authenticated"]`, shows a `st.text_input(type="password")` until correct. Called at the top of every page.
2. `app.py` sets page config, calls `require_password()`, then renders a short landing screen ("Welcome — open Dashboard from the sidebar"). Streamlit's multi-page routing handles the rest.
3. Each page file starts with the same auth check and a single `st.header(...)` so we can confirm routing works.
4. Add `streamlit run src/ui/app.py` to the README dev section.

**Done when:** `streamlit run src/ui/app.py` shows a password prompt; on correct password I land on the welcome screen and can navigate to all three stub pages.

---

## Phase 5 — Dashboard: Quick Add + activity list

**Goal:** The first end-to-end vertical slice. User types a workout in the Quick Add box → Parser Agent runs → activity is saved to GitHub → it appears in the list.

**Touches**
- `src/ui/pages/1_Dashboard.py` (flesh out)
- `src/ui/components.py` (add `activity_card`, `follow_up_panel`)
- `src/services/storage.py` (any helpers that turned out missing in Phase 1)

**Steps**
1. Quick Add: a `st.text_area` + Submit button. On submit:
   - Call `parse_activity(text)`.
   - If `result.activity` is `None` → show `fallback_message`.
   - Else → `storage.save_activity(result.activity, body=text)` and `st.rerun()`.
   - If `result.questions` is non-empty → stash them in `st.session_state` keyed by the new activity path so the detail page can pick them up.
2. Activity list:
   - `storage.list_activities()` → newest first.
   - Render each via `activity_card` (sport icon, title, date, duration, RPE badge). Click → `st.switch_page` to the detail page with the path in query params.
3. Weekly overview widget: simple total-minutes-this-week metric and a per-sport breakdown bar chart (Plotly). Keep it small; it's a teaser, not the focus.
4. Loading + error states: wrap agent + GitHub calls in `with st.spinner(...)` and `try/except` that surfaces a `st.error` instead of crashing.

**Done when:** I can type "30 min easy run this morning" in the deployed-style local app, see a spinner, then see the activity appear in the list, and confirm the `.md` file exists in the data repo on GitHub.

---

## Phase 6 — Activity Detail page

**Goal:** Render a parsed activity beautifully and let the user (a) answer follow-up questions and (b) issue free-form edit instructions.

**Touches**
- `src/ui/pages/2_Activity_Detail.py`
- `src/agents/parser_agent.py` — add `revise_activity(current: ActivitySchema, instruction: str) -> ParseResult`
- `src/ui/components.py` — `render_strength_table`, `render_endurance_charts`, `render_followups`

**Steps**
1. Read `?path=` from query params, load the activity via storage.
2. Header: sport emoji, title, date, duration, intensity/RPE chip.
3. Body sections, conditional on sport:
   - Strength: a table of exercises × sets (reps / weight / duration / rest).
   - Endurance with metrics: HR + pace charts via Plotly (only if data present — skip cleanly when not).
   - Notes: render the Markdown body verbatim.
4. Follow-up Q&A panel: if the activity has `follow_up_questions`, render each as a text input + a "Skip" button. Submitting answers calls `revise_activity` with a structured instruction, saves the result.
5. Master prompt at the bottom: `st.text_input("Tell the AI what to fix…")` → `revise_activity(current, instruction)` → save → rerun.
6. Delete button (with `st.popover` confirm) → `storage.delete_file(path, ...)`.

**Done when:** I can open an activity I logged in Phase 5, fix something with a sentence ("those were Bulgarian split squats"), and see the rendered detail update plus a new commit in the data repo.

---

## Phase 7 — Strava integration (Sync Agent)

**Goal:** Pull running activities from Strava and persist them in the same Markdown format, including the route map and any photos so the Activity Detail page renders them. Photos and the map basemap are fetched from Strava / OSM at view time — we only store references (polyline + photo URLs), not binary assets. This is independent of Phases 5–6 and could slip later if time runs short.

**Touches**
- `src/services/strava_sync.py` (new)
- `src/agents/sync_agent.py` (new — orchestrates the import; very thin)
- `src/models/schemas.py` — extend `EnduranceMetrics` with `map_polyline: Optional[str]` and `photo_urls: list[str]` (default `[]`).
- `src/ui/pages/1_Dashboard.py` — add a "Sync Strava" button
- `src/ui/pages/2_Activity_Detail.py` — render route map + photo gallery when fields are present (additive: existing strength/endurance/notes layout unchanged).
- `src/ui/components.py` — `render_route_map(polyline: str)`, `render_photo_gallery(urls: list[str])`.
- `src/config.py` — Strava fields become required
- `requirements.txt` — add `polyline` (decode Strava's encoded polyline) and `streamlit-folium` + `folium` (interactive route map on OSM tiles).

**Steps**
1. Strava OAuth setup (one-time, outside the app):
   - Register a Strava API application; get `client_id`/`client_secret`.
   - Ensure the requested scope includes `activity:read_all` so we can fetch photo URLs in addition to summary data.
   - Run a small helper script (`scripts/strava_authorize.py`, kept out of `src/`) that walks the auth-code flow once locally and prints the long-lived `refresh_token`. Paste the result into `secrets.toml`.
2. `StravaClient`:
   - Uses the refresh token to mint short-lived access tokens (`stravalib` or raw `requests`).
   - `recent_activities(since: date) -> list[dict]` — list endpoint, returns summary including `map.summary_polyline`.
   - `activity_photos(activity_id: int, size: int = 1024) -> list[str]` — `GET /activities/{id}/photos?size={size}&photo_sources=true`, returns a list of CDN URLs (largest variant per photo). Empty list when the activity has no photos.
3. Schema extension (lands first in this phase):
   - Add `map_polyline: Optional[str]` to `EnduranceMetrics` — Google-encoded polyline string straight from Strava (`summary_polyline`). Stored as-is; decoded only at render time.
   - Add `photo_urls: list[str] = []` to `EnduranceMetrics` — Strava CDN URLs. We persist the URL only; the image bytes stay on Strava and are loaded by the browser via `st.image(url)`.
   - Round-trip the new fields through the frontmatter test in `tests/test_storage.py` (or `test_schemas.py`) so they survive load/save.
4. `sync_recent()`:
   - Determine "since" = latest stored Strava activity date (or 30 days ago on first run).
   - For each new activity: build an `ActivitySchema` (sport ↔ Strava type mapping, distance, avg HR, etc.) with `source = STRAVA` and a synthesized body ("Synced from Strava.").
   - Populate `metrics.map_polyline` from the activity's `map.summary_polyline` (skip if empty — e.g. treadmill runs have no route).
   - If the activity's `total_photo_count > 0`, call `activity_photos(id)` and stash the URLs in `metrics.photo_urls`. Otherwise leave the list empty.
   - Use `metrics.strava_id` for dedup — skip if already stored.
   - `storage.save_activity` each one.
5. Activity Detail rendering (additive, runs on every activity but only renders when the fields are present):
   - `render_route_map`: decode `metrics.map_polyline` with the `polyline` library, build a `folium.Map`, drop a `PolyLine` overlay, fit bounds to the route, and embed via `streamlit-folium.st_folium`. Skip cleanly when polyline is absent or unparseable.
   - `render_photo_gallery`: lay the URLs out in a responsive grid (e.g. `st.columns(3)`) and pass each URL straight to `st.image(url, use_container_width=True)` — no downloading, no caching, no GitHub round-trip. Skip cleanly when the list is empty.
   - Both renderers are also safe to call for manual activities (polyline/photo_urls are simply absent), so the detail page doesn't need source-specific branching.
6. Dashboard wires a button "Sync Strava" that calls `sync_recent()` and reports the count of new activities.

**Done when:** Clicking "Sync Strava" once imports my actual last run from Strava into the data repo with HR + pace, and clicking it again imports nothing (dedup works). Opening that synced run on the Activity Detail page shows the route drawn on an interactive map and any photos attached to the activity, both loaded live from Strava/OSM with no binary assets stored in the data repo.

---

## Phase 8 — Planner Agent

**Goal:** Generate a `PlanSchema` for the upcoming week based on `ProfileSchema` + recent activities. Iterative refinement via natural language.

**Touches**
- `src/agents/planner_agent.py` (new)
- `src/agents/prompts.py` — planner prompt
- `tests/test_planner_agent.py` (new — stubbed model fixtures)

**Steps**
1. `generate_plan(profile, recent_activities, week_start) -> PlanSchema`:
   - Builds context: profile narrative + goals + last 14 days summarized (sport, duration, intensity, RPE).
   - System prompt rules: respect recovery (no hard legs day after long run), honor constraints, fill the week with 4–6 sessions by default, week_start must be a Monday.
   - Single tool `submit_plan(plan: PlanSchema)`.
2. `revise_plan(current: PlanSchema, instruction: str) -> PlanSchema` — same agent, different prompt context, returns the new revision.
3. Persist via `storage.save_plan`.

**Done when:** From a script, given a stubbed profile and a few recent activities, the agent emits a 7-entry plan starting on the correct Monday that survives Pydantic validation.

---

## Phase 9 — Weekly Plan page

**Goal:** UI for viewing, refining, and checking off the plan.

**Touches**
- `src/ui/pages/3_Weekly_Plan.py`
- `src/ui/components.py` — `render_plan_day`

**Steps**
1. On page load: try `storage.load_current_plan()`. If none, show a single "Generate plan for week of …" button.
2. Render the 7 days as columns (or a stacked layout on narrow viewports); each card shows title, sport, duration, intensity, description, and a "Completed" checkbox.
3. Conversational adjustment box at the bottom: instruction → `revise_plan` → save → rerun.
4. "Regenerate from scratch" secondary button — confirm dialog because it overwrites.
5. Completed flips persist by updating the plan file (no need for a separate state store).

**Done when:** I can generate a plan, tick a day as done, ask "move Tuesday's run to Wednesday", and see the change reflected and committed.

---

## Phase 10 — Profile page + polish

**Goal:** Let the user edit their goals/preferences, plus cleanup before deploy.

**Touches**
- `src/ui/pages/4_Profile.py` (new)
- `src/ui/components.py` (assorted)
- `README.md` (update with screenshots / setup steps)

**Steps**
1. Profile page: form for name, goals list, preferred sports (multiselect), weekly target hours, constraints list, narrative textarea. Save → `storage.save_profile`.
2. Empty states everywhere: "no activities yet", "no plan yet", "Strava not connected".
3. Loading spinners + a global `try/except` in each page so a single API error never blanks the app.
4. mypy pass: `mypy src/` clean (add ignores only where unavoidable — e.g. smolagents internals).
5. Smoke tests: at least one test per page importing the module to catch syntax/import regressions on Python 3.10.

**Done when:** `mypy src/` is clean and the app can be navigated end-to-end without a single uncaught exception.

---

## Phase 11 — Deploy to Streamlit Community Cloud

**Goal:** Live, password-protected URL.

**Steps**
1. Push the code repo to a public (or private — both work on free tier) GitHub repo. Confirm `.streamlit/secrets.toml` is **not** in the push.
2. On <https://streamlit.io/cloud>:
   - "New app" → pick the repo and branch → main file: `src/ui/app.py`.
   - Python version: 3.10 or newer matching the local dev version.
   - Paste `requirements.txt` content into the dependencies field (Streamlit reads it automatically).
3. App settings → Secrets: paste the full `secrets.toml` content (Anthropic key, GitHub PAT, app password, Strava credentials, data repo name).
4. Deploy. Watch the build log. Common gotchas:
   - Wheels for `stravalib` — pin a known-good version if pip resolves slowly.
   - Cold-start latency on the first agent call (~10–20 s) is normal.
5. Smoke-test on the live URL: password login → Quick Add → see file in data repo → open detail → generate plan.
6. Lock down: confirm the GitHub PAT is scoped to the data repo only. Rotate it if it was ever in plaintext outside `st.secrets`.

**Done when:** I can open the deployed URL on my phone, log in, type "30 min easy run", and see a new commit land in the data repo within a few seconds.

---

## Post-launch backlog (not part of v1)

These are deferred deliberately to keep v1 shippable:

- Calendar view on the Dashboard (real month grid, not just a list).
- Charts for trend analysis (volume per week, HR drift, etc.).
- Export/share a plan as a PDF.
- Multi-user support (currently single-user by design — the password gate is enough).
- Mobile-specific layout tweaks beyond what Streamlit gives for free.

---

## Working order summary

```
Phase 1 (storage)  ──► Phase 2 (config) ──► Phase 3 (parser) ──► Phase 4 (UI shell)
                                                                       │
                                                                       ▼
                                          Phase 5 (dashboard + quick add)
                                                                       │
                                                                       ▼
                                                  Phase 6 (activity detail)
                                                                       │
                                          ┌────────────────────────────┤
                                          ▼                            ▼
                            Phase 7 (Strava sync)        Phase 8 (planner agent)
                                                                       │
                                                                       ▼
                                                       Phase 9 (weekly plan UI)
                                                                       │
                                                                       ▼
                                                  Phase 10 (profile + polish)
                                                                       │
                                                                       ▼
                                                          Phase 11 (deploy)
```

Phases 7 and 8 are the only ones that can run in parallel; everything else is strictly sequential.
