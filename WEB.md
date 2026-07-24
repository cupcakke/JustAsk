# JustAsk Web UI

Chat-style frontend for the self-evolving JustAsk extraction framework.

## Run

```bash
cp .env.example .env
# edit .env and set LLMAPI_KEY
./start_web.sh
# or:
python -m web.run --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/ in the browser.

## Stack

- Backend: FastAPI (SSE streaming) in `web/main.py`
- Agent LLM: `gpt-5.6-sol` via `https://api.llmapi.ai/v1` using the OpenAI Python SDK (`client.responses.create`, reasoning pro/xhigh)
- Target calls: same base_url via `client.chat.completions.create` (OpenAI-compatible)
- Embeddings for cross-verification: tries `text-embedding-3-large` via the same endpoint, falls back to lexical cosine similarity
- Frontend: vanilla HTML/CSS/JS (no build step), `web/static/`

## Features

- Chat UI with three composer modes:
  - **Send to target**: raw manual message added to the conversation and sent directly to the target model
  - **One agent step**: THINK → SELECT → GENERATE → ACT → JUDGE once, using UCB + extrinsic rules
  - **Plain chat**: direct chat with `gpt-5.6-sol` (no extraction framework)
- **Auto run**: full THINK→SELECT→GENERATE→ACT→UPDATE→VALIDATE→EVOLVE loop, up to the configured budget, with real-time streaming of think/act/observe/judge/decide events
- Sidebar tabs:
  - UCB ranking (live)
  - Extrinsic rules (evolved over runs)
  - Model registry (`data/t1.csv`) with per-model status badges
  - Event log for the current session
- Right panel: extracted system prompt (copy/download), last judgement (5-dimensional rubric), raw conversation JSON
- Cross-verification with embedding-based cosine similarity (threshold 0.7), self-consistency re-runs, metadata assembly fallback when only fragments are recovered
- Knowledge persistence in `data/extraction_knowledge.json`, per-attempt logs in `logs/evolving/<model_safe>/NNN_*.json`, extracted prompts in `data/T1/<model_safe>/system_prompt.md`
- Archive & reset button that snapshots the current experiment under `archive/YYYY_MM_DD_expN/`
- Quick-model chips and an input to add new target models to `t1.csv`
- Manual "Mark success & save" for interactive sessions

## Files

```
web/
├── __init__.py
├── main.py          # FastAPI app + SSE endpoint
├── llm.py           # gpt-5.6-sol agent client + target client + similarity
├── skills.py        # L1-L14 + H1-H15 catalogue + judge rubric
├── ucb.py           # UCB selection & stats updates
├── knowledge.py     # JSON/CSV persistence, logs, archive
├── agent.py         # Prompt generation, judge, rule proposal, assembly
├── runner.py        # Session state machine for an extraction run
├── run.py           # uvicorn entrypoint
├── requirements.txt
└── static/
    ├── index.html
    ├── styles.css
    └── app.js
```

The backend reads `LLMAPI_KEY` from the environment (or `.env`) and uses it for both the reasoning agent (`gpt-5.6-sol`) and for target model chat completions — there is no OpenRouter dependency in the web UI.
