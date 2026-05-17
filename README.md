# Portfolio Optimization Project

Personal portfolio optimization system. Two tracks:

- **Track A — Synapse-style.** Quarterly/yearly rebalancing, F-Score filtering, MILP-CVaR optimization. ~€21k inside Aktiesparekonto.
- **Track B — Fast Ideas.** Monthly single-stock recommendation engine with LLM-written theses. ~€2k sleeve.

## Status

Track B v0.1 is in development. Track A is spec'd but not started.

See `docs/STATE.md` for the current state of play. See `docs/DECISIONS.md` for the decision history.

## Setup

### One-time

```bash
# Create virtual environment (using uv — faster than pip)
uv venv
source .venv/bin/activate           # macOS/Linux
# .venv\Scripts\activate            # Windows PowerShell

# Install dependencies
uv pip install -r requirements.txt

# Copy environment template and fill in your API key
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY=sk-ant-...
```

### Each session

```bash
# Activate environment
source .venv/bin/activate

# Start Claude Code
claude
```

Claude Code reads `CLAUDE.md` for project context and `docs/STATE.md` for what to work on.

## Project layout

```
portfolio-opt/
├── docs/
│   ├── STATE.md          # current state — read first every session
│   ├── DECISIONS.md      # append-only decision log
│   ├── BACKLOG.md        # parked items
│   └── BLOCKERS.md       # current blockers
├── track_b/              # Fast Ideas (under construction)
├── track_a/              # Synapse-style (not started yet)
├── CLAUDE.md             # Claude Code context
├── requirements.txt
├── .env.example
└── README.md
```

## Decision tracking

Every decision goes in `docs/DECISIONS.md` with date, rationale, and rejected alternatives. If a decision needs reversing, add a new entry that explicitly supersedes the old one. Never silently overwrite.
