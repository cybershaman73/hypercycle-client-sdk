// examples/text/ollama-aim/kotlin/example.kt
// HyperCycle SDK v0.2.1-beta — Ollama LLM AIM (Kotlin/Android)
//
// AIM image: ollama-aim     Endpoint: POST /aim/<slot>/request
// Warmup: ~4 min after "running" — model downloads after container starts.
//
// Android usage: call ollamaService.chat() from viewModelScope.launch { }
// JVM/CLI:       fun main() = runBlocking { runExample() }

package ai.hypercycle.sdk.examples

import ai.hypercycle.sdk.*
import kotlinx.coroutines.*
import org.json.JSONObject

class OllamaAIMService(nodeUrl: String? = null) {

    companion object { private const val IMAGE_NAME = "ollama-aim" }

    private val client = HyperCycleClient(nodeUrl)

    /**
     * Poll /health until model_ready == true.
     * ollama-aim downloads its LLM AFTER entering "running" state (~4 min).
     * Must be called from a coroutine.
     */
    suspend fun waitForReady(slot: Int, maxWaitSec: Int = 300, pollSec: Long = 15): Boolean {
        println("Waiting for model (up to ${maxWaitSec / 60}min)...")
        var elapsed = 0
        while (elapsed < maxWaitSec) {
            val health = client.health(slot)
            if (health is HyperCycleResult.Success) {
                val ready = health.data.optBoolean("model_ready", false)
                val model = health.data.optString("model", "")
                println("  [${elapsed}s] model_ready=$ready  model=$model")
                if (ready) return true
            }
            delay(pollSec * 1000)
            elapsed += pollSec.toInt()
        }
        return false
    }

    /** Full flow: discover → wait for ready → execute. Returns response text. */
    suspend fun chat(prompt: String): HyperCycleResult<String> {
        val aim = when (val d = client.discover(IMAGE_NAME)) {
            is HyperCycleResult.Success -> d.data
            is HyperCycleResult.Failure -> return HyperCycleResult.Failure(d.error, d.statusCode)
        }

        if (!waitForReady(aim.slot)) {
            return HyperCycleResult.Failure("Model not ready after timeout.")
        }

        val body = JSONObject().put("prompt", prompt)
        return when (val r = client.execute(aim.slot, "request", body)) {
            is HyperCycleResult.Success -> {
                val text = r.data.optString("response").ifEmpty { r.data.optString("text") }
                HyperCycleResult.Success(text, r.statusCode)
            }
            is HyperCycleResult.Failure -> r
        }
    }
}

suspend fun runOllamaExample() {
    println("HyperCycle SDK ${HyperCycleClient.SDK_VERSION} — ollama-aim example\n")

    val service = OllamaAIMService()

    val prompts = listOf(
        "List Earth's atmosphere layers with altitude ranges, one sentence each.",
        """Return JSON only: {"layers": [{"name": "str", "min_km": 0, "max_km": 0}]}""",
    )

    for (prompt in prompts) {
        println("Prompt: ${prompt.take(60)}...")
        when (val result = service.chat(prompt)) {
            is HyperCycleResult.Success -> {
                val preview = result.data.let { if (it.length > 300) it.take(300) + "..." else it }
                println("Response: $preview\n")
            }
            is HyperCycleResult.Failure -> println("Error: ${result.error}\n")
        }
    }
}

fun main() = runBlocking { runOllamaExample() }
