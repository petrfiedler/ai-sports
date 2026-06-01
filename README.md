# AI Sports Planner & Tracker

Personal AI sports diary & coach: log workouts in natural language,
auto-sync Strava, and get AI-generated weekly training plans.

## What it does

**ai-sports** replaces rigid fitness apps with a conversational interface.
Instead of clicking through menus, you just describe your workout:

> *"Bouldering today, 2 hours, tried some hard overhang routes but my fingers
> got pretty trashed."*

The AI extracts structured data, creates a beautiful activity record, and -
based on your goals and recent training load - suggests what to do next week.

## Features

- **Natural language logging**: describe workouts in free text, AI parses
  the rest
- **Strava sync**: automatically imports runs with pace, HR zones, route
  maps, and photos
- **AI weekly planner**: personalized training plans that respect fatigue
  (no intervals the day after heavy legs)
- **Conversational edits**: fix misunderstood exercises or adjust the plan
  with a plain-text command
- **Plaintext data model**: all data stored as Markdown + YAML frontmatter
  in a private GitHub repo - human-readable, LLM-friendly

## Architecture

The app is built on a **Multi-Agent System**:

| Agent | Role |
|---|---|
| Parser Agent | Converts free text to structured Markdown activity |
| Sync Agent | Fetches Strava activities in the background |
| Planner Agent | Generates & adjusts weekly training plans |

UI is built with **Streamlit**.

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Copy the example secrets file and fill in your values:
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# Run the app locally:
streamlit run src/ui/app.py
```

## Development

```bash
# Run tests:
pytest

# Type checking:
mypy src/
```

## Data model

Each activity is a Markdown file with YAML frontmatter stored in a private
GitHub repo:


```
data/
├── profile.md              # goals & preferences
├── activities/
│   └── 2026-06-01-bouldering.md
└── plans/
    └── 2026-W23-plan.md
```

## License

MIT