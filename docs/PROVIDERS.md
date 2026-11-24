# Wiring real providers (deliberately not done yet)

Nothing external is connected. ASR / TTS / LLM / SMS / web-push each have an interface, a registry and a mock.

## Steps for each provider
1. **Check the provider's CURRENT docs first** (languages, pricing, request format). Do not rely on memory. For ASR confirm Urdu, Punjabi, Sindhi and Pashto support and which model/version; for TTS confirm a natural Urdu voice.
2. Create `backend/app/ai/providers/<name>.py`. Implement the interface from `app/ai/base.py`:
   - `ASR.transcribe(audio: bytes, mime: str, lang: str) -> Transcript`
   - `TTS.synthesize(text: str, lang: str) -> Audio`
   - `LLM.complete_json(*, task, system, prompt, schema) -> dict` (must return JSON matching `schema`; set `family`)
   - set `name`, `family`, `is_mock = False`
3. At import time call `registry.register("asr"|"tts"|"llm", "<name>", factory)`. Modules in `providers/` are auto-imported.
4. Put keys in `.env` (names suggested in `.env.example`) and select with `ASR_PROVIDERS=<name>,mock` etc. Chains try providers in order and log provider / latency / failure to the `ai_call_log` table.
5. **Verifier rule:** `LLM_VERIFY_PROVIDERS` must be a *different model family* than `LLM_EXTRACT_PROVIDERS`; the app refuses to start otherwise.
6. SMS: `modules/notifications.register_sms(name, factory)`; web push: `register_push(name, factory)` and set `NOTIFY_PROVIDERS`.
7. Re-run `python -m adversarial.run --llm <name>` for real extraction numbers.

If every provider in a chain fails the API answers `503 {degraded: true}` and the PWA drops to tap-only input / browser `speechSynthesis`.
