"""
examples/audio/yamnet-classifier/python/example.py
HyperCycle SDK v0.2.1-beta — YAMNet Acoustic Classifier (Python)

Use case: Acoustic event classification
AIM image: yamnet-classifier
Endpoint: POST /aim/<slot>/infer
Warmup:   None (model loads at container start)

masked_waveform requirements (422 on violation):
  - Flat JSON array of floats in [-1.0, +1.0]
  - Exactly sample_rate × duration_sec samples (±2%)
  - 16,000 Hz, mono, speech zeroed, rounded to 6dp

Usage:
    export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
    python3 example.py
"""

import sys, os, math, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../python"))
from hypercycle_client import HyperCycleClient

IMAGE_NAME           = "yamnet-classifier"
AIM_PROTOCOL_VERSION = "0.1"


def generate_test_waveform(duration_sec=10.0, sample_rate=16000):
    """Synthetic 440 Hz sine tone. Replace with real captured audio."""
    n = int(sample_rate * duration_sec)
    return [round(0.4 * math.sin(2 * math.pi * 440 * i / sample_rate), 6) for i in range(n)]

def normalize_int16(samples):
    return [round(max(-1.0, min(1.0, s / 32768.0)), 6) for s in samples]

def normalize_float(samples):
    return [round(max(-1.0, min(1.0, s)), 6) for s in samples]

def validate_waveform(waveform, sample_rate=16000, duration_sec=10.0):
    expected  = sample_rate * duration_sec
    tolerance = expected * 0.02
    if not (expected - tolerance <= len(waveform) <= expected + tolerance):
        raise ValueError(f"Length {len(waveform):,} outside ±2% of expected {int(expected):,}")
    bad = sum(1 for v in waveform if v < -1.0 or v > 1.0)
    if bad:
        raise ValueError(f"{bad} sample(s) outside [-1.0, +1.0]")


def main():
    try:
        client = HyperCycleClient()
    except ValueError as e:
        print(f"Config error: {e}\nSet: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000")
        sys.exit(1)

    print(f"SDK {HyperCycleClient.SDK_VERSION} | Node: {client.node_url}\n")

    if not client.ping():
        print("Node unreachable."); sys.exit(1)

    discovery = client.discover(IMAGE_NAME)
    if not discovery.ok:
        print(f"Discovery failed: {discovery.error}"); sys.exit(1)
    aim = discovery.data
    print(f"Found '{IMAGE_NAME}' at slot {aim.slot}\n")

    health = client.health(aim.slot)
    if not health.ok or not health.data.get("model_ready", True):
        print("AIM not ready. Retry in a moment."); sys.exit(1)
    print(f"Health: {health.data}\n")

    duration_sec, sample_rate = 10.0, 16000
    waveform = generate_test_waveform(duration_sec, sample_rate)
    validate_waveform(waveform, sample_rate, duration_sec)

    body = {
        "device_id":       "python-yamnet-example",
        "timestamp":       datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample_rate":     sample_rate,
        "channels":        1,
        "duration_sec":    duration_sec,
        "masked_waveform": waveform,
        "doa_deg":         0.0,
        "geo":             {"lat": 42.3265, "lon": -122.8756},
        "sdk_version":     AIM_PROTOCOL_VERSION,
    }

    print(f"Submitting inference (~{len(waveform)*8//1024} KB)...")
    result = client.execute(aim.slot, "infer", body)

    if not result.ok:
        hint = " → fix payload" if result.status == 422 else " → retry after /health"
        print(f"Error {result.status}: {result.error}{hint}"); sys.exit(1)

    data = result.data
    print(f"\nTop event      : {data.get('top_event')}")
    print(f"Max confidence : {data.get('max_confidence', 0):.2%}")
    for ev in data.get("detected_events", [])[:5]:
        print(f"  [{ev['class_index']:3}] {ev['class_name']:<25} "
              f"{ev['confidence']:.2%}  {ev['start_sec']:.1f}s–{ev['end_sec']:.1f}s  "
              f"{ev['intensity_db']:.1f} dBFS")

if __name__ == "__main__":
    main()
