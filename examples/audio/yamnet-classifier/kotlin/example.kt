// examples/audio/yamnet-classifier/kotlin/example.kt
// HyperCycle SDK v0.3.1-beta — YAMNet Acoustic Classifier (Kotlin/Android)
// See python/example.py in this folder for full waveform documentation.
// Set HYPERCYCLE_NODE_URL environment variable before running.

package ai.hypercycle.sdk.examples

import ai.hypercycle.sdk.*
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import kotlin.math.sin

fun generateTestWaveform(durationSec: Double = 10.0, sampleRate: Int = 16000): JSONArray {
    val n = (sampleRate * durationSec).toInt()
    return JSONArray().apply {
        repeat(n) { i ->
            put(Math.round(0.4 * sin(2.0 * Math.PI * 440.0 * i / sampleRate) * 1_000_000.0) / 1_000_000.0)
        }
    }
}

suspend fun runYAMNetExample() {
    println("HyperCycle SDK ${HyperCycleClient.SDK_VERSION} — yamnet-classifier example\n")
    val client = HyperCycleClient()

    val aim = when (val d = client.discover("yamnet-classifier")) {
        is HyperCycleResult.Success -> d.data
        is HyperCycleResult.Failure -> { println("Discovery failed: ${d.error}"); return }
    }
    println("Found 'yamnet-classifier' at slot ${aim.slot}\n")

    val body = JSONObject().apply {
        put("device_id", "kotlin-yamnet-example")
        put("timestamp", Instant.now().toString())
        put("sample_rate", 16000); put("channels", 1); put("duration_sec", 10.0)
        put("masked_waveform", generateTestWaveform())
        put("doa_deg", 0.0)
        put("geo", JSONObject().put("lat", 42.3265).put("lon", -122.8756))
        put("sdk_version", "0.1")
    }

    println("Submitting inference...")
    when (val r = client.execute(aim.slot, "infer", body)) {
        is HyperCycleResult.Success -> println("Top event: ${r.data.optString("top_event")}")
        is HyperCycleResult.Failure -> println("Error ${r.statusCode}: ${r.error}")
    }
}

fun main() = runBlocking { runYAMNetExample() }
