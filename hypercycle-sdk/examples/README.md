# HyperCycle SDK — Examples

Examples are organized by use case category. Each category contains one or more AIM examples, each with implementations in all four supported languages.

## Categories

| Category | AIM | Status | Hardware |
|---|---|---|---|
| `audio/` | `yamnet-classifier` | ✅ Live | GPU recommended |
| `speech/` | `tortoise-tts` | ✅ Live | GPU 8+ GB VRAM required |
| `text/` | `ollama-aim` | ✅ Live | CPU ok, GPU recommended |
| `vision/` | `cog-videox` | 🚧 In development | GPU required |

## Structure

```
examples/
├── audio/
│   └── yamnet-classifier/      ← Acoustic event classification
│       ├── python/example.py
│       ├── typescript/example.ts
│       ├── swift/example.swift
│       └── kotlin/example.kt
├── speech/
│   └── tortoise-tts/           ← Text-to-speech synthesis
│       ├── python/example.py
│       ├── typescript/example.ts
│       ├── swift/example.swift
│       └── kotlin/example.kt
├── text/
│   └── ollama-aim/             ← LLM chat / text generation
│       ├── python/example.py
│       ├── typescript/example.ts
│       ├── swift/example.swift
│       └── kotlin/example.kt
└── vision/
    └── cog-videox/             ← Text-to-video (coming soon)
        └── python/example.py   ← Stub with expected API pattern
```

## Quick start

All examples read the node URL from an environment variable:

```bash
export HYPERCYCLE_NODE_URL=http://<your-node-ip>:8000
```

**Recommended starting point:** `text/ollama-aim` — simplest payload (just a text prompt), no special encoding, works on CPU nodes.

## Warmup note (ollama-aim and tortoise-tts)

Both `ollama-aim` and `tortoise-tts` download their models **after** the container enters `running` state. This takes approximately 4 minutes. All examples include a `waitForReady()` polling loop that handles this automatically — do not skip it.

```
Container status = "running"
     ↓ (model download begins)
     ↓ ~4 minutes
model_ready = true  ← safe to submit inference
```
