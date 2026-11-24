# Dihari (دیہاڑی) — PLAN

Voice-first Urdu job marketplace for daily-wage labour. Pakistan is market #1; every country-specific fact is **configuration**, not code.

## Scope decisions for this build
- External AI providers (ASR / TTS / LLM / SMS / web-push) are **not wired yet**. Each has an interface, a config-driven registry, a fallback chain and an offline **mock**. Real providers drop into `backend/app/ai/providers/` (see `docs/PROVIDERS.md`) with no other code change.
- Built locally first; no remote repo yet.

## Architecture
```
 PWA (React+Vite+Tailwind, RTL, Urdu)           Reviewer page (static HTML, /admin)
        │  REST/JSON                                     │
        ▼                                                ▼
 FastAPI app ── auth ─ profiles ─ jobs(state machine) ─ offers ─ agreements
    │             wage_floor (pure code) ─ geo ─ payments/check-ins ─ cases
    │             reputation ─ notifications ─ abuse ─ audit
    │             voice router ── ai/ (ASR · TTS · LLM interfaces → registry → fallback chain → mock)
    │                               extraction → code validation → readback → verifier (different model family)
    ▼
 SQLAlchemy ── Postgres+PostGIS (prod, ST_DWithin)  /  SQLite + haversine (tests, offline)
 FastMCP server: post_job · check_wage_floor · find_workers · file_case
```
Config tree: `config/countries/<cc>.json` (currency, phone, regions, trades, places, providers, holidays) · `config/wage_rules/<cc>.json` (versioned, `verified` flag) · `locales/<lang>.json` (all strings + lexicon, shared by backend and frontend).

## Folder structure
```
config/ locales/ docs/
backend/app/{settings,db,models,country_config,i18n,security,deps,main}.py
backend/app/modules/{auth,profiles,wage_floor,jobs,geo,offers,agreements,payments,cases,reputation,notifications,abuse,audit,voice}.py
backend/app/ai/{base,registry,mock,chain,extraction,validation,readback,verifier}.py  + providers/
backend/app/mcp_server.py   backend/app/admin_ui/index.html
backend/tests/  backend/sim/  backend/adversarial/  backend/scripts/seed.py
frontend/  (Vite PWA)      docker-compose.yml  .env.example  README.md  DEMO.md  DECISIONS.md
```

## Milestones (commit after each, tests green)
1. **M1** Skeleton: settings, DB, country config, i18n, auth (phone+OTP), profiles, audit.
2. **M2** wage_floor, job state machine, offers (upward-only).
3. **M3** geo matching + fuzz, agreements (immutable), payments check-in, cases + reviewer, reputation.
4. **M4** AI layer: interfaces, registry, chain, mocks, extraction + grounding + validation, readback, verifier, voice endpoints.
5. **M5** notifications, abuse controls, MCP server, reviewer page.
6. **M6** Frontend PWA.
7. **M7** Seed, simulation, adversarial eval, docker-compose, README, DEMO.
