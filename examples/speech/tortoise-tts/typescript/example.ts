/**
 * examples/speech/tortoise-tts/typescript/example.ts
 * HyperCycle SDK v0.3.1-beta — Tortoise TTS AIM (TypeScript)
 *
 * NOTE: tortoise-tts has no /health endpoint.
 * Warmup detection works by retrying /speak until the model responds.
 * Model loads ~4 min after container enters "running" state.
 *
 * Usage: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
 *        npx ts-node example.ts
 */

import { HyperCycleClient, type HyperCycleResult } from "../../../../typescript/hypercycle-client";
import * as fs from "fs";

const IMAGE_NAME    = "tortoise-tts";
const DEFAULT_VOICE = "daniel";
const OUTPUT_WAV    = "output.wav";

async function speakWithRetry(
  client:      HyperCycleClient,
  slot:        number,
  body:        Record<string, unknown>,
  maxWaitMs  = 360_000,
  pollMs     = 20_000,
) {
  /**
   * Retry /speak with backoff — handles the ~4 min warmup window.
   * tortoise-tts has no /health endpoint; a successful /speak is the
   * only signal the model is loaded.
   */
  console.log(`Attempting /speak (model warms ~4min, timeout ${maxWaitMs / 60000}min)...`);
  let elapsed = 0;
  let attempt = 0;
  let lastFailure: HyperCycleResult<Record<string, unknown>> | undefined;

  while (elapsed < maxWaitMs) {
    attempt++;
    const result = await client.execute(slot, "speak", body);

    if (result.ok) {
      console.log(`  [${Math.round(elapsed / 1000)}s] Success on attempt ${attempt}`);
      return result;
    }

    // 400 = bad request — do not retry
    if (result.status === 400) {
      console.error(`  [${Math.round(elapsed / 1000)}s] Bad request: ${result.error}`);
      return result;
    }

    lastFailure = result;
    console.log(`  [${Math.round(elapsed / 1000)}s] Not ready (${result.status ?? "no response"}) — retrying in ${pollMs / 1000}s`);
    await new Promise(r => setTimeout(r, pollMs));
    elapsed += pollMs;
  }

  // Return last failure
  return lastFailure ?? {
    ok: false,
    data: null,
    error: `Timed out waiting for TTS model after ${maxWaitMs / 1000}s`,
    status: null,
  };
}

async function main() {
  let client: HyperCycleClient;
  try {
    client = new HyperCycleClient();
  } catch (e) {
    console.error("Config error:", e instanceof Error ? e.message : e);
    process.exit(1);
  }

  console.log(`SDK ${HyperCycleClient.SDK_VERSION} — tortoise-tts\n`);

  if (!await client.ping()) { console.error("Node unreachable."); process.exit(1); }

  const discovery = await client.discover(IMAGE_NAME);
  if (!discovery.ok) { console.error("Discovery failed:", discovery.error); process.exit(1); }
  const aim = discovery.data;
  console.log(`Found '${IMAGE_NAME}' at slot ${aim.slot}\n`);

  const text  = "You are now hearing this in my voice, courtesy of the HyperCycle network.";
  const voice = DEFAULT_VOICE;
  if (text.length > 100) {
    console.error(`Text exceeds 100 char limit (${text.length} chars)`);
    process.exit(1);
  }
  console.log(`Text : "${text}"`);
  console.log(`Voice: ${voice}\n`);

  const result = await speakWithRetry(client, aim.slot, { text, voice });

  if (!result.ok) {
    console.error(`\nFailed: ${result.error}`);
    console.error("Check: docker logs <container_id> --tail 50");
    process.exit(1);
  }

  const audioB64 = (result.data as any)["file"] as string;
  if (!audioB64) { console.error("No audio in response."); process.exit(1); }

  const audioBuffer = Buffer.from(audioB64, "base64");
  fs.writeFileSync(OUTPUT_WAV, audioBuffer);
  console.log(`\nAudio saved: ${OUTPUT_WAV} (${Math.round(audioBuffer.length / 1024)} KB)`);
}

main().catch(console.error);
