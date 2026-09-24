/**
 * examples/text/ollama-aim/typescript/example.ts
 * HyperCycle SDK v0.3.1-beta — Ollama LLM AIM (TypeScript)
 *
 * AIM image: ollama-aim     Endpoint: POST /aim/<slot>/request
 * Warmup: ~4 min after "running" — model downloads after container starts.
 *
 * Usage: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
 *        npx ts-node example.ts
 */

import { HyperCycleClient } from "../../../../typescript/hypercycle-client";

const IMAGE_NAME = "ollama-aim";

async function waitForReady(
  client: HyperCycleClient,
  slot: number,
  maxWaitMs = 300_000,
  pollMs    = 15_000,
): Promise<boolean> {
  /**
   * The ollama-aim downloads its model AFTER entering "running" state (~4 min).
   * Priority: model_ready → ollama_healthy → field absent (assume ready).
   */
  console.log(`Waiting for model (up to ${maxWaitMs / 60000}min)...`);
  let elapsed = 0;
  while (elapsed < maxWaitMs) {
    const health = await client.health(slot);
    if (health.ok) {
      const ready = "model_ready" in health.data
        ? health.data["model_ready"] as boolean
        : "ollama_healthy" in health.data
          ? health.data["ollama_healthy"] as boolean
          : true;
      const model = health.data["model"] ?? "";
      console.log(`  [${Math.round(elapsed / 1000)}s] ready=${ready}  model=${model}`);
      if (ready) return true;
    }
    await new Promise(r => setTimeout(r, pollMs));
    elapsed += pollMs;
  }
  return false;
}

async function main() {
  let client: HyperCycleClient;
  try {
    client = new HyperCycleClient();
  } catch (e) {
    console.error("Config error:", e instanceof Error ? e.message : e);
    console.error("Set: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000");
    process.exit(1);
  }

  console.log(`SDK ${HyperCycleClient.SDK_VERSION} | ollama-aim example\n`);

  if (!await client.ping()) { console.error("Node unreachable."); process.exit(1); }

  const discovery = await client.discover(IMAGE_NAME);
  if (!discovery.ok) { console.error("Discovery failed:", discovery.error); process.exit(1); }
  const aim = discovery.data;
  console.log(`Found '${IMAGE_NAME}' at slot ${aim.slot}\n`);

  if (!await waitForReady(client, aim.slot)) {
    console.error("Model not ready after timeout."); process.exit(1);
  }
  console.log("Model ready.\n");

  const prompts = [
    "List Earth's atmosphere layers and altitude ranges in one sentence each.",
    'Return JSON: {"layers": [{"name": "str", "min_km": 0, "max_km": 0}]}. No extra text.',
  ];

  for (const prompt of prompts) {
    console.log(`Prompt: ${prompt.slice(0, 60)}...`);
    const result = await client.execute(aim.slot, "request", { prompt });

    if (!result.ok) {
      console.error(`  Error ${result.status}: ${result.error}`);
      continue;
    }
    const data = result.data as Record<string, any>;
    const text = data["response"] ?? data["text"] ?? "";
    console.log(`  Model   : ${data["model"] ?? "unknown"}`);
    console.log(`  Response: ${text.slice(0, 300)}${text.length > 300 ? "..." : ""}`);
    console.log();
  }
}

main().catch(console.error);
