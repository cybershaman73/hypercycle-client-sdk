"""
examples/audio/yamnet-classifier/python/example.py
HyperCycle SDK v0.3.1-beta — YAMNet Acoustic Classifier (Python)

Use case: Acoustic event classification
AIM image: yamnet-classifier
Endpoint: POST /aim/<slot>/infer

Audio input (choose one):
  1. Path to a WAV file (16kHz mono recommended, other formats auto-converted)
  2. Press Enter to use the built-in synthetic test waveform

masked_waveform requirements (422 on violation):
  - Flat JSON array of floats in [-1.0, +1.0]
  - Exactly sample_rate x duration_sec samples (±2%)
  - 16,000 Hz, mono, speech zeroed, rounded to 6dp

Usage:
    export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
    python3 example.py
"""

import sys, os, math, datetime, random, struct, wave
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../python"))
from hypercycle_client import HyperCycleClient

IMAGE_NAME           = "yamnet-classifier"
AIM_PROTOCOL_VERSION = "0.1"
SAMPLE_RATE          = 16000
DURATION_SEC         = 10.0


# ---------------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------------

def load_wav(path):
    """
    Load a WAV file and return a normalized float waveform.

    Handles:
      - Mono and stereo (stereo is downmixed)
      - 8-bit, 16-bit, and 32-bit PCM
      - Any sample rate (resampled to 16kHz via simple decimation/interpolation)

    Returns a flat list of floats in [-1.0, +1.0], rounded to 6dp.
    """
    with wave.open(path, "rb") as wf:
        n_channels  = wf.getnchannels()
        samp_width  = wf.getsampwidth()
        src_rate    = wf.getframerate()
        n_frames    = wf.getnframes()
        raw         = wf.readframes(n_frames)

    # Decode PCM bytes
    if samp_width == 1:      # 8-bit unsigned
        samples = [((b - 128) / 128.0) for b in raw]
    elif samp_width == 2:    # 16-bit signed
        count   = len(raw) // 2
        samples = list(struct.unpack(f"<{count}h", raw))
        samples = [s / 32768.0 for s in samples]
    elif samp_width == 4:    # 32-bit signed
        count   = len(raw) // 4
        samples = list(struct.unpack(f"<{count}i", raw))
        samples = [s / 2147483648.0 for s in samples]
    else:
        raise ValueError(f"Unsupported sample width: {samp_width} bytes")

    # Downmix stereo to mono
    if n_channels == 2:
        samples = [
            (samples[i] + samples[i + 1]) / 2.0
            for i in range(0, len(samples) - 1, 2)
        ]
    elif n_channels > 2:
        raise ValueError(f"Unsupported channel count: {n_channels}")

    # Resample to 16kHz if needed (linear interpolation)
    if src_rate != SAMPLE_RATE:
        ratio      = SAMPLE_RATE / src_rate
        new_length = int(len(samples) * ratio)
        resampled  = []
        for i in range(new_length):
            src_idx = i / ratio
            lo      = int(src_idx)
            hi      = min(lo + 1, len(samples) - 1)
            frac    = src_idx - lo
            resampled.append(samples[lo] * (1 - frac) + samples[hi] * frac)
        samples = resampled

    # Trim or pad to exactly DURATION_SEC
    target = int(SAMPLE_RATE * DURATION_SEC)
    if len(samples) > target:
        samples = samples[:target]
        print(f"  WAV trimmed to {DURATION_SEC}s")
    elif len(samples) < int(target * 0.98):
        # Pad with silence if short (within ±2% tolerance is fine without padding)
        samples = samples + [0.0] * (target - len(samples))
        print(f"  WAV padded with silence to {DURATION_SEC}s")

    # Normalize and round
    return [round(max(-1.0, min(1.0, s)), 6) for s in samples]


def generate_test_waveform(duration_sec=DURATION_SEC, sample_rate=SAMPLE_RATE):
    """
    Synthetic mixed waveform — layered tones + noise floor.
    Produces detectable results from YAMNet unlike a pure sine tone.
    Replace with real captured audio in production.
    """
    random.seed(42)
    n = int(sample_rate * duration_sec)
    result = []
    for i in range(n):
        t = i / sample_rate
        v = (
            0.3 * math.sin(2 * math.pi * 120 * t) +
            0.2 * math.sin(2 * math.pi * 440 * t) +
            0.1 * math.sin(2 * math.pi * 880 * t) +
            0.05 * (random.random() * 2 - 1)
        )
        result.append(round(max(-1.0, min(1.0, v)), 6))
    return result


def validate_waveform(waveform):
    expected  = SAMPLE_RATE * DURATION_SEC
    tolerance = expected * 0.02
    if not (expected - tolerance <= len(waveform) <= expected + tolerance):
        raise ValueError(
            f"Length {len(waveform):,} outside ±2% of expected {int(expected):,} samples"
        )
    bad = sum(1 for v in waveform if v < -1.0 or v > 1.0)
    if bad:
        raise ValueError(f"{bad} sample(s) outside [-1.0, +1.0]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        client = HyperCycleClient()
    except ValueError as e:
        print(f"Config error: {e}\nSet: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000")
        sys.exit(1)

    print(f"HyperCycle Client SDK {HyperCycleClient.SDK_VERSION}")
    print(f"Node: {client.node_url}\n")

    if not client.ping():
        print("Node unreachable. Check HYPERCYCLE_NODE_URL.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 1. Prompt for audio file
    # ------------------------------------------------------------------
    print("Audio input:")
    print("  Enter path to a WAV file, or press Enter to use the built-in test waveform.")
    wav_path = input("  WAV file path: ").strip().strip('"').strip("'")

    if wav_path:
        if not os.path.exists(wav_path):
            print(f"  File not found: {wav_path}")
            sys.exit(1)
        print(f"  Loading {wav_path}...")
        try:
            waveform = load_wav(wav_path)
            print(f"  Loaded {len(waveform):,} samples from WAV\n")
        except Exception as e:
            print(f"  Failed to load WAV: {e}")
            sys.exit(1)
    else:
        print("  No file provided — using built-in test waveform\n")
        waveform = generate_test_waveform()

    try:
        validate_waveform(waveform)
    except ValueError as e:
        print(f"Waveform validation failed: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Discover
    # ------------------------------------------------------------------
    print(f"Discovering '{IMAGE_NAME}'...")
    discovery = client.discover(IMAGE_NAME)
    if not discovery.ok:
        print(f"  Discovery failed: {discovery.error}")
        sys.exit(1)
    aim = discovery.data
    ep_str = ", ".join(aim.endpoints) if aim.endpoints else "none declared"
    print(f"  Slot {aim.slot}  endpoints: {ep_str}\n")

    # ------------------------------------------------------------------
    # 3. Health check
    # ------------------------------------------------------------------
    health = client.health(aim.slot)
    if not health.ok:
        print(f"  Health check failed: {health.error}")
        sys.exit(1)
    print(f"Health: {health.data}\n")

    # ------------------------------------------------------------------
    # 4. Submit inference
    # ------------------------------------------------------------------
    body = {
        "device_id":       "yamnet-python-example",
        "timestamp":       datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample_rate":     SAMPLE_RATE,
        "channels":        1,
        "duration_sec":    DURATION_SEC,
        "masked_waveform": waveform,
        "doa_deg":         0.0,
        "geo":             {"lat": 42.3265, "lon": -122.8756},
        "sdk_version":     AIM_PROTOCOL_VERSION,
    }

    approx_kb = len(waveform) * 8 // 1024
    print(f"Submitting inference (~{approx_kb} KB)...")
    result = client.execute(aim.slot, "infer", body)

    if not result.ok:
        if result.status == 422:
            print(f"  422 Schema violation: {result.error}")
            print("  → Check waveform: length, range [-1,+1], sample_rate=16000, channels=1")
        else:
            print(f"  Error {result.status}: {result.error}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 5. Display results
    # ------------------------------------------------------------------
    data   = result.data
    events = data.get("detected_events", [])

    print(f"\nTop event      : {data.get('top_event', 'none')}")
    print(f"Max confidence : {data.get('max_confidence', 0):.2%}")

    if events:
        print(f"\nDetected events ({len(events)}, ranked by confidence):")
        for ev in events:
            print(
                f"  [{ev.get('class_index', '?'):3}] "
                f"{ev.get('class_name', '?'):<25} "
                f"conf={ev.get('confidence', 0):.2%}  "
                f"peak={ev.get('peak_confidence', 0):.2%}  "
                f"{ev.get('start_sec', 0):.1f}s–{ev.get('end_sec', 0):.1f}s  "
                f"{ev.get('intensity_db', 0):.1f} dBFS"
            )
            for rel in ev.get("related", []):
                print(f"         co-occurring: {rel.get('class_name')} "
                      f"({rel.get('confidence', 0):.2%})")
    else:
        print("\nNo events detected above confidence threshold.")
        print("Try a real audio recording for better results.")


if __name__ == "__main__":
    main()
