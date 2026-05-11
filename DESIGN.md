# Application Design: AI Sports Planner & Tracker

## Abstract
The application serves as a personal, fully flexible sports diary and AI coach. While traditional fitness apps force users to click through sets, reps, and pick exercises from predefined lists, this application relies on natural language processing (NLP). The user describes their activity in free text (e.g., "Bouldering today, tried some hard overhang routes, but my fingers got pretty trashed, did about 1.5 hours") and the AI agent automatically extracts structured data, creates a visually appealing record, and optionally asks for details. The app also automatically fetches running activities from Strava and, based on all data and defined personal goals, suggests a training plan for the upcoming week. The entire configuration, modifications, and data persistence are managed in Plaintext (Markdown), which is then dynamically rendered into a modern, clean UI.

## Architecture and AI Agents
The system is built on a Multi-Agent System architecture. These agents process user text, communicate with external APIs, and modify the underlying data layer.

1. **Parser Agent (Logging)**
   - **Purpose:** Takes free text input and converts it into structured data (Markdown format of the activity).
   - **Behavior:** Detects the sport and identifies parameters (duration, weights, reps, feelings/RPE). If it misses key metrics for a specific sport, it generates a series of follow-up questions (e.g., for swimming it might ask "How long did you swim?").
2. **Sync Agent (Strava Integration)**
   - **Purpose:** Runs in the background and communicates with the Strava API.
   - **Behavior:** Fetches historical and newly tracked running activities. Downloads metadata (distance, pace, HR zones from smartwatches) and saves them in the exact same Markdown format as manually entered activities.
3. **Planner Agent (Training Plan)**
   - **Purpose:** Generates a recommended training plan for the upcoming week.
   - **Behavior:** Takes the user profile (sports goals, preferences) and the history of recent activities into account. Ensures the plan reflects current fatigue (e.g., it will not suggest an interval run the day after a heavy leg-day at the gym). The plan can be iteratively adjusted using natural language prompts.

## Data Model (Plaintext / Markdown)
All data persistence relies on local Markdown files with YAML Frontmatter. This format is entirely natural for an LLM to read and write, while being easy to parse and render into a nice UI on the frontend.

- **Profile (`profile.md`):** Where the user defines their goals (e.g., "I want to run a half marathon under 2 hours, I lift weights for core stability, and I boulder for fun").
- **Activities (`/activities/YYYY-MM-DD-title.md`):** Each logged activity is saved as a single markdown file.
- **Plan (`/plans/current.md`):** The saved training plan for the current or upcoming week.

## UI and Key Pages

### 1. Dashboard & Calendar
- **Calendar View:** Displays a history of activities (both Strava syncs and manual logs) as well as future planned activities.
- **Logging Input (Quick Add):** The main text prompt bar at the top. The user simply types: "Yesterday 45 minutes of dumbbell workout (10kg bicep curls 3x10, squats 3x15)".
- **Weekly Overview:** A visual representation of training volume and weekly plan completion.

### 2. Activity Page (Activity Detail)
- **Header:** Sport icon, title, date, duration, and potentially Rate of Perceived Exertion (RPE).
- **Processed Output:** Beautifully rendered tables (for sets/reps/weights), charts (for Strava runs - heart rate, pace), and text notes ("feelings").
- **Q&A Panel (Follow-up Questions):** If the Parser Agent determines the data is incomplete, it displays follow-up text fields here (e.g., "What was the rest time between sets?"). These can be filled out or completely ignored via a "Skip" button.
- **Raw Edit / Master Prompt:** A field at the bottom of the page. If the user notices the AI misunderstood an exercise, they type: "Change those squats, they weren't standard but Bulgarian split squats". The background Agent modifies the source Markdown based on the instruction, and the UI instantly re-renders.

### 3. Weekly Planner
- **Generated Plan:** Displayed for 7 days ahead.
- **Conversational Adjustments:** A text field below the plan: "It's raining on Tuesday, move the run to Wednesday and give me a home upper-body workout on Tuesday instead." The Planner Agent instantly generates a new revision of the plan.

## User Workflow
1. The user opens the app and sees their calendar.
2. They type into the Quick Add textbox: "Great bouldering session today for 2 hours, did some heavy overhangs."
3. The Agent analyzes the input. It saves the activity as sport `bouldering`, duration `120 min`, intensity `high`. A new activity page is dynamically created.
4. On the activity page, the Agent generates a prompt: "Do you want to add the estimated difficulty (V-scale / Font scale) for those overhangs?". The user clicks "Skip".
5. On Sunday evening, the user opens the Planner, reviews the suggestion for the next week, and either confirms it or modifies it with a simple text command.