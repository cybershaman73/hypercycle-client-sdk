# HyperCycle Client SDK

**Version:** 0.2.0-beta  
**Target audience:** Frontend app developers — iOS, Android, and desktop  
**Goal:** Connect your app to any AIM deployed on a HyperCycle node

---

## What is this SDK?

The HyperCycle Client SDK lets your app discover and call AI services (AIMs) running on HyperCycle nodes. It handles the Node Manager API — the single gateway between your app and any AIM container on the network.

**What this SDK does:**
- Discover which AIMs are running on a node (via `/info`)
- Check AIM health before calling it
- Estimate costs before executing (no charge)
- Execute AIM endpoints and parse results

**What this SDK does not do (yet):**
- Build or deploy AIMs (that's the next SDK release)
- Handle wallet signing or payments (see the field guide for session-based auth)

---

## How it works

All AIM interaction flows through the Node Manager (NM) on port 8000. AIM containers are never addressed directly.

```
Your App
  └─► HyperCycleClient(node_url)
        └─► GET  /info                     → discover AIMs, endpoints, costs
        └─► GET  /aim/<slot>/health        → liveness check
        └─► POST /aim/<slot>/<endpoint>    → estimate (cost_only) or execute
              └─► Node Manager routes to AIM container
                    └─► Result returned to your app
```

---

## Quick start (4 steps, any language)

```
1. client = HyperCycleClient(node_url)         // reads env var if not passed
2. aim    = client.discover("image-name")       // find AIM slot via /info
3. health = client.health(aim.slot)             // confirm AIM is ready
4. result = client.execute(aim.slot, endpoint, body)
```

---

## Installation

### Python — no dependencies, stdlib only (Python 3.8+)

```bash
# Copy python/hypercycle_client.py into your project
export HYPERCYCLE_NODE_URL=http://<your-node-ip>:8000
```

```python
import os
from hypercycle_client import HyperCycleClient

client = HyperCycleClient()  # reads HYPERCYCLE_NODE_URL
```

### TypeScript — no dependencies, native fetch (Node 18+, all modern browsers)

```bash
# Copy typescript/hypercycle-client.ts into your project
export HYPERCYCLE_NODE_URL=http://<your-node-ip>:8000
```

```typescript
import { HyperCycleClient } from "./hypercycle-client";

const client = new HyperCycleClient(); // reads HYPERCYCLE_NODE_URL
```

### Swift — no dependencies, URLSession (iOS 15+, macOS 12+)

```swift
// Copy swift/HyperCycleClient.swift into your Xcode project
// Set HYPERCYCLE_NODE_URL in your scheme's environment variables

let client = try HyperCycleClient()  // reads HYPERCYCLE_NODE_URL
```

### Kotlin — requires OkHttp + coroutines (Android)

```gradle
implementation("com.squareup.okhttp3:okhttp:4.12.0")
implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
```

```bash
# Copy kotlin/HyperCycleClient.kt into your Android project
# Set HYPERCYCLE_NODE_URL in your build config or environment
```

```kotlin
val client = HyperCycleClient()  // reads HYPERCYCLE_NODE_URL
```

---

## Configuring the node URL

**Never hardcode a node IP in your app.** Use an environment variable:

```bash
export HYPERCYCLE_NODE_URL=http://<your-node-ip>:8000
```

Or pass it directly (useful for testing or per-user node selection):

```python
client = HyperCycleClient("http://192.168.1.10:8000")
```

---

## API reference

All methods return a result wrapper — never throws or raises. Always check `.ok` before using `.data`.

| Method | Description |
|---|---|
| `ping()` | Returns true if the node is reachable |
| `info()` | Fetch full node info — AIMs, costs, hardware, network |
| `discover(imageName)` | Find a running AIM by Docker image name |
| `discoverAll(runningOnly=true)` | List all AIMs on the node |
| `health(slot)` | Check AIM liveness and model readiness |
| `estimate(slot, endpoint, body)` | Get cost estimate without executing |
| `execute(slot, endpoint, body)` | Execute an AIM endpoint |

### Result type

Every method returns a result wrapper — never raises or throws.

**Python:**
```python
result = client.execute(slot, "infer", body)
if result.ok:
    print(result.data)   # dict
else:
    print(result.error)  # str
    print(result.status) # int or None
```

**TypeScript:**
```typescript
const result = await client.execute(slot, "infer", body);
if (result.ok) {
    console.log(result.data);
} else {
    console.error(result.error, result.status);
}
```

**Swift:**
```swift
let result = await client.execute(slot: slot, endpoint: "infer", body: body)
switch result {
case .success(let data): print(data)
case .failure(let err):  print(err.message, err.statusCode ?? 0)
}
```

**Kotlin:**
```kotlin
// Must be called from a coroutine
val result = client.execute(slot, "infer", body)
when (result) {
    is HyperCycleResult.Success -> println(result.data)
    is HyperCycleResult.Failure -> println(result.error)
}
```

---

## Zero-cost AIMs (open beta / hackathon)

During open beta or hackathon events, AIM operators may set endpoint costs to zero across all currencies. When this is the case:

- `estimate()` returns `costs` with all values at 0
- `execute()` requires no wallet signature or balance
- All four languages handle this identically — no special code needed

The YAMNet example AIM (`yamnet-classifier`) uses zero-cost pricing for the `/infer` endpoint during the current beta period.

---

## Retry strategy

The SDK does not retry automatically. The caller controls retry logic, which lets you match the strategy to your UX:

```python
# Python retry example
for attempt in range(3):
    result = client.execute(slot, "infer", body)
    if result.ok:
        break
    time.sleep(2 ** attempt)
```

```typescript
// TypeScript retry example
for (let attempt = 0; attempt < 3; attempt++) {
    const result = await client.execute(slot, "infer", body);
    if (result.ok) break;
    await new Promise(r => setTimeout(r, 1000 * 2 ** attempt));
}
```

---

## YAMNet reference implementation

The `examples/` directory contains a complete working example for each language using the YAMNet Acoustic Classifier AIM.

```
examples/
├── python/
│   └── yamnet_example.py
├── typescript/
│   └── yamnet-example.ts
├── swift/
│   └── YAMNetExample.swift
└── kotlin/
    └── YAMNetExample.kt
```

Each example demonstrates: `ping → info → discover → health → estimate → execute → parse`

---

## File structure

```
hypercycle-sdk/
├── python/
│   └── hypercycle_client.py
├── typescript/
│   └── hypercycle-client.ts
├── swift/
│   └── HyperCycleClient.swift
├── kotlin/
│   └── HyperCycleClient.kt
├── examples/
│   ├── python/
│   │   └── yamnet_example.py
│   ├── typescript/
│   │   └── yamnet-example.ts
│   ├── swift/
│   │   └── YAMNetExample.swift
│   └── kotlin/
│       └── YAMNetExample.kt
├── docs/
│   └── info-endpoint-reference.md
├── README.md
└── CHANGELOG.md
```

---

## What's next

Once the group adopts this SDK and provides feedback, the next release will introduce the **AIM Builder SDK** — tools to build, package, and deploy your own AIMs to a HyperCycle node.

---

## Appendix: `/info` endpoint reference

The `/info` endpoint is the most important API surface for app developers. It tells you everything running on a node.

```
GET http://<node-address>:8000/info
```

### Top-level response fields

| Field | Type | Description |
|---|---|---|
| `status` | string | Node health: `"alive"` when operational |
| `name` | string | Human-readable node name |
| `address` | string | Node's public address on the network |
| `node_id` | string | Unique node identifier |
| `node_version` | string | Node Manager software version |
| `network` | string | `"mainnet"` or `"testnet"` |
| `platform` | string | Host architecture, e.g. `"x86_64"` |
| `accepting_currencies` | string[] | Currencies accepted for payment, e.g. `["HyPC", "USDC"]` |
| `aim` | object | Contains the `aims` array (see below) |
| `hardware` | object | CPU, memory, disk, GPU info |
| `license` | string | License ID attached to this node |
| `geo_ip` | string | Public IP of the node |

### `aim.aims[]` — the AIM list

Each object in the `aims` array represents one deployed AIM container.

| Field | Type | Description |
|---|---|---|
| `slot` | int | **Key field.** Used in all `/aim/<slot>/...` calls |
| `port` | int | Internal container port (informational; not called directly) |
| `image_name` | string | Docker image name — use this in `discover()` |
| `image_tag` | string | Docker image tag, typically `"latest"` |
| `status` | string | `"running"` = callable; other values = not ready |
| `container_id` | string | Short Docker container ID |
| `labels` | object | Docker labels declared by the AIM (GPU, ENV_VARS, etc.) |
| `uri_cost` | object | Per-endpoint cost declarations (see below) |
| `whitelisted` | bool | Whether this AIM is whitelisted on the node |
| `network_mode` | string | Docker network mode |

### `uri_cost` — cost declarations

`uri_cost` declares the per-endpoint, per-currency pricing for this AIM. The structure is:

```json
"uri_cost": {
  "default": {
    "HyPC": {
      "currency": "HyPC",
      "fixed": 0
    },
    "USDC": {
      "currency": "USDC",
      "fixed": 10000
    }
  }
}
```

When `fixed` is `0`, the endpoint is free (no balance or signature required). During hackathon/beta periods, operators typically set all costs to zero to simplify app development.

### Common `labels` fields

| Label | Purpose |
|---|---|
| `GPUS` | GPU requirement indicator (e.g. `"0+"`) |
| `GPU_MEMORY` | Minimum GPU memory required |
| `ENV_VARS` | Semicolon-separated environment variables |
| `EXTRA_PORT_ENV` | Additional ports the AIM exposes |
| `PERSIST_VOLUME` | `"1"` if the AIM uses persistent storage |
| `description` | Human-readable AIM description |

### Example: full `/info` response (abbreviated)

```json
{
  "status": "alive",
  "name": "Example Node",
  "address": "207.53.252.108:8010",
  "node_version": "0.4.15",
  "node_id": "562928bc42cea196",
  "network": "mainnet",
  "platform": "x86_64",
  "accepting_currencies": ["HyPC", "USDC"],
  "aim": {
    "interface_version": "0.0.1",
    "aims": [
      {
        "image_name": "yamnet-classifier",
        "image_tag": "latest",
        "status": "running",
        "slot": 0,
        "port": 9100,
        "container_id": "6d6b8867bd08",
        "whitelisted": true,
        "labels": {
          "GPUS": "0+",
          "GPU_MEMORY": "0",
          "description": "YAMNet acoustic event classifier"
        },
        "uri_cost": {
          "default": {
            "HyPC": { "currency": "HyPC", "fixed": 0 },
            "USDC": { "currency": "USDC", "fixed": 0 }
          }
        }
      }
    ]
  },
  "hardware": {
    "memory": 135027404800,
    "cpu_count": 72,
    "gpu": {
      "gpu_count": 1,
      "gpus": [{ "name": "Tesla T4", "memory": 15360 }]
    }
  }
}
```

### Using `/info` to discover AIM endpoints and costs

`/info` tells you a slot exists and its cost, but not the full endpoint schema. For the complete endpoint contract (input fields, output fields, detailed per-endpoint costs), fetch the AIM's manifest:

```
GET http://<node-address>:8000/aim/<slot>/manifest.json
```

The manifest includes endpoint URIs, input/output schemas, documentation, and example calls — useful for building a UI that adapts dynamically to whatever AIM is deployed.

### Iterating over all running AIMs

```python
node = client.info().data
for aim in node.aims:
    if aim.status == "running":
        print(f"[slot {aim.slot}] {aim.image_name} — costs: {aim.costs}")
```

```typescript
const node = (await client.info()).data!;
for (const aim of node.aims.filter(a => a.status === "running")) {
    console.log(`[slot ${aim.slot}] ${aim.image_name}`);
}
```

---

## Appendix: `masked_waveform` format specification

The waveform field is the most common source of 422 errors. Get this right before your first call.

### Exact requirements

| Property | Requirement |
|---|---|
| Type | Flat JSON array of decimal numbers |
| Element type | Double (not Float — see serialization notes below) |
| Range | Every value in `[-1.0, +1.0]` inclusive |
| Length | Exactly `sample_rate × duration_sec` samples (±2% tolerance) |
| For 10s demo | Exactly 160,000 elements (16000 × 10) |
| Channels | Mono only — downmix stereo before sending |
| Speech segments | Zeroed (`0.0`) by on-device VAD before sending |
| Encoding | Standard JSON numbers — no base64, no binary, no compression |
| Rounding | Round each sample to 6 decimal places |
| Payload size | ~640 KB – 1.4 MB depending on decimal places per sample |

### Normalization

**From 16-bit integer PCM:**
```
sample_float = sample_int16 / 32768.0
```

**From 32-bit integer PCM:**
```
sample_float = sample_int32 / 2147483648.0
```

**If already float:** clip to range, then round:
```
sample = max(-1.0, min(1.0, sample))
sample = round(sample, 6)
```

### Stereo downmix
```
mono[i] = (left[i] + right[i]) / 2.0
```

### Serialization notes

**Swift:** Always cast `Float → Double` before serializing. `JSONSerialization` does not reliably serialize `Float`:
```swift
body["masked_waveform"] = maskedWaveform.map { Double($0) }
```

**Kotlin:** Always use `.toDouble()` before `put()` into `JSONArray`:
```kotlin
maskedWaveform.forEach { put(it.toDouble()) }
```

### Error responses

| HTTP status | Meaning | Action |
|---|---|---|
| `422` | Schema or waveform violation | **Do not retry** — fix the payload. Check length, range, `sample_rate`, `channels`. |
| `500` | Inference failure | Retry after confirming `/health` `model_ready == true`. |

---

## Appendix: YAMNet response field reference

| Field | Description |
|---|---|
| `event_id` | Unique result ID — use for deduplication |
| `detected_events` | Ranked list, highest confidence first, max 10 |
| `class_name` | Snake_case label from the 100-class taxonomy |
| `class_index` | Integer index into `categories.json` |
| `confidence` | Mean score across active frames `[0.0, 1.0]` |
| `start_sec` / `end_sec` | Time window within the 10s capture |
| `peak_confidence` | Highest per-frame score within the window |
| `intensity_db` | RMS power in dBFS over the active window |
| `related` | Co-occurring classes above 0.05 threshold |
| `top_event` | `class_name` of `detected_events[0]` |
| `max_confidence` | `confidence` of `detected_events[0]` |
| `doa_deg` | Direction of arrival — echoed from request |
| `geo` | Location — echoed from request |

### Sample taxonomy labels (snake_case)

`accordion` · `acoustic_guitar` · `air_conditioner` · `airplane` · `alarm_clock` · `car_horn` · `chainsaw` · `children_playing` · `dog` · `drilling` · `engine` · `fireworks` · `glass_breaking` · `gun_shot` · `helicopter` · `motorcycle` · `rain` · `siren` · `thunder` · `traffic` · `train`

Full 100-class list: `models/categories.json` (served by the AIM node)
