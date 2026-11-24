# DECISIONS

Reasonable choices made without asking. Newest at bottom.

1. **Vite + React + TS + Tailwind PWA, not Next.js.** Smaller bundle for slow 3G, no SSR needed, simple static hosting + service worker.
2. **Sync SQLAlchemy 2 + FastAPI.** Simpler and fully adequate; DB access isn't the bottleneck.
3. **Postgres+PostGIS in prod, SQLite in tests.** Geo module picks the backend by dialect: `ST_DWithin` (geography) on Postgres, haversine in Python on SQLite. Same interface, same tests on the haversine path; the PostGIS SQL is compiled-checked in tests but needs a PostGIS container to run end to end (docker-compose).
4. **Money = integer whole units** of the country's currency (`minor_units` from config is available for countries that need it).
5. **Provider space left empty.** Registry + chain + mocks only. Mock ASR treats audio bytes as UTF-8 text (test convenience). Mock TTS returns silence and reports `is_mock`, so the frontend uses browser `speechSynthesis` instead.
6. **Wage rules are placeholders.** All regions ship `min_daily_wage: 1000`, `verified: false`, `placeholder: true`, with a TODO to fill from the official provincial notification. The app shows a warning while a rule is unverified. The number is *not* a legal figure.
7. **Job states** = spec states + `cancelled` (terminal, from open/offers/assigned). `offers` is entered on first offer; `assigned` once the hirer picks ≥1 worker (headcount may be >1; further picks allowed while assigned).
8. **Worker-level state lives in `Assignment`**, immutable terms in `Agreement` (ORM blocks updates). Job `payment_confirmed` when every confirmed worker reports paid; `disputed` as soon as any reports unpaid.
9. **Required extraction fields** are: task, headcount, location, start_at, daily_rate, hours_per_day, payment_day, deductions, advance, transport. Unknown ≠ none: "no deductions" must be said or tapped. `days` defaults to 1 but is always read back.
10. **Grounding check:** numeric values from the LLM must literally appear in the transcript (digits or number words from the locale lexicon), otherwise they are nulled and asked again. Code never trusts the LLM's numbers.
11. **Verifier can only tighten.** Code checks (floor, hours, required, grounding) are authoritative. A verifier mismatch forces explicit human confirmation; it can never turn a code failure into a pass. Verifier and extractor must be different `family` values (startup check).
12. **Read-back is template-based** (deterministic, locale file), then verified by the second model.
13. **Reputation inputs are self-reported.** Hirer on-time rate = worker "paid" reports / (paid+unpaid reports). Worker completion = completed / (completed+no_show+cancelled assignments). Hirers see workers as first name only; cases shown to hirers never contain worker name/phone.
14. **Reviewer actions** are proposed by deterministic code rules; named reviewers (token auth) approve/reject. No AI decides anything about disputes.
15. **Rate limiting** is in-process sliding window behind an interface (swap for Redis when scaling past one worker).
16. **Dev OTP** is returned in the API response only when `SMS_PROVIDER=stub` and `DEV_MODE=true`.
17. **Place gazetteer coordinates** in `config/countries/pk.json` are approximate demo values, flagged `approx: true`.
18. **Adversarial baseline** uses the LLM interface; with only a mock configured, the "LLM-only" baseline is a naive stand-in and the report says so. Re-run with a real provider for real numbers.
