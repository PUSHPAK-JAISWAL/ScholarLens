# ScholarLens — Project Plan

> **What this is.** A productionized version of the *Student GrantMatch* capstone (Agentic RAG with Pydantic AI). Same core idea — take a student's basic info and tell them which scholarships/grants they qualify for, with the exact rule cited — rebuilt as a real SaaS product with a Next.js front end, a FastAPI back end, and a full observability stack.
>
> **Reference:** GrantMatch capstone (G4, GardenStateAI) — Agentic RAG, Pydantic AI ReAct loop, ChromaDB + OpenAI embeddings, retrieval + web-search tools, structured cited eligibility output, labeled-profile evaluation.
>
> **Stack decisions for this version:** Next.js (App Router) · FastAPI · Vercel + Render/Railway · Grafana Cloud (traces + metrics + logs).

---

## 1. Problem — What are we solving?

Students often don't know which scholarships or grants they actually qualify for. Eligibility rules are buried in long PDFs and program pages, and keyword search either misses real matches or confidently returns wrong ones.

**ScholarLens** takes a student's basic information (income, state, GPA, major, and so on) and determines which programs they may qualify for — while showing the **exact rule** behind each result, so the answer is auditable rather than a black box.

The original capstone solves this with an **Agentic RAG** approach: documents are chunked and embedded into ChromaDB, and a runtime Pydantic AI agent decides — per query — whether to retrieve from the document store or run a web search before producing a structured, cited eligibility result.

This version keeps that core intact and productionizes everything around it: a real front end, a REST API, reliability hardening, and production-grade observability and metrics.

### What stays the same (the graded core)
- Agentic RAG with Pydantic AI and its ReAct-style Thought → Action → Observation loop
- ChromaDB vector store, OpenAI embeddings (`text-embedding-3-small`)
- A retriever tool and a web-search tool (Tavily or SerpAPI), with the agent choosing between them
- Structured Pydantic output: eligibility status + supporting clause + source
- The labeled-profile evaluation suite

### What's new (the productionization)
- Next.js (App Router) SaaS front end with a real landing page, replacing the Streamlit/demo UI
- A FastAPI REST API in front of the agent
- Reliability and security hardening (timeouts, bounded retries, rate limiting, server-side keys)
- End-to-end observability: OpenTelemetry traces, Prometheus metrics, structured logs, Grafana dashboards
- A protected internal operations view for metrics and evaluation results

---

## 2. Users — Who is this for?

### Primary: Students
- Check scholarship/grant eligibility from plain-language input
- Understand *why* they qualify or don't
- See the exact rule (clause) supporting the result
- Identify **partial** matches, not just yes/no
- Understand what information is missing or uncertain

Students see eligibility only — never "odds of winning."

### Secondary: Maintainers / evaluators (that's you, on your resume)
- Monitor application health and AI behavior in production
- Review evaluation runs and quality metrics over time
- Diagnose failures across retrieval, tools, model, and ingestion

---

## 3. Features — What does v1 need?

### Eligibility assistant (student-facing)
- Natural-language student input, with a guided form for the common fields
- Result: **`eligible`**, **`not eligible`**, or **`partial`**
- The exact supporting clause, quoted
- A source citation (program + document + link where available)
- A plain-language explanation
- Explicit handling of missing information and uncertainty
- Neutral, cautious tone on borderline cases; eligibility reporting only

### Agentic RAG (the engine)
- Document ingestion → chunking → OpenAI embeddings → ChromaDB
- A retriever tool wrapping the vector store
- A web-search tool (Tavily or SerpAPI) for rules not in the local corpus
- Agent chooses between retrieval and web search per query
- Structured Pydantic output (typed eligibility + cited clause) — no fragile free-text parsing

### Agent transparency (SaaS trust signal)
- Show live activity as the agent works: *Searching program rules → Checking official sources → Validating eligibility → Preparing cited answer*
- Never expose hidden chain-of-thought — surface the *steps*, not the model's internal reasoning

### Evaluation (repeatable, not one-off)
Retain the labeled-profile evaluation and make it a one-command run reporting:
- Eligibility accuracy · citation accuracy · hallucination rate
- Tool-call count · response latency
- Repeated-query consistency
- Qualitative citation review · borderline/edge-case review

**Targets (from the reference):** >80% eligibility accuracy, >70% citation accuracy, <10% hallucination rate.

### Observability (the productionization headline)
Production visibility into: API requests, latency, and errors; agent duration; LLM calls and token usage (where available); retriever/web-search calls and latency; tool-call counts; ingestion health; and evaluation metrics over time.

---

## 4. Data — What are we storing?

### Knowledge data (the corpus)
Source documents · document metadata · chunks · embeddings · program/source identifiers. **ChromaDB** is the initial vector store, with persistent storage (not an ephemeral container filesystem).

### Evaluation data
Labeled student profiles · expected results and citations · evaluation runs · aggregate metrics. Kept controlled and **separate from public traffic**.

### Runtime data
**No student accounts or persistent profiles in v1.** Requests are processed without permanently storing student information. This is a deliberate privacy stance, not a missing feature.

### Telemetry data
Traces, metrics, and logs live in the observability backend (Grafana Cloud), **separate from application data**, and are scrubbed of full student prompts/profiles and provider payloads by default.

---

## 5. Tech — What stack are we using?

### Front end
- **Next.js (App Router)** + **TypeScript**
- **Tailwind CSS** + **shadcn/ui** for the component system
- **TanStack Query** for API data fetching, retries, and caching
- A lightweight charting library (Recharts) for the internal metrics view
- Deployed on **Vercel**

*Why Next.js over the reference's React + Vite:* the App Router gives a server-rendered marketing/landing page (better first-load and SEO for a portfolio piece), file-based routing for the `/`, `/check`, and `/ops` areas, and a one-click Vercel deploy — all without changing anything about the Python engine.

### Back end (Python — kept close to the reference on purpose)
- **Python** + **FastAPI**
- **Pydantic** / **Pydantic Settings** for validation and typed configuration
- **Pydantic AI** for the agent loop and structured output
- **OpenAI API** for reasoning and embeddings
- **ChromaDB** vector store
- **Tavily** or **SerpAPI** for web search
- **httpx** for external HTTP with explicit timeouts
- Deployed on **Render** or **Railway** as a persistent service

*Keeping the Python stack from the capstone is intentional* — you're learning Python, and the graded core (Pydantic AI + ChromaDB + tools) is exactly what should stay stable while the production scaffolding grows around it.

### API (REST between Next.js and FastAPI)
Core areas: **Eligibility** · **Health/readiness** · **Evaluation** · **Ingestion status**. Typed request/response models shared in spirit between Pydantic (server) and TypeScript (client).

### Observability
- **Structured logging** (JSON) with request/correlation IDs
- **OpenTelemetry** traces spanning the FastAPI request → agent → tools → LLM
- **Prometheus-compatible metrics** scraped or pushed to **Grafana Cloud**
- **Grafana dashboards** for latency/errors/tool usage + evaluation trends

The capstone already traces tool calls and latency for evaluation; this version promotes that into request-level, production observability.

### Deployment
Front end and back end deploy independently (Vercel + Render/Railway). ChromaDB uses persistent storage. Logs, traces, and metrics centralize in Grafana Cloud so production debugging never depends on local files. Full local parity via Docker Compose for development.

---

## 6. UI/UX — How should it look and feel?

ScholarLens should feel like a **trustworthy modern SaaS eligibility tool**, not a generic chatbot. Clean, confident, lots of whitespace, one clear primary action.

### Landing page (`/`)
A real SaaS landing page: a focused hero ("Find scholarships you actually qualify for — with the exact rule that says so"), a short "how it works" (input → agent checks rules → cited result), a trust section that leans on the *cited-clause* differentiator, and a single primary CTA into the eligibility check. Server-rendered, responsive, light/dark aware.

### Student flow (`/check`)
1. Enter student information (guided fields + free-text)
2. Submit eligibility query
3. Watch agent activity (the transparency steps above)
4. See eligibility status as a clear, color-coded verdict (eligible / partial / not eligible)
5. Read the plain-language explanation
6. Review the exact supporting clause
7. Open the source
8. Review any uncertainty or missing information

Loading, empty, timeout, and failure states are all designed — not afterthoughts — because a tool that says "I'm not sure, here's why" *builds* trust.

### Internal operations (`/ops`, protected)
A separate, protected view — kept visually and functionally distinct from the student experience — showing request volume, latency, error rate, tool usage, evaluation scores, recent evaluation runs, and ingestion health. This is the page that makes the "productionized" claim real to a reviewer.

---

## 7. Reliability, Security & Privacy

- Validate all API inputs with Pydantic
- Keep API keys server-side only — never in the browser bundle
- Explicit timeouts on every external service (OpenAI, web search, ChromaDB)
- Graceful degradation: LLM, search, and vector-store failures produce controlled UI/API states, never a crash or a hang
- Health/readiness endpoints suitable for the host
- Request/correlation IDs threaded through logs and traces
- Do not log full student prompts/profiles or provider payloads by default
- Restrict CORS in production to the known front-end origin
- Rate-limit public eligibility requests
- Protect evaluation and ingestion endpoints (not public)
- HTTPS everywhere (handled by Vercel/Render)
- Review and pin dependencies

Answers stay neutral and appropriately cautious, especially on borderline cases.

---

## 8. MVP Scope

The productionized MVP is complete when:

1. Next.js (App Router) replaces the demo front end, with a real landing page.
2. FastAPI exposes the core REST API.
3. The existing Pydantic AI agent remains functional and unchanged in behavior.
4. ChromaDB retrieval and web search both work.
5. Answers retain supporting clauses and sources.
6. The labeled evaluation set runs consistently with one command.
7. API, agent, retrieval, search, and LLM activity is observable end-to-end.
8. Metrics cover latency, errors, tool usage, and evaluation quality.
9. Health/readiness checks work in deployment.
10. External failures produce controlled UI/API states.
11. Front end and back end are independently deployed and reachable over HTTPS.
12. Sensitive student information is not unnecessarily persisted or logged.

### Later (explicitly out of scope for v1)
User accounts · saved student profiles · scholarship tracking · multi-tenant admin · hybrid retrieval · reranking · query rewriting · larger-scale evaluation infrastructure · fine-tuned models · native mobile apps.

Keeping these out is a scoping decision, not an oversight — v1 proves the productionization end to end without the maintenance weight of accounts and personalization.
