# ScholarLens — Backend (FastAPI)

Python API in front of the Agentic RAG eligibility engine.

## Setup

```bash
cd backend
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -e ".[dev]"   # or: pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Health: http://localhost:8000/health
- Interactive docs: http://localhost:8000/docs
