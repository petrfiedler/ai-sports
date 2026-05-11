# ai-sports

Personal AI sports diary &amp; coach. Log workouts using natural language, auto-sync Strava, and get AI-generated weekly plans.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Copy the example secrets file and fill in your values:
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# Run the app locally:
streamlit run src/ui/app.py

# Run the test suite:
pytest
```

See [DESIGN.md](DESIGN.md) and [TECH_STACK.md](TECH_STACK.md) for product spec and architecture, and [ROADMAP.md](ROADMAP.md) for the phase-by-phase build plan.
