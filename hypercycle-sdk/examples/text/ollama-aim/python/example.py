"""
examples/text/ollama-aim/python/example.py
HyperCycle SDK v0.2.1-beta — Ollama LLM AIM (Python)

Use case: Text generation / chat via local LLM
AIM image: ollama-aim
Endpoint: POST /aim/<slot>/request
Warmup:   ~4 minutes after status = "running"
          The AIM downloads the model AFTER the container starts.
          Health checks pass immediately but inference fails until download
          completes. Use wait_for_ready() below before submitting prompts.

Default model: gemma2:2b (CPU-safe, ~8GB RAM)
Other models (set via OLLAMA_MODEL env on deploy):
  gemma3:4b   ~6 GB VRAM
  mistral:7b  ~8–16 GB VRAM
  llama3:8b   ~10–16 GB VRAM

Cost: $0.02 USDC per call by default (operator-configurable, can be zero)

Usage:
    export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
    python3 example.py
"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../python"))
from hypercycle_client import HyperCycleClient

IMAGE_NAME = "ollama-aim"


def wait_for_ready(client, slot, max_wait_sec=300, poll_interval=15):
    """
    Poll /health until the AIM is ready to serve inference.

    IMPORTANT: The ollama-aim downloads its model AFTER the container enters
    'running' state. This takes ~4 minutes. During this window, /health returns
    ok but inference requests will fail. This function waits it out.

    Returns True when ready, False if max_wait_sec is exceeded.
    """
    print(f"Waiting for model to be ready (up to {max_wait_sec//60}min)...")
    elapsed = 0
    while elapsed < max_wait_sec:
        health = client.health(slot)
        if health.ok:
            model_ready = health.data.get("model_ready", False)
            status      = health.data.get("status", "")
            model_name  = health.data.get("model", "")
            print(f"  [{elapsed:3d}s] status={status}  model_ready={model_ready}  model={model_name}")
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
    # Wait for model download (critical for ollama-aim)
    # ------------------------------------------------------------------
    if not wait_for_ready(client, aim.slot):
        print("Model not ready after timeout. Check docker logs on the node.")
        sys.exit(1)
    print("Model ready.\n")

    # ------------------------------------------------------------------
    # Cost estimate
    # ------------------------------------------------------------------
    test_body = {"prompt": "Hello"}
    estimate  = client.estimate(aim.slot, "request", test_body)
    if estimate.ok:
        costs = estimate.data.get("costs", [])
        for c in costs:
            print(f"Estimated cost: {c.get('currency')} {c.get('estimated_cost', 0)}")
        if not costs:
            print("Cost: free (no cost declared)")
    print()

    # ------------------------------------------------------------------
    # Run inference — POST /request
    # Endpoint is /request, not /chat or /generate
    # ------------------------------------------------------------------
    prompts = [
        "List Earth's atmosphere layers and altitude ranges in one sentence each.",
        "Return JSON: {\"layers\": [{\"name\": str, \"min_km\": int, \"max_km\": int}]}. No extra text.",
    ]

    for prompt in prompts:
        print(f"Prompt: {prompt[:60]}...")
        body   = {"prompt": prompt}
        result = client.execute(aim.slot, "request", body)

        if not result.ok:
            print(f"  Error {result.status}: {result.error}")
            continue

        response_text = result.data.get("response", result.data.get("text", ""))
        model_used    = result.data.get("model", "unknown")
        print(f"  Model   : {model_used}")
        print(f"  Response: {response_text[:300]}{'...' if len(response_text) > 300 else ''}")
        print()


if __name__ == "__main__":
    main()
