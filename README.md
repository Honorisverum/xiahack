# Voice Agent

## Requirements

- Python ≥ 3.11 + [uv](https://docs.astral.sh/uv/)
- Node.js ≥ 20 + pnpm
- LiveKit Cloud account (free)

## Setup

### 1. Environment Variables

Create `.env` in root:

```bash
LIVEKIT_API_KEY=<your_key>
LIVEKIT_API_SECRET=<your_secret>
LIVEKIT_URL=wss://your-project.livekit.cloud
XAI_API_KEY=<your_xai_key>
```

### 2. Backend

```bash
uv run backend/app.py download-files  # download models (first time)
uv run backend/app.py console | dev | start             # start dev mode
```

### 3. Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

Open http://localhost:3000

