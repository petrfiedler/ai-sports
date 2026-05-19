# AI Sports Planner & Tracker - Claude Code Instructions

## Project Overview
This is a personal, LLM-powered sports diary and weekly planner. The user inputs their workout data in natural language, and AI agents parse it into structured Markdown files with YAML Frontmatter. The app is deployed on Streamlit Community Cloud and uses a private GitHub repository as its database.

## Tech Stack
- **Language:** Python 3.10+
- **UI Framework:** Streamlit (`streamlit`)
- **Agent Framework:** Hugging Face `smolagents` 
- **LLM Provider:** Anthropic API (Claude models)
- **Data Validation:** `pydantic`
- **Data Serialization:** `python-frontmatter`
- **Database / Storage:** `PyGithub` (Committing directly to a private GitHub repo)
- **Strava Integration:** `stravalib` (or standard `requests` for API calls)

## Architectural Rules
1. **Separation of Concerns:** 
   - `src/ui/`: STRICTLY UI rendering (Streamlit). No business logic.
   - `src/agents/`: LLM logic and tool definitions. Agents return Pydantic models or plain data, NOT UI components.
   - `src/services/`: External API calls (GitHub, Strava).
2. **Data Storage (Crucial!):** 
   - DO NOT use local file I/O (e.g., `open('file.md', 'w')`) for user data (activities, profile, plans). 
   - Streamlit Cloud is ephemeral. ALWAYS use `PyGithub` in `src/services/storage.py` to read/write `.md` files as commits to the remote data repository.
3. **Secrets Management:** 
   - NEVER hardcode API keys or passwords.
   - Always use `st.secrets["SECRET_NAME"]` for Anthropic keys, GitHub PATs, Strava tokens, and the app password.

## Coding Standards
1. **Typing:** Use strict Python type hints (`mypy` compliant) for all functions, arguments, and return types.
2. **Pydantic First:** Always use Pydantic models (e.g., `ActivitySchema`) to validate LLM outputs from `smolagents` before saving them as YAML Frontmatter.
3. **Error Handling:** Streamlit apps must not crash. Wrap agent calls and API calls in `try-except` blocks. If an agent fails to parse text, return a polite fallback message to the UI asking the user to clarify.
4. **Style:** Write clean, PEP 8 compliant code. Do not add redundant inline comments; code should be self-explanatory.
5. **Cost Efficiency:** Limit maximum iterations/steps in `smolagents` to prevent infinite loops and API credit drain.

## Workflow & Commands
- **Run local server:** `streamlit run src/ui/app.py`
- **Install dependencies:** `pip install -r requirements.txt` (Always update this file when adding new libraries).

## Initial Setup Requirement
When asked to create the foundation, always start by building the Pydantic models (`src/models/schemas.py`) and the GitHub storage service (`src/services/storage.py`) before implementing the UI or Agents.