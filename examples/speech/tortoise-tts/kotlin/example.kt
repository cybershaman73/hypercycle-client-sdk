// examples/speech/tortoise-tts/kotlin/example.kt
// HyperCycle SDK v0.2.1-beta — Tortoise TTS AIM (Kotlin/Android)
//
// AIM image: tortoise-tts
// Endpoints: GET /list-voices, POST /speak
// Warmup: ~4 min after "running" — model loads after container starts.
// Hardware: NVIDIA GPU 8+ GB free VRAM required on the node.
//
// Input:  JSONObject { "text": "...", "voice": "daniel" }  max 100 chars
// Output: JSONObject { "file": "<base64 WAV>" }
//         → decode with Base64.decode() → play with MediaPlayer or ExoPlayer
//
// Android usage: call ttsService.speak() from viewModelScope.launch { }
// JVM/CLI:       fun main() = runBlocking { runExample() }

package ai.hypercycle.sdk.examples

import ai.hypercycle.sdk.*
import android.util.Base64         // Android — swap for java.util.Base64 on JVM
import kotlinx.coroutines.*
import org.json.JSONObject

class TortoiseTTSService(nodeUrl: String? = null) {

    companion object { private const val IMAGE_NAME = "tortoise-tts" }

    private val client = HyperCycleClient(nodeUrl)

    /** Poll until TTS model is loaded (~4 min after "running"). */
    suspend fun waitForReady(slot: Int, maxWaitSec: Int = 300, pollSec: Long = 15): Boolean {
        println("Waiting for TTS model (up to ${maxWaitSec / 60}min)...")
        var elapsed = 0
        while (elapsed < maxWaitSec) {
            val health = client.health(slot)
            if (health is HyperCycleResult.Success) {
                val ready = health.data.optBoolean("model_ready", false)
                println("  [${elapsed}s] model_ready=$ready")
                if (ready) return true
            }
            delay(pollSec * 1000)
            elapsed += pollSec.toInt()
        }
        return false
    }

    /** Fetch available voice names from /list-voices. */
    suspend fun listVoices(slot: Int): List<String> {
        val body   = JSONObject()
        val result = client.execute(slot, "list-voices", body)
        if (result is HyperCycleResult.Success) {
            val arr = result.data.optJSONArray("available_voices") ?: return emptyList()
            return (0 until arr.length()).map { arr.getString(it) }
        }
        return emptyList()
    }

    /**
     * Full flow: discover → wait → speak.
     * Returns raw WAV bytes on success.
     * text must be ≤ 100 characters.
     */
    suspend fun speak(text: String, voice: String = "daniel"): HyperCycleResult<ByteArray> {
        if (text.length > 100) {
            return HyperCycleResult.Failure("Text exceeds 100 char limit (${text.length} chars)")
        }

        val aim = when (val d = client.discover(IMAGE_NAME)) {
            is HyperCycleResult.Success -> d.data
            is HyperCycleResult.Failure -> return HyperCycleResult.Failure(d.error, d.statusCode)
        }

        if (!waitForReady(aim.slot)) {
            return HyperCycleResult.Failure("TTS model not ready after timeout.")
        }

        val body = JSONObject().put("text", text).put("voice", voice)
        return when (val r = client.execute(aim.slot, "speak", body)) {
            is HyperCycleResult.Success -> {
                val b64 = r.data.optString("file")
                if (b64.isNullOrEmpty()) {
                    HyperCycleResult.Failure("No audio in response")
                } else {
                    // Android: Base64.decode(b64, Base64.DEFAULT)
                    // JVM:     java.util.Base64.getDecoder().decode(b64)
                    val wavBytes = Base64.decode(b64, Base64.DEFAULT)
                    HyperCycleResult.Success(wavBytes, r.statusCode)
                }
            }
            is HyperCycleResult.Failure -> {
                val hint = if (r.statusCode == 400) " (invalid voice — check listVoices())" else ""
                HyperCycleResult.Failure(r.error + hint, r.statusCode)
            }
        }
    }
}

suspend fun runTTSExample() {
    println("HyperCycle SDK ${HyperCycleClient.SDK_VERSION} — tortoise-tts example\n")

    val service = TortoiseTTSService()
    val text    = "You are now hearing this in my voice, courtesy of the HyperCycle network."
    val voice   = "daniel"

    println("Synthesizing: \"$text\"")
    println("Voice: $voice  |  Processing: 10s–1min...\n")

    when (val result = service.speak(text, voice)) {
        is HyperCycleResult.Success -> {
            val wavBytes = result.data
            // Android: write to cache file, play with MediaPlayer
            // val file = File(context.cacheDir, "output.wav")
            // file.writeBytes(wavBytes)
            // val player = MediaPlayer().apply { setDataSource(file.absolutePath); prepare(); start() }

            // JVM/CLI: write to disk
            java.io.File("output.wav").writeBytes(wavBytes)
            println("Audio saved to output.wav (${wavBytes.size} bytes)")
        }
        is HyperCycleResult.Failure -> {
            println("Error: ${result.error}")
        }
    }
}

fun main() = runBlocking { runTTSExample() }
