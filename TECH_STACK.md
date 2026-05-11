# Technical Architecture & Stack: AI Sports Planner

## 1. Technology Stack

Since the primary goal is a fast, robust implementation using Python and LLM agents, the stack is optimized for backend simplicity and dynamic AI interactions without the overhead of a complex frontend framework or relational database.

### Core & Backend
- **Language:** Python 3.10+ (Strictly typed with `mypy` hints).
- **LLM Framework:** `smolagents` (by Hugging Face) - Lightweight agent framework perfect for Python-native tool calling and reasoning.
- **LLM Provider:** Anthropic API (Claude 3.5/3.7 Sonnet) - Used for both the Parser and Planner agents.
- **Data Validation:** `pydantic` - Crucial for ensuring the LLM's output matches the required schema before writing to files.

### Frontend / UI
- **Framework:** `Streamlit` - A pure-Python web framework. It natively supports rendering Markdown, interactive widgets, data visualization (matplotlib/plotly for heart rate/pace charts), and has built-in chat UI components perfect for the "Quick Add" and Q&A features.

### Storage & Data Management
- **Database:** Private GitHub Repository (`ai-sports-data`).
- **Data Format:** Markdown with YAML Frontmatter.
- **Library:** `PyGithub` and `python-frontmatter`. 
- **Workflow:** The `storage.py` service reads and writes `.md` files directly to the private data repository via GitHub API commits, bypassing the ephemeral local file system.

### Deployment & Security
- **Hosting:** Streamlit Community Cloud (Free tier).
- **Security:** 
  - Application locked behind a simple password prompt using Streamlit session state.
  - Secrets (Anthropic API Key, GitHub PAT, App Password, Strava tokens) securely managed via `st.secrets`.

### Integrations
- **Strava API:** `stravalib` (or `requests`) - For OAuth2 authentication and fetching activity data (distance, HR, GPX/TCX paths).

---

## 2. Project Structure

A modular architecture separating the user interface, agent logic, and data storage.

```text
ai-sports-planner/
├── data/                       # Local database (git-ignored if needed)
│   ├── activities/             # e.g., 2026-05-10-bouldering.md
│   ├── plans/                  # e.g., 2026-W20-plan.md
│   └── profile.md              # User goals and preferences
├── src/
│   ├── agents/                 # LLM Agent definitions
│   │   ├── parser_agent.py     # Extracts structured data from raw text
│   │   ├── planner_agent.py    # Generates the weekly schedule
│   │   └── tools.py            # Custom functions (tools) the agents can call
│   ├── models/                 # Pydantic schemas representing data structures
│   │   └── schemas.py          # ActivitySchema, PlanSchema, ProfileSchema
│   ├── services/               # Business logic and external API communication
│   │   ├── storage.py          # CRUD operations for Markdown/Frontmatter files
│   │   └── strava_sync.py      # Strava API authentication and data fetching
│   └── ui/                     # Streamlit frontend components
│       ├── components.py       # Reusable UI parts (e.g., Q&A panel, activity card)
│       ├── pages/              # Streamlit multipage routing
│       │   ├── 1_Dashboard.py
│       │   ├── 2_Activity_Detail.py
│       │   └── 3_Weekly_Plan.py
│       └── app.py              # Main Streamlit entry point
├── tests/                      # Pytest directory
├── .env                        # API keys (Anthropic, Strava Client ID/Secret)
├── .gitignore
├── requirements.txt            # or pyproject.toml
├── DESIGN.md                   # Product design specification
├── TECH_STACK.md               # This file
└── CLAUDE.md                   # System instructions for the Claude Code CLI tool
```

---

## 3. Data Flow Example (Logging an Activity)

1. **User Input:** User types free text in the Streamlit UI (`src/ui/pages/1_Dashboard.py`).
2. **Agent Processing:** Streamlit calls `parser_agent.py`. The agent reads the text and attempts to populate a Pydantic model (`ActivitySchema`).
3. **Missing Data Handling:** If `ActivitySchema` validation fails or the agent deems data incomplete, the agent returns a list of questions back to the UI.
4. **Storage:** Once the schema is complete (or user skips questions), `storage.py` serializes the Pydantic model into YAML Frontmatter, appends the raw text as the Markdown body, and saves the `.md` file in `data/activities/`.
5. **UI Update:** Streamlit re-renders the Dashboard, displaying the newly parsed Markdown file.

---

## 4. Development Guidelines (for Claude Code)
- **Modularity:** Keep agents unaware of the Streamlit UI. Agents should return pure data (Pydantic models, strings, or dicts). UI rendering happens strictly in `src/ui/`.
- **Typing:** Use strict Python type hints everywhere.
- **Fail Gracefully:** If the LLM returns unparseable data, catch the error and ask the user to rephrase, rather than crashing the app.