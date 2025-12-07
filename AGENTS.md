# Repository Guidelines

## Project Structure & Modules
- `backend/`: LiveKit agent servers (`app.py` for a simple assistant, `app_old.py` for earlier iteration). Invoked with `uv run`.
- `frontend/`: Next.js UI (`app/` routes, `components/`, `hooks/`, `lib/`, `public/`, `styles/`, `app-config.ts` for branding/feature flags). Uses pnpm and Turbopack in dev.
- Root configs: `pyproject.toml` (Python deps), `README.md` (quickstart), `.env` for secrets. Other folders contain example/demo artifacts; keep new work in `backend/` and `frontend/`.

## Environment & Setup
- Install Python ≥3.11 plus `uv`, Node.js ≥20 plus `pnpm`.
- Copy `.env.example` (if present) to `.env` and set `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL`, `XAI_API_KEY`. Never commit secrets.
- Frontend uses `.env.local` in `frontend/` for overrides when needed.

## Build, Test, and Development Commands
- Backend: `uv run backend/app.py download-files` (initial model assets), `uv run backend/app.py dev` (dev loop), `uv run backend/app.py start` (serve). Use `console` for CLI-only runs if defined.
- Frontend (from `frontend/`): `pnpm dev` (local dev server), `pnpm build` (production bundle), `pnpm start` (serve build), `pnpm lint` (ESLint), `pnpm format` / `pnpm format:check` (Prettier).

## Coding Style & Naming
- Python: Prefer PEP 8, type hints, concise functions; keep LiveKit session logic separated from utility code. Follow existing pattern of dataclasses and Pydantic models for structured data.
- TypeScript/React: ESLint + Prettier + Tailwind plugin; 2-space indent, single quotes per formatter defaults. Components live in `components/` and `app/`; name files in kebab-case, React components in PascalCase.
- Configuration: Keep user-facing text and branding in `app-config.ts`; avoid hard-coding keys or URLs.

## Testing Guidelines
- No formal test suite yet; before opening a PR, run `pnpm lint` and exercise the voice flow locally (`pnpm dev` + `uv run backend/app.py dev`). Add targeted unit/interaction tests when touching complex hooks or backend session logic.
- Keep fixtures minimal; prefer explicit sample payloads over broad mocks.

## Commit & Pull Request Guidelines
- Commits in this repo use short imperative subjects (e.g., “Convert frontend from submodule”). Keep diffs focused and include rationale when changing agent behavior or config.
- PRs should describe scope, testing performed, and any environment updates required (`.env` keys, LiveKit project settings). Add screenshots or terminal output for UX-visible changes. Link issues if applicable.

## Security & Operational Tips
- Do not log credentials. Use `.env` for secrets and confirm `.gitignore` coverage before adding new env files.
- Validate LiveKit and XAI keys in a dev project before production changes. Rotate keys if accidental exposure occurs.
