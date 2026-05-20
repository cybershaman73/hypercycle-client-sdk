# Changelog

All notable changes to the HyperCycle Client SDK are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [0.2.0-beta] — 2026-05-13

### Added
- `ping()` method on all four clients — quick connectivity check before discovery
- `NodeInfo` return type from `info()` — structured access to node identity, hardware, network, and aims list without manual JSON parsing
- `EndpointCost` type — structured parsing of `uri_cost` block from `/info` response
- `running_only` / `runningOnly` parameter on `discoverAll()` — filter by status at the call site
- `SDK_VERSION` constant exposed on all client classes
- Environment variable support — all clients now read `HYPERCYCLE_NODE_URL` if no URL is passed directly
- Kotlin: all methods are now `suspend` functions dispatched on `Dispatchers.IO` — safe to call from Android main thread via `viewModelScope` or `lifecycleScope`
- Expanded inline documentation across all four languages covering Node Manager architecture, `/info` parsing, and cost model
- `docs/info-endpoint-reference.md` (also included as README appendix)
- `CHANGELOG.md`

### Changed
- Hardcoded node IP removed from all clients and examples — replaced with `HYPERCYCLE_NODE_URL` environment variable
- Directory structure now matches README: `python/`, `typescript/`, `swift/`, `kotlin/`, `examples/{python,typescript,swift,kotlin}/`
- Python example `sys.path` import fixed to use correct relative path
- `discoverAll()` now defaults to `running_only=True` — non-running AIMs are excluded by default (pass `False` to include all)
- `info()` now returns a typed `NodeInfo` object instead of raw `dict` / `JSONObject`

### Fixed
- Kotlin `NetworkOnMainThreadException` risk — all network calls are now wrapped in `withContext(Dispatchers.IO)`
- Python example path assumptions — example now works correctly from `examples/python/` with the new directory layout

---

## [0.1.0-beta] — 2026-04-15

### Added
- Initial beta release
- Python client (`hypercycle_client.py`) — stdlib only, no dependencies
- TypeScript client (`hypercycle-client.ts`) — native fetch, no dependencies
- Swift client (`HyperCycleClient.swift`) — URLSession, iOS 15+ / macOS 12+
- Kotlin client (`HyperCycleClient.kt`) — OkHttp 4.12
- Result wrapper pattern across all four languages (never-throw, check `.ok`)
- `info()`, `discover()`, `discoverAll()`, `health()`, `estimate()`, `execute()` on all clients
- YAMNet acoustic classifier reference example in all four languages
- `README.md` with quickstart and API reference

---

## [0.2.1-beta] — 2026-05-13

### Added
- `WaveformUtils` class in Python, TypeScript, Swift, and Kotlin examples:
  - `generateTestWaveform()` — synthetic 440 Hz tone for testing
  - `normalizeInt16()` / `normalizeFloat32()` / `normalizeInt32()` — PCM normalization helpers
  - `downmixStereoToMono()` — stereo interleaved to mono
  - `validate()` / `validateWaveform()` — pre-flight check before sending; raises descriptive error if payload would cause 422
  - `toJsonArray()` (Kotlin) — ensures correct Float→Double conversion for JSONArray
- `SoundEvent` and `YAMNetResponse` typed structs/data classes in Swift and Kotlin examples — no more raw dict parsing in app code
- `HyperCycleYAMNetService` wrapper class in Swift and Kotlin — encapsulates the discover → health → infer flow as a single `infer()` call
- `AIM_PROTOCOL_VERSION = "0.1"` constant in all examples — clarifies this is the AIM-level protocol field, separate from the SDK version
- 422 vs 500 error handling in all examples with distinct messaging and retry guidance
- README: `masked_waveform` format specification appendix (exact requirements, normalization, serialization notes, error table)
- README: YAMNet response field reference appendix (all fields, sample taxonomy labels, `categories.json` reference)

### Fixed
- `sdk_version` in request body was incorrectly set to the SDK version string; corrected to `"0.1"` (AIM protocol version)
- `peak_confidence` field added to response parsing in all examples (was missing)
- `intensity_db` field added to response parsing in all examples (was missing)
- Swift serialization note: `Float → Double` cast documented and enforced in example
- Kotlin serialization note: `.toDouble()` cast documented and enforced in `WaveformUtils.toJsonArray()`

---

## [0.3.0-beta] — 2026-05-13

### Added
- New examples directory structure organized by use case category:
  `audio/`, `speech/`, `text/`, `vision/`
- **ollama-aim** examples (all 4 languages) — `text/ollama-aim/`
  - `waitForReady()` polling loop — handles the ~4 min model download window after container enters "running" state
  - Correct endpoint: `POST /request` (not `/chat` or `/generate`)
  - `OllamaAIMService` convenience wrapper in Swift and Kotlin
- **tortoise-tts** examples (all 4 languages) — `speech/tortoise-tts/`
  - `waitForReady()` polling loop — same ~4 min warmup applies
  - `GET /list-voices` endpoint for dynamic voice discovery
  - `POST /speak` with base64 WAV response decoding
  - Platform-specific audio playback guidance (AVAudioPlayer / MediaPlayer / ExoPlayer)
  - `TortoiseTTSService` convenience wrapper in Swift and Kotlin
  - 100-character input limit enforced client-side before network call
- **cog-videox** skeleton — `vision/cog-videox/` — marked as "AIM in active development", not yet on CBNO nodes
- `examples/README.md` — use case overview, warmup note, quick start

### Changed
- YAMNet examples moved from flat `examples/{language}/` to `examples/audio/yamnet-classifier/{language}/`
- All examples renamed from `yamnet_example.*` to `example.*` — consistent naming across all AIMs
- Relative import paths updated to match new directory depth

### Notes (from CBNO operator guide)
- `ollama-aim` and `tortoise-tts` both require ~4 min warmup after container status = "running". Health checks pass before the model is ready — always use `waitForReady()` before submitting inference.
- `ollama-aim` default model is `gemma2:2b` (CPU-safe). Larger models (`mistral:7b`, `llama3:8b`) require GPU and are configured at deploy time via `OLLAMA_MODEL` env var.
- `tortoise-tts` requires NVIDIA GPU with 8+ GB free VRAM.
- USDC costs are operator-configurable and can be set to zero for beta/hackathon use.


---

## [0.3.1-beta] — 2026-05-19

### Changed

**`EndpointCost` now includes the endpoint name.**
Previously: `EndpointCost(currency, fixed, estimated_cost, min, max)` — the URI
key from `uri_cost` (e.g. `/speak`, `/infer`) was parsed and then discarded.
Now: `EndpointCost(endpoint, currency, fixed, ...)` — the endpoint name is
preserved and stored, making it possible to match costs back to specific endpoints.

**`AIMInfo` now includes an `endpoints` list.**
Previously: `AIMInfo` had a `costs` list but no record of which endpoints the AIM
exposed — callers had to know endpoint names out-of-band or read the docs.
Now: `AIMInfo.endpoints` is a `List[str]` of all endpoint URIs declared in the
`uri_cost` block of `/info` (e.g. `["/speak", "/list-voices"]`). Empty if the AIM
uses `manifest.json` costs instead, in which case fetch `/aim/<slot>/manifest.json`.

**`health()` now distinguishes 404 from other failures.**
Previously: any failed health check returned a generic failure result — callers
could not tell whether the AIM was down or simply had no `/health` endpoint.
Now: a 404 from `/health` returns `status=404` with an explicit message:
`"AIM at slot N has no /health endpoint — probe the active endpoint directly."`
Callers can branch on `result.status == 404` to fall through gracefully.

**Tortoise TTS example: health-first with active-endpoint fallback.**
Previously: `waitForReady()` polled `/health` unconditionally. Because
`tortoise-tts` has no `/health` endpoint, every poll returned a connection error,
the loop never exited early, and the full 5-minute timeout elapsed before failing.
Now: the example attempts `/health` first. On 404 it immediately falls through to
`speak_with_retry()`, which probes `/speak` directly with 20-second backoff. A
successful `/speak` response is the definitive signal the model is loaded. 400
responses (bad voice name, text too long) exit immediately without retrying.

**Tortoise TTS example: endpoint reporting from /info.**
Previously: discovery printed slot number only.
Now: `report_aim()` prints all endpoints declared in `uri_cost`, their per-currency
costs (or "free" if fixed=0), and GPU label requirements — giving the developer
a full picture of the AIM before any inference call is made.

### Notes
- The absence of a `/health` endpoint on `tortoise-tts` is a known AIM-side gap.
  The correct fix is for the AIM to expose `GET /health` returning
  `{"model_ready": false}` during model load and `{"model_ready": true}` once
  ready. Until that is shipped, the active-endpoint fallback pattern handles it.
- TypeScript, Swift, and Kotlin examples will be updated to match in the next pass.
