// examples/speech/tortoise-tts/kotlin/example.kt
// HyperCycle SDK v0.3.0-beta — Tortoise TTS AIM (Kotlin/Android)
//
// NOTE: tortoise-tts has no /health endpoint.
// Warmup detection works by retrying /speak directly until the model responds.
// Model loads ~4 min after container enters "running" state.
//
// Input:  { "text": "...", "voice": "daniel" }  max 100 chars
// Output: { "file": "<base64 WAV>" } → decode → MediaPlayer / ExoPlayer
//
// Android: call ttsService.speak() from viewModelScope.launch { }
// JVM/CLI: fun main() = runBlocking { runExample() }

package ai.hypercycle.sdk.examples

import ai.hypercycle.sdk.*
import kotlinx.coroutines.*
import org.json.JSONObject
import java.util.Base64   // JVM — use android.util.Base64 on Android

class TortoiseTTSService(nodeUrl: String? = null) {

    companion object { private const val IMAGE_NAME = "tortoise-tts" }

    private val client = HyperCycleClient(nodeUrl)

    /**
     * Attempt /speak with retry backoff — handles the ~4 min warmup window.
     * tortoise-tts has no /health endpoint; a successful /speak is the only
     * signal that the model is loaded and ready.
     *
     * Must be called from a coroutine (suspend function).
     */
    suspend fun speakWithRetry(
        slot:         Int,
        text:         String,
        voice:        String,
        maxWaitSec:   Int  = 360,
        pollSec:      Long = 20,
    ): HyperCycleResult<JSONObject> {
        println("Attempting /speak (model warms ~4min, timeout ${maxWaitSec / 60}min)...")
        var elapsed = 0
        var attempt = 0
        val body = JSONObject().put("text", text).put("voice", voice)

        while (elapsed < maxWaitSec) {
            attempt++
            val result = client.execute(slot, "speak", body)

            when (result) {
                is HyperCycleResult.Success -> {
                    println("  [${elapsed}s] Success on attempt $attempt")
                    return result
                }
                is HyperCycleResult.Failure -> {
                    // 400 = bad request (voice/text) — do not retry
                    if (result.statusCode == 400) {
                        println("  [${elapsed}s] Bad request: ${result.error}")
                        return result
                    }
                    println("  [${elapsed}s] Not ready (${result.statusCode ?: "no response"}) — retrying in ${pollSec}s")
                    delay(pollSec * 1000)
                    elapsed += pollSec.toInt()
                }
            }
        }

        return HyperCycleResult.Failure("Timed out waiting for TTS model after ${maxWaitSec}s")
    }

    /**
     * Full flow: discover → speak with retry → return WAV bytes.
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
        println("Found '$IMAGE_NAME' at slot ${aim.slot}\n")

        return when (val r = speakWithRetry(aim.slot, text, voice)) {
            is HyperCycleResult.Success -> {
                val b64 = r.data.optString("file")
                if (b64.isNullOrEmpty()) {
                    HyperCycleResult.Failure("No audio in response")
                } else {
                    // JVM: Base64.getDecoder().decode(b64)
                    // Android: android.util.Base64.decode(b64, android.util.Base64.DEFAULT)
                    HyperCycleResult.Success(Base64.getDecoder().decode(b64), r.statusCode)
                }
            }
            is HyperCycleResult.Failure -> r
        }
    }
}

suspend fun runTTSExample() {
    println("HyperCycle SDK ${HyperCycleClient.SDK_VERSION} — tortoise-tts\n")

    val service = TortoiseTTSService()
    val text    = "You are now hearing this in my voice, courtesy of the HyperCycle network."
    val voice   = "daniel"

    println("Text : \"$text\"")
    println("Voice: $voice\n")

    when (val result = service.speak(text, voice)) {
        is HyperCycleResult.Success -> {
            val wavBytes = result.data
            // Android: write to cache, play with MediaPlayer
            // JVM/CLI: write to disk
            java.io.File("output.wav").writeBytes(wavBytes)
            println("\nAudio saved: output.wav (${wavBytes.size / 1024} KB)")
        }
        is HyperCycleResult.Failure -> {
            println("\nFailed: ${result.error}")
            println("Check: docker logs <container_id> --tail 50")
        }
    }
}

fun main() = runBlocking { runTTSExample() }
