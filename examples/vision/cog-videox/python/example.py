"""
examples/vision/cog-videox/python/example.py
HyperCycle SDK v0.3.1-beta — CogVideoX Text-to-Video AIM (Python)

⚠️  STATUS: AIM IN ACTIVE DEVELOPMENT
    This AIM is not yet available on CBNO nodes.
    This example is a placeholder showing the expected integration pattern.
    Check release notes for availability updates.

Use case: Text-to-video generation (6s, 49 frames, 8fps)
AIM image: cog-videox
Author:   Ray Mata

Expected endpoints (when available):
  POST /aim/<slot>/generate  → submit text prompt, returns result/download URL
  GET  /aim/<slot>/download  → retrieve generated video file

Expected flow (async — generation takes minutes):
  1. POST /generate with {"text": "A dog runs on the beach"}
  2. Receive {"result": "<download-url-or-id>"}
  3. GET /download?id=<id> to retrieve the video when ready

Note: The output delivery mechanism (inline vs URL vs polling) is being
finalized. This example will be updated once the AIM is released on CBNO nodes.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../python"))
from hypercycle_client import HyperCycleClient

IMAGE_NAME = "cog-videox"


def main():
    print("⚠️  CogVideoX AIM is not yet available on CBNO nodes.")
    print("    This example is a placeholder for the expected integration pattern.\n")

    try:
        client = HyperCycleClient()
    except ValueError as e:
        print(f"Config error: {e}")
        sys.exit(1)

    # Discovery will fail until the AIM is deployed
    discovery = client.discover(IMAGE_NAME)
    if not discovery.ok:
        print(f"AIM not found: {discovery.error}")
        print("\nExpected integration pattern (when available):\n")
        print("  # 1. Discover")
        print("  aim = client.discover('cog-videox').data")
        print()
        print("  # 2. Estimate cost")
        print("  estimate = client.estimate(aim.slot, 'generate', {'text': 'A dog runs...'})")
        print()
        print("  # 3. Generate (long-running — expect minutes)")
        print("  result = client.execute(aim.slot, 'generate', {'text': 'A dog runs...'})")
        print("  download_url = result.data.get('result')")
        print()
        print("  # 4. Retrieve video (polling or direct URL — TBD)")
        print("  video = client.execute(aim.slot, 'download', {'id': download_url})")
        sys.exit(0)

    aim = discovery.data
    print(f"Found '{IMAGE_NAME}' at slot {aim.slot}")
    print("Update this example once the AIM endpoint contract is confirmed.")


if __name__ == "__main__":
    main()
