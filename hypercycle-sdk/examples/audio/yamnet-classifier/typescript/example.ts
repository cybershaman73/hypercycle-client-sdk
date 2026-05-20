/**
 * examples/audio/yamnet-classifier/typescript/example.ts
 * HyperCycle SDK v0.2.1-beta — YAMNet Acoustic Classifier (TypeScript)
 * See python/example.py in this folder for full waveform documentation.
 *
 * Usage: export HYPERCYCLE_NODE_URL=http://<node-ip>:8000
 *        npx ts-node example.ts
 */

import { HyperCycleClient } from "../../../../typescript/hypercycle-client";

const IMAGE_NAME = "yamnet-classifier";
const AIM_VER    = "0.1";

function generateTestWaveform(durationSec = 10.0, sampleRate = 16000): number[] {
  const n = Math.floor(sampleRate * durationSec);
  return Array.from({ length: n }, (_, i) =>
    parseFloat((0.4 * Math.sin(2 * Math.PI * 440 * i / sampleRate)).toFixed(6))
  );
}

async function main() {
  let client: HyperCycleClient;
  try { client = new HyperCycleClient(); }
  catch (e) { console.error("Config error:", e instanceof Error ? e.message : e); process.exit(1); }

  console.log(`SDK ${HyperCycleClient.SDK_VERSION} | yamnet-classifier example\n`);
  if (!await client.ping()) { console.error("Node unreachable."); process.exit(1); }

  const discovery = await client.discover(IMAGE_NAME);
  if (!discovery.ok) { console.error("Discovery failed:", discovery.error); process.exit(1); }
  const aim = discovery.data;
  console.log(`Found '${IMAGE_NAME}' at slot ${aim.slot}\n`);

  const health = await client.health(aim.slot);
  if (!health.ok) { console.error("Health check failed:", health.error); process.exit(1); }
  console.log("Health:", health.data, "\n");

  const durationSec = 10.0, sampleRate = 16000;
  const waveform    = generateTestWaveform(durationSec, sampleRate);
  const body = {
    device_id: "ts-yamnet-example",
    timestamp: new Date().toISOString(),
    sample_rate: sampleRate, channels: 1, duration_sec: durationSec,
    masked_waveform: waveform, doa_deg: 0.0,
    geo: { lat: 42.3265, lon: -122.8756 },
    sdk_version: AIM_VER,
  };

  console.log(`Submitting (~${Math.round(waveform.length * 8 / 1024)} KB)...`);
  const result = await client.execute(aim.slot, "infer", body);
  if (!result.ok) {
    const hint = result.status === 422 ? " → fix payload" : " → retry after /health";
    console.error(`Error ${result.status}: ${result.error}${hint}`); process.exit(1);
  }

  const data = result.data as Record<string, any>;
  console.log(`\nTop event: ${data["top_event"]}  (${((data["max_confidence"] ?? 0) * 100).toFixed(1)}%)`);
  const events: any[] = data["detected_events"] ?? [];
  events.slice(0, 5).forEach(ev =>
    console.log(`  [${String(ev.class_index).padStart(3)}] ${ev.class_name.padEnd(25)} ${(ev.confidence*100).toFixed(1)}%  ${ev.start_sec.toFixed(1)}s–${ev.end_sec.toFixed(1)}s`)
  );
}

main().catch(console.error);
