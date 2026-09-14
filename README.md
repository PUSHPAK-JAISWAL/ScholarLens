# ScholarLens

Scholarship & grant eligibility assistant — Agentic RAG (Pydantic AI) with a Next.js front end and a FastAPI back end.

## Repo layout

```
frontend/   Next.js (App Router, TypeScript, Tailwind) — the SaaS client
backend/    FastAPI + Pydantic AI — the API and Agentic RAG engine
infra/      Deployment / observability config (Docker Compose, env templates)
```

## Quickstart

### Frontend
```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

### Backend
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |   macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload   # http://localhost:8000  (docs at /docs)
```

See `project-requirement-docs/` for the project plan, build plan, and design reference.
