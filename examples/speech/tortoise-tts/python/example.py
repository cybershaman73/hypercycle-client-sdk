"""
examples/speech/tortoise-tts/python/example.py
HyperCycle SDK v0.3.1-beta — Tortoise Text-to-Speech AIM (Python)

Use case: Text-to-speech synthesis with multiple voice avatars
AIM image: tortoise-tts
Endpoints (from /info uri_cost):
  POST /speak        → synthesize speech, returns base64 WAV
  GET  /list-voices  → available voice names (served after model loads)

Warmup: ~4 minutes after container status = "running"
        The model downloads and loads after container start.
        /health is attempted first; if absent (404) or not yet ready,
        the example falls through to probing /speak directly.

Hardware: NVIDIA GPU with 8+ GB free VRAM required on the node.

Input:  { "text": "...", "voice": "daniel" }   max 100 characters
Output: { "file": "<base64-encoded WAV>" }     decode → write → play

Available voices: angie, applejack, cond_late, daniel, deniro, emma,
                  freeman, geralt, halle, jlaw, li

Cost: $0.01–$0.02 USDC per call (operator-configurable, can be zero)

Usage:
    export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
    python3 example.py
"""

import sys, os, time, base64
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../python"))
from hypercycle_client import HyperCycleClient

IMAGE_NAME    = "tortoise-tts"
DEFAULT_VOICE = "daniel"
OUTPUT_WAV    = "output.wav"


def report_aim(aim):
    """Print everything /info tells us about this AIM before making calls."""
    print(f"  Image    : {aim.image_name}:{aim.image_tag}")
    print(f"  Slot     : {aim.slot}  (internal port {aim.port})")
    print(f"  Status   : {aim.status}")
    print(f"  Container: {aim.container_id}")

    if aim.endpoints:
        print(f"  Endpoints declared in /info:")
        seen = set()
        for ep in aim.endpoints:
            if ep not in seen:
                ep_costs = [c for c in aim.costs if c.endpoint == ep]
                if ep_costs:
                    cost_str = ", ".join(
                        f"{c.currency} fixed={c.fixed}"
                        for c in ep_costs
                    )
                    free = all(c.fixed == 0 for c in ep_costs)
                    cost_label = "free" if free else cost_str
                else:
                    cost_label = "no cost declared"
                print(f"    {ep:<20} {cost_label}")
                seen.add(ep)
    else:
        print(f"  Endpoints: not declared in /info (check manifest.json)")

    gpu = aim.labels.get("GPUS", "")
    gpu_mem = aim.labels.get("GPU_MEMORY", "")
    if gpu:
        print(f"  GPU req  : {gpu}  VRAM: {gpu_mem or 'unspecified'}")
    print()


def check_health(client, slot):
    """
    Attempt /health. Returns one of four outcomes:
      "ready"       — endpoint exists, model_ready == true
      "not_ready"   — endpoint exists, model_ready == false
      "no_endpoint" — 404, AIM has no /health endpoint
      "error"       — 500 or connection error (includes NM routing bug)
    """
    health = client.health(slot)

    if not health.ok:
        if health.status == 404:
            return "no_endpoint", None
        return "error", health

    model_ready = health.data.get("model_ready", True)
    if model_ready:
        return "ready", health.data
    return "not_ready", health.data


def wait_for_health(client, slot, max_wait_sec=300, poll_interval=15):
    """
    Poll /health until model_ready or until we determine the endpoint
    is unavailable. Returns ("ready"|"no_endpoint"|"timeout"), last_data.

    Fall-through rules (stop polling immediately):
      - 404: AIM has no /health endpoint
      - 500 on first attempt: Node Manager error routing /health (known NM
        bug where cost resolution runs on costless endpoints). Treat as
        no usable health signal and fall through to active endpoint probe.
      - "not_ready": keep polling — model is loading normally
    """
    print(f"Checking /health...")
    outcome, data = check_health(client, slot)

    if outcome == "ready":
        print(f"  [  0s] /health → model_ready=True")
        return "ready", data

    if outcome == "no_endpoint":
        print(f"  [  0s] /health → 404 (no health endpoint)")
        return "no_endpoint", None

    if outcome == "error":
        # A failed /health is not a model state signal.
        # Fall through immediately rather than polling a broken route.
        print(f"  [  0s] /health → {data.status or 'no response'} ({data.error})")
        print(f"         Falling through to active endpoint probe.")
        return "no_endpoint", None

    # model_ready=False — poll until ready or timeout
    print(f"  [  0s] /health → model_ready=False — polling...")
    elapsed = poll_interval
    time.sleep(poll_interval)

    while elapsed < max_wait_sec:
        outcome, data = check_health(client, slot)

        if outcome == "ready":
            print(f"  [{elapsed:3d}s] /health → model_ready=True")
            return "ready", data

        if outcome in ("no_endpoint", "error"):
            print(f"  [{elapsed:3d}s] /health → {outcome} — falling through")
            return "no_endpoint", None

        print(f"  [{elapsed:3d}s] /health → model_ready=False — waiting...")
        time.sleep(poll_interval)
        elapsed += poll_interval

    return "timeout", None


def speak_with_retry(client, slot, body, max_wait_sec=360, poll_interval=20):
    """
    Probe /speak directly with retry backoff.

    Used when /health is absent or timed out. A successful /speak response
    is the definitive signal that the model is loaded. Retries on 500 or
    connection error; exits immediately on 400 (bad request — don't retry).
    """
    print(f"Probing /speak directly (up to {max_wait_sec//60}min)...")
    elapsed = 0
    attempt = 0

    while elapsed < max_wait_sec:
        attempt += 1
        result = client.execute(slot, "speak", body)

        if result.ok:
            print(f"  [{elapsed:3d}s] /speak → success (attempt {attempt})")
            return result

        if result.status == 400:
            print(f"  [{elapsed:3d}s] /speak → 400 bad request: {result.error}")
            return result   # non-retryable

        print(f"  [{elapsed:3d}s] /speak → {result.status or 'no response'} — retrying in {poll_interval}s")
        time.sleep(poll_interval)
        elapsed += poll_interval

    return result


def main():
    try:
        client = HyperCycleClient()
    except ValueError as e:
        print(f"Config error: {e}\nSet: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000")
        sys.exit(1)

    print(f"HyperCycle Client SDK {HyperCycleClient.SDK_VERSION}")
    print(f"Node: {client.node_url}\n")

    # ------------------------------------------------------------------
    # 1. Confirm node is reachable
    # ------------------------------------------------------------------
    print("Pinging node...")
    if not client.ping():
        print("  Node unreachable. Check HYPERCYCLE_NODE_URL.")
        sys.exit(1)
    print("  Node reachable.\n")

    # ------------------------------------------------------------------
    # 2. Discover — parse and report all AIM info from /info
    # ------------------------------------------------------------------
    print(f"Discovering '{IMAGE_NAME}'...")
    discovery = client.discover(IMAGE_NAME)
    if not discovery.ok:
        print(f"  Discovery failed: {discovery.error}")
        sys.exit(1)
    aim = discovery.data
    report_aim(aim)

    # ------------------------------------------------------------------
    # 3. Health check — attempt first; fall through if absent/timeout
    # ------------------------------------------------------------------
    outcome, health_data = wait_for_health(client, aim.slot)

    if outcome == "ready":
        print(f"  Model ready via /health.\n")

    elif outcome == "no_endpoint":
        print(f"  No /health endpoint — falling through to /speak probe.\n")
        # speak_with_retry runs below

    elif outcome == "timeout":
        print(f"  /health timed out — falling through to /speak probe.\n")
        # speak_with_retry runs below

    # ------------------------------------------------------------------
    # 4. Build request
    # ------------------------------------------------------------------
    text  = "You are now hearing this in my voice, courtesy of the HyperCycle network."
    voice = DEFAULT_VOICE
    if len(text) > 100:
        print(f"Text exceeds 100 char limit ({len(text)} chars)")
        sys.exit(1)
    body  = {"text": text, "voice": voice}

    print(f"Text  : \"{text}\"")
    print(f"Voice : {voice}\n")

    # ------------------------------------------------------------------
    # 5. Execute — direct call if health confirmed, retry probe if not
    # ------------------------------------------------------------------
    if outcome == "ready":
        print("Submitting /speak...")
        result = client.execute(aim.slot, "speak", body)
    else:
        result = speak_with_retry(client, aim.slot, body)

    if not result.ok:
        print(f"\nFailed ({result.status}): {result.error}")
        print("\nDiagnostic steps on the node:")
        print("  docker ps                             — confirm container is running")
        print("  docker logs <container_id> --tail 50  — look for download/CUDA errors")
        print("  nvidia-smi                            — confirm 8+ GB VRAM is free")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 6. Decode and save WAV
    # ------------------------------------------------------------------
    audio_b64 = result.data.get("file", "")
    if not audio_b64:
        print("No audio data in response.")
        sys.exit(1)

    audio_bytes = base64.b64decode(audio_b64)
    with open(OUTPUT_WAV, "wb") as f:
        f.write(audio_bytes)

    print(f"\nAudio saved : {OUTPUT_WAV} ({len(audio_bytes) // 1024} KB)")
    print("Play with   :")
    print("  macOS  : afplay output.wav")
    print("  Linux  : aplay output.wav")
    print("  Windows: (New-Object Media.SoundPlayer 'output.wav').PlaySync()")

    for c in result.data.get("costs", []):
        used = c.get("used", c.get("estimated_cost", 0))
        print(f"Cost        : {c.get('currency')} {used}")


if __name__ == "__main__":
    main()
