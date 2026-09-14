# ScholarLens — Build Plan

> **Goal.** Productionize the *GrantMatch* capstone without replacing its core Agentic RAG approach. The existing architecture is offline RAG ingestion plus an online Pydantic AI agent that chooses retrieval or web search before returning a structured, cited answer. That engine stays; everything around it gets built to production quality.
>
> **Stack:** Next.js (App Router) + Tailwind + shadcn/ui on **Vercel** · FastAPI + Pydantic AI + ChromaDB on **Render/Railway** · OpenTelemetry + Prometheus + logs into **Grafana Cloud**.
>
> **Working principle:** ship the thin end-to-end path early (Next.js → FastAPI → Agent → Retrieval/Web Search → cited answer), *then* harden. Don't polish a path that doesn't run yet.

---

## Phase 0 — Foundation

- [ ] **0.1 Repo + structure** — Keep a clean monorepo layout: `/backend` (FastAPI app), `/frontend` (Next.js app), `/infra` (Docker Compose, env templates), `/docs` (these plans). One README that explains the "what" and "why" in 60 seconds — this is the first thing a resume reviewer opens.
- [ ] **0.2 Backend reorganization** — Restructure the Python project around clear modules: `api`, `agent`, `tools`, `retrieval`, `ingestion`, `evaluation`, `config`. Introduce **Pydantic Settings** for typed config and clean dev/prod separation. **Do not change agent behavior** in this step — this is pure reorganization so everything after it has a home.
- [ ] **0.3 Local dev via Docker Compose** — One `docker compose up` brings up FastAPI, ChromaDB (persistent volume), and the Grafana Cloud OTel collector/agent. Frontend runs with `next dev` against it. Development parity means production surprises are rare.

## Phase 1 — Back end + engine (keep the graded core intact)

- [ ] **1.1 FastAPI REST API** — Health/readiness endpoints, CORS config, structured error responses, request validation, and the core **eligibility endpoint** that invokes the existing Pydantic AI agent. Typed request/response models.
- [ ] **1.2 Productionize the Agentic RAG flow** — Preserve Pydantic AI, the structured eligibility output, ChromaDB retrieval, OpenAI embeddings, and the Tavily/SerpAPI web-search tool. Isolate every external call behind a thin client with **explicit timeouts and error handling**. Behavior stays identical; failure modes become controlled.
- [ ] **1.3 Knowledge ingestion pipeline** — Make ingestion reproducible: formalize chunking, embeddings, metadata, ChromaDB persistence, source identifiers, and an ingestion-status record. One command re-ingests from scratch.
- [ ] **1.4 Evaluation pipeline** — Preserve the hand-labeled student-profile evaluation and make it a repeatable one-command run. Report eligibility accuracy, citation accuracy, hallucination rate, tool-call count, latency, consistency, and qualitative failure categories. Persist each run so trends are visible later. **Targets: >80% eligibility, >70% citation, <10% hallucination.**

## Phase 2 — Front end (the SaaS layer)

- [ ] **2.1 Next.js app shell** — App Router + TypeScript + Tailwind + shadcn/ui. Set up routing for `/` (landing), `/check` (student flow), `/ops` (protected internal view). Theme tokens (light/dark), typography, and a small design system before building screens.
- [ ] **2.2 SaaS landing page (`/`)** — Server-rendered hero, "how it works," a trust section built around the *cited-clause* differentiator, and one clear CTA into the eligibility check. This is the portfolio centerpiece — invest in it.
- [ ] **2.3 Student eligibility flow (`/check`)** — Guided input (fields + free text), example queries, the eligibility verdict (color-coded eligible/partial/not-eligible), plain-language explanation, cited clause, source link, and explicit uncertainty/missing-info states. Design the loading, empty, timeout, and error states too.
- [ ] **2.4 Agent transparency UI** — Surface live activity steps (*searching program rules → checking official sources → validating eligibility → preparing cited answer*). Show the steps, never hidden chain-of-thought.

## Phase 3 — Integration

- [ ] **3.1 Frontend ↔ API integration** — Connect Next.js to FastAPI with typed request/response models and **TanStack Query**. Handle loading, retries, timeouts, failures, and empty states cleanly. Server-side keys only — the browser never sees a provider key.

## Phase 4 — Observability (the productionization headline)

- [ ] **4.1 Structured logging + correlation IDs** — JSON logs with a request/correlation ID threaded across the whole request lifecycle and consistent field names.
- [ ] **4.2 OpenTelemetry instrumentation** — Auto-instrument the FastAPI request lifecycle, then add manual spans across the agent, retriever, web-search tool, embedding/retrieval ops, and LLM calls. Capture duration, success/failure, tool sequence, provider/model metadata, and token usage where available — **without logging sensitive student data**. Export traces to Grafana Cloud Tempo.
- [ ] **4.3 Prometheus metrics** — Expose request count, latency, error rate, agent duration, LLM calls, tool calls, retrieval latency, web-search latency, token usage (where available), ingestion health, and latest evaluation results. Push/scrape into Grafana Cloud.
- [ ] **4.4 Grafana dashboards** — One "service health" dashboard (latency/errors/throughput) and one "AI quality" dashboard (tool usage, evaluation trends, hallucination rate over time). These two dashboards are what make the observability claim tangible.
- [ ] **4.5 Operations view (`/ops`, protected)** — A protected internal UI for high-level metrics, evaluation runs, tool usage, latency/error trends, and ingestion health. Kept separate from the student-facing experience. Can embed Grafana panels or read a metrics summary endpoint — either is fine for v1.

## Phase 5 — Hardening

- [ ] **5.1 Reliability + security** — Rate limiting on public eligibility requests, production CORS locked to the front-end origin, timeout policies, bounded retries where safe, protected ingestion/evaluation endpoints, secure server-side key handling, a dependency review/pin, and log-scrubbing safeguards so student data and provider payloads never enter telemetry.
- [ ] **5.2 Testing** — Unit tests (validation, retrieval/tool behavior, evaluation calculations, metrics), API tests (validation + failure handling), an integration test for the agent/tool pipeline, and one end-to-end test for the main eligibility journey. Aim for meaningful coverage of the paths that matter, not a coverage number.

## Phase 6 — Deploy + polish

- [ ] **6.1 Deploy (early, then iterate)** — Deploy the thin end-to-end path as soon as `Next.js → FastAPI → Agent → answer` works locally, so production-specific issues surface early. Frontend on **Vercel**; backend on **Render/Railway** as a persistent service with a persistent ChromaDB volume; env vars for all OpenAI/web-search/observability credentials; HTTPS; health checks; Grafana Cloud receiving logs/traces/metrics.
- [ ] **6.2 Production polish** — Final UX/accessibility pass, better answer/source presentation, verified mobile responsiveness, tuned dashboards/alerts, a short operations note in the README, and a final rerun of the evaluation suite against the deployed version. Capture one or two dashboard screenshots for the resume/README.

---

## Deployment notes

Decisions settled for this version:

- **Frontend** — Next.js on Vercel (server-rendered landing page, static/edge for the rest).
- **Backend** — FastAPI as a persistent service on Render or Railway (not a serverless function — the agent and ChromaDB want a warm, stateful process).
- **ChromaDB** — persistent storage (a mounted volume). Never rely on an ephemeral container filesystem.
- **Configuration** — OpenAI, web-search, and observability credentials live in environment variables / platform secrets only.
- **HTTPS** — handled by Vercel and Render/Railway out of the box.
- **Health checks** — liveness/readiness endpoints wired to the platform's health probes.
- **Observability** — Grafana Cloud centralizes logs, traces, and metrics; production debugging never depends on local files.
- **External APIs** — explicit timeouts and bounded retries for OpenAI and web-search calls.
- **Sensitive data** — never record full student prompts/profiles or provider payloads in normal telemetry.
- **Evaluation** — keep the labeled dataset controlled and separate from public traffic.

---

## Later (not v1)

Only if ScholarLens grows beyond the productionized capstone:

- User accounts and saved student profiles
- Personalized scholarship tracking
- Multi-tenant administration
- Hybrid retrieval · reranking · query rewriting
- Larger-scale evaluation infrastructure
- Fine-tuned models
- Native mobile applications

---

## Suggested order (fastest path to a demo-able, resume-ready build)

**0.1–0.3 → 1.1–1.2 → 2.1–2.3 → 3.1 → deploy the thin path (6.1) → 1.3–1.4 → 2.4 → 4.1–4.5 → 5.1–5.2 → 6.2.**

The point of front-loading the thin deployed path: you always have a working, shareable link, and every later phase visibly improves something real rather than building toward a big-bang launch.
