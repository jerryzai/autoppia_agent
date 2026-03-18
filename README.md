# Subnet 36 Web Agent

LLM-powered web agent for Bittensor Subnet 36. Exposes `GET /health` and `POST /act` as required by validators.

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Configure (copy and add OPENAI_API_KEY)
cp .env.example .env

# Run
uvicorn main:app --host 0.0.0.0 --port 5000
```

## API Contract

- **GET /health** - Returns `{"status": "healthy"}`
- **POST /act** - Accepts task/HTML/history, returns `{"actions": [{"type": "...", ...}]}`

## Environment

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Your OpenAI API key (or Chutes etc. via gateway) |
| `OPENAI_BASE_URL` | Override API URL (sandbox sets this to gateway) |
| `OPENAI_MODEL` | Model name (default: gpt-4o-mini) |

## Miner Setup

1. Push this repo to GitHub
2. In `autoppia_web_agents_subnet/.env` set:
   ```
   GITHUB_URL="https://github.com/yourusername/my_agent/commit/abc123..."
   AGENT_NAME="My Agent"
   ```
3. Start the miner with PM2

## Leaderboard task prompts

Eval tasks and natural-language prompts are listed at:

`https://api-leaderboard.autoppia.com/api/v1/tasks/search?successMode=all&page=1&limit=100&includeDetails=false`

Paginate with `page=2`, etc. To dump locally:

```bash
python scripts/fetch_leaderboard_tasks.py --out data/leaderboard_tasks.json
```

Each row has `useCase` (e.g. `FILM_DETAIL`, `MARK_AS_UNREAD`) and `prompt` with constraints. The agent parses common IWA phrasing (`genres field CONTAINS`, `does NOT equal`, `less equal`, …) into `TASK_CONSTRAINTS` for the LLM. Tune `_classify_task` / `_TASK_PLAYBOOKS` in `agent.py` for weak use cases.

## Supported Actions

- `navigate` - `{"type": "navigate", "url": "https://..."}`
- `click` - `{"type": "click", "selector": "#submit-btn"}`
- `input` - `{"type": "input", "selector": "#email", "value": "text"}`
