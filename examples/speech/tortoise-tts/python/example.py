"""
examples/speech/tortoise-tts/python/example.py
HyperCycle SDK v0.2.1-beta — Tortoise Text-to-Speech AIM (Python)

Use case: Text-to-speech synthesis with multiple voice avatars
AIM image: tortoise-tts
Endpoints:
  GET  /aim/<slot>/list-voices  → available voice names
  POST /aim/<slot>/speak        → synthesize speech
Warmup:   ~4 minutes after status = "running"
          Model loads AFTER container starts. Wait for model_ready.

Hardware: Requires NVIDIA GPU with 8+ GB free VRAM

Input:
  { "text": "...", "voice": "daniel" }
  text: up to 100 characters including spaces
  voice: one of the names from /list-voices

Output:
  { "file": "<base64-encoded WAV>" }
  Decode base64 → write to .wav → play or send to device

Available voices (from Voiceboard UI):
  angie, applejack, cond_late, daniel, deniro, emma,
  freeman, geralt, halle, jlaw, li (and more via /list-voices)

Cost: $0.01–$0.02 USDC per call, scales with word count
      Operator can set to zero for beta/hackathon

Usage:
    export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
    python3 example.py
    # Produces output.wav in the current directory
"""

import sys, os, time, base64
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../python"))
from hypercycle_client import HyperCycleClient

IMAGE_NAME     = "tortoise-tts"
DEFAULT_VOICE  = "daniel"
OUTPUT_WAV     = "output.wav"


def wait_for_ready(client, slot, max_wait_sec=300, poll_interval=15):
    """
    Poll /health until the TTS model is loaded and ready.

    tortoise-tts loads its model after entering 'running' state (~4 min).
    Calls made before model_ready == true will error out.
    """
    print(f"Waiting for TTS model (up to {max_wait_sec//60}min)...")
    elapsed = 0
    while elapsed < max_wait_sec:
        health = client.health(slot)
        if health.ok:
            model_ready = health.data.get("model_ready", False)
            print(f"  [{elapsed:3d}s] model_ready={model_ready}")
            if model_ready:
                return True
        time.sleep(poll_interval)
        elapsed += poll_interval
    return False


def main():
    try:
        client = HyperCycleClient()
    except ValueError as e:
        print(f"Config error: {e}\nSet: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000")
        sys.exit(1)

    print(f"SDK {HyperCycleClient.SDK_VERSION} | Node: {client.node_url}\n")

    if not client.ping():
        print("Node unreachable."); sys.exit(1)

    # ------------------------------------------------------------------
    # Discover
    # ------------------------------------------------------------------
    discovery = client.discover(IMAGE_NAME)
    if not discovery.ok:
        print(f"Discovery failed: {discovery.error}"); sys.exit(1)
    aim = discovery.data
    print(f"Found '{IMAGE_NAME}' at slot {aim.slot}\n")

    # ------------------------------------------------------------------
    # Wait for model (critical for tortoise-tts)
    # ------------------------------------------------------------------
    if not wait_for_ready(client, aim.slot):
        print("Model not ready after timeout."); sys.exit(1)
    print("Model ready.\n")

    # ------------------------------------------------------------------
    # List available voices
    # ------------------------------------------------------------------
    voices_result = client.execute(aim.slot, "list-voices", {})
    if voices_result.ok:
        voices = voices_result.data.get("available_voices", [])
        print(f"Available voices ({len(voices)}): {', '.join(voices)}\n")
    else:
        print(f"Could not fetch voices: {voices_result.error}")
        voices = [DEFAULT_VOICE]

    # ------------------------------------------------------------------
    # Estimate cost
    # ------------------------------------------------------------------
    text        = "You are now hearing this in my voice, courtesy of the HyperCycle network."
    voice       = DEFAULT_VOICE if DEFAULT_VOICE in voices else (voices[0] if voices else DEFAULT_VOICE)
    sample_body = {"text": text, "voice": voice}

    estimate = client.estimate(aim.slot, "speak", sample_body)
    if estimate.ok:
        for c in estimate.data.get("costs", []):
            print(f"Estimated cost: {c.get('currency')} {c.get('estimated_cost', 0)}")
    print()

    # ------------------------------------------------------------------
    # Synthesize speech — POST /speak
    # text max 100 chars; response is base64-encoded WAV
    # ------------------------------------------------------------------
    print(f"Synthesizing: \"{text}\" (voice: {voice})")
    print("Processing time: 10s–1min depending on GPU...\n")

    result = client.execute(aim.slot, "speak", sample_body)

    if not result.ok:
        print(f"Error {result.status}: {result.error}")
        if result.status == 400:
            print("→ Check voice name — use /list-voices to confirm available voices.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Decode and save WAV
    # ------------------------------------------------------------------
    audio_b64 = result.data.get("file", "")
    if not audio_b64:
        print("No audio in response."); sys.exit(1)

    audio_bytes = base64.b64decode(audio_b64)
    with open(OUTPUT_WAV, "wb") as f:
        f.write(audio_bytes)

    print(f"Audio saved to {OUTPUT_WAV} ({len(audio_bytes):,} bytes)")
    print("Play it with: aplay output.wav  (Linux)  or  afplay output.wav  (macOS)")

    # Report costs returned by the AIM
    costs = result.data.get("costs", [])
    for c in costs:
        used = c.get("used", c.get("estimated_cost", 0))
        print(f"Actual cost: {c.get('currency')} {used}")


if __name__ == "__main__":
    main()
