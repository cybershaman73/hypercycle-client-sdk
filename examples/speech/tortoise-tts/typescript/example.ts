/**
 * examples/speech/tortoise-tts/typescript/example.ts
 * HyperCycle SDK v0.2.1-beta — Tortoise TTS AIM (TypeScript)
 *
 * AIM image: tortoise-tts
 * Endpoints: GET /list-voices, POST /speak
 * Warmup: ~4 min after "running" — model loads after container starts.
 * Hardware: NVIDIA GPU 8+ GB free VRAM required
 *
 * Input:  { text: "...", voice: "daniel" }  (max 100 chars)
 * Output: { file: "<base64 WAV>" }  →  decode → write to .wav
 *
 * Usage: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
 *        npx ts-node example.ts
 */

import { HyperCycleClient } from "../../../../typescript/hypercycle-client";
import * as fs from "fs";

const IMAGE_NAME    = "tortoise-tts";
const DEFAULT_VOICE = "daniel";
const OUTPUT_WAV    = "output.wav";

async function waitForReady(
  client: HyperCycleClient,
  slot: number,
  maxWaitMs = 300_000,
  pollMs    = 15_000,
): Promise<boolean> {
  console.log(`Waiting for TTS model (up to ${maxWaitMs / 60000}min)...`);
  let elapsed = 0;
  while (elapsed < maxWaitMs) {
    const health = await client.health(slot);
    if (health.ok) {
      const ready = (health.data["model_ready"] as boolean) ?? false;
      console.log(`  [${Math.round(elapsed / 1000)}s] model_ready=${ready}`);
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
    process.exit(1);
  }

  console.log(`SDK ${HyperCycleClient.SDK_VERSION} | tortoise-tts example\n`);

  if (!await client.ping()) { console.error("Node unreachable."); process.exit(1); }

  const discovery = await client.discover(IMAGE_NAME);
  if (!discovery.ok) { console.error("Discovery failed:", discovery.error); process.exit(1); }
  const aim = discovery.data;
  console.log(`Found '${IMAGE_NAME}' at slot ${aim.slot}\n`);

  if (!await waitForReady(client, aim.slot)) {
    console.error("Model not ready after timeout."); process.exit(1);
  }
  console.log("Model ready.\n");

  // List voices
  const voicesResult = await client.execute(aim.slot, "list-voices", {});
  let voices: string[] = [DEFAULT_VOICE];
  if (voicesResult.ok) {
    voices = (voicesResult.data as any)["available_voices"] ?? [DEFAULT_VOICE];
    console.log(`Available voices: ${voices.join(", ")}\n`);
  }

  const text  = "You are now hearing this in my voice, courtesy of the HyperCycle network.";
  const voice = voices.includes(DEFAULT_VOICE) ? DEFAULT_VOICE : voices[0];

  // Estimate
  const estimate = await client.estimate(aim.slot, "speak", { text, voice });
  if (estimate.ok) {
    const costs = (estimate.data["costs"] as any[]) ?? [];
    costs.forEach(c => console.log(`Estimated cost: ${c.currency} ${c.estimated_cost ?? 0}`));
  }
  console.log();

  // Speak — POST /speak, response is base64 WAV
  console.log(`Synthesizing: "${text}" (voice: ${voice})`);
  console.log("Processing: 10s–1min depending on GPU...\n");

  const result = await client.execute(aim.slot, "speak", { text, voice });
  if (!result.ok) {
    const hint = result.status === 400 ? " → check voice name via /list-voices" : "";
    console.error(`Error ${result.status}: ${result.error}${hint}`);
    process.exit(1);
  }

  const audioB64 = (result.data as any)["file"] as string;
  if (!audioB64) { console.error("No audio in response."); process.exit(1); }

  const audioBuffer = Buffer.from(audioB64, "base64");
  fs.writeFileSync(OUTPUT_WAV, audioBuffer);
  console.log(`Audio saved to ${OUTPUT_WAV} (${audioBuffer.length.toLocaleString()} bytes)`);

  const costs = (result.data as any)["costs"] ?? [];
  costs.forEach((c: any) => console.log(`Actual cost: ${c.currency} ${c.used ?? c.estimated_cost ?? 0}`));
}

main().catch(console.error);
