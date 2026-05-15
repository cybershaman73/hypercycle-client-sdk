// HyperCycleClient.kt — HyperCycle AIM Client SDK (Kotlin/Android)
// Version: 0.2.0-beta
//
// Generic client for connecting to any public AIM on any HyperCycle node.
// Designed for Android app developers building on HyperCycle.
//
// Dependencies (add to build.gradle):
//   implementation("com.squareup.okhttp3:okhttp:4.12.0")
//   implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
//
// All methods are suspend functions — call from a coroutine or use
// lifecycleScope / viewModelScope. Never call from the main thread directly.
//
// The node URL is read from the HYPERCYCLE_NODE_URL system property,
// or passed directly. Do not hardcode node IPs in shipping apps.
//
// Quick start:
//   val client = HyperCycleClient(nodeUrl = BuildConfig.NODE_URL)
//   val aim    = client.discover("yamnet-classifier")
//   if (aim is HyperCycleResult.Success) {
//       val result = client.execute(aim.data.slot, "infer", body)
//   }

package ai.hypercycle.sdk

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

const val SDK_VERSION = "0.2.0-beta"

// ---------------------------------------------------------------------------
// Result type
// ---------------------------------------------------------------------------

sealed class HyperCycleResult<out T> {
    data class Success<T>(val data: T, val statusCode: Int = 200) : HyperCycleResult<T>()
    data class Failure(val error: String, val statusCode: Int? = null) : HyperCycleResult<Nothing>()
}

// ---------------------------------------------------------------------------
// Endpoint cost info
// ---------------------------------------------------------------------------

data class EndpointCost(
    val currency:      String,
    val fixed:         Double? = null,
    val estimatedCost: Double? = null,
    val min:           Double? = null,
    val max:           Double? = null,
)

// ---------------------------------------------------------------------------
// AIM info — from /info endpoint
// ---------------------------------------------------------------------------

/**
 * Metadata for a deployed AIM, sourced from the node's /info endpoint.
 *
 * The /info endpoint is the primary discovery mechanism for running AIMs.
 * [slot] and [imageName] are the key fields for app integration.
 */
data class AIMInfo(
    val slot:        Int,
    val port:        Int,
    val imageName:   String,
    val imageTag:    String,
    val status:      String,   // "running" = callable
    val labels:      Map<String, String>,
    val containerID: String,
    val costs:       List<EndpointCost>,
)

// ---------------------------------------------------------------------------
// Node info — from /info endpoint
// ---------------------------------------------------------------------------

/**
 * Full node info from the /info endpoint.
 *
 * This is the primary entry point for any app integrating with a HyperCycle
 * node. The [aims] list contains every deployed AIM with its metadata.
 */
data class NodeInfo(
    val status:              String,
    val name:                String,
    val address:             String,
    val nodeId:              String,
    val network:             String,
    val nodeVersion:         String,
    val platform:            String,
    val aims:                List<AIMInfo>,
    val acceptingCurrencies: List<String>,
    val raw:                 JSONObject,   // full /info response
)

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

class HyperCycleClient(
    nodeUrl: String? = null,
    timeoutSeconds: Long = 30L,
) {
    companion object {
        const val SDK_VERSION = ai.hypercycle.sdk.SDK_VERSION
    }

    private val JSON_TYPE = "application/json; charset=utf-8".toMediaType()

    private val baseUrl: String = run {
        val url = nodeUrl
            ?: System.getProperty("HYPERCYCLE_NODE_URL")
            ?: System.getenv("HYPERCYCLE_NODE_URL")
        requireNotNull(url) {
            "nodeUrl is required. Pass it directly or set HYPERCYCLE_NODE_URL."
        }
        url.trimEnd('/')
    }

    private val http = OkHttpClient.Builder()
        .connectTimeout(timeoutSeconds, TimeUnit.SECONDS)
        .readTimeout(timeoutSeconds, TimeUnit.SECONDS)
        .writeTimeout(timeoutSeconds, TimeUnit.SECONDS)
        .build()

    // -------------------------------------------------------------------------
    // Node info
    // -------------------------------------------------------------------------

    /**
     * GET /info — fetch full node info including all deployed AIMs.
     *
     * This is the primary discovery endpoint. Call this (or [discover]) before
     * calling [health] or [execute].
     *
     * Must be called from a coroutine (suspend function).
     */
    suspend fun info(): HyperCycleResult<NodeInfo> = withContext(Dispatchers.IO) {
        val raw = get("/info")
        if (raw is HyperCycleResult.Failure) return@withContext raw

        val data = (raw as HyperCycleResult.Success).data
        val aimBlock = data.optJSONObject("aim")
        val aimsJson = aimBlock?.optJSONArray("aims")
            ?: return@withContext HyperCycleResult.Failure("Invalid /info response: missing aim.aims")

        val aims = (0 until aimsJson.length()).map { parseAIM(aimsJson.getJSONObject(it)) }
        val currencies = data.optJSONArray("accepting_currencies")?.let { arr ->
            (0 until arr.length()).map { arr.getString(it) }
        } ?: emptyList()

        HyperCycleResult.Success(NodeInfo(
            status              = data.optString("status", ""),
            name                = data.optString("name", ""),
            address             = data.optString("address", ""),
            nodeId              = data.optString("node_id", ""),
            network             = data.optString("network", ""),
            nodeVersion         = data.optString("node_version", ""),
            platform            = data.optString("platform", ""),
            aims                = aims,
            acceptingCurrencies = currencies,
            raw                 = data,
        ))
    }

    // -------------------------------------------------------------------------
    // Discovery
    // -------------------------------------------------------------------------

    /**
     * Find a deployed, running AIM by Docker image name.
     *
     * @param imageName Docker image name, e.g. "yamnet-classifier"
     */
    suspend fun discover(imageName: String): HyperCycleResult<AIMInfo> {
        val infoResult = info()
        if (infoResult is HyperCycleResult.Failure) {
            return HyperCycleResult.Failure(
                "Failed to fetch node info: ${infoResult.error}", infoResult.statusCode
            )
        }
        val aims = (infoResult as HyperCycleResult.Success).data.aims
        val match = aims.find { it.imageName == imageName }
            ?: run {
                val available = aims.map { it.imageName }
                return HyperCycleResult.Failure(
                    "AIM '$imageName' not found on node. Available: $available"
                )
            }

        if (match.status != "running") {
            return HyperCycleResult.Failure(
                "AIM '$imageName' found at slot ${match.slot} but status is '${match.status}', not 'running'."
            )
        }
        return HyperCycleResult.Success(match)
    }

    /**
     * Return metadata for all AIMs on the node.
     *
     * @param runningOnly If true (default), return only AIMs with status "running".
     */
    suspend fun discoverAll(runningOnly: Boolean = true): HyperCycleResult<List<AIMInfo>> {
        val infoResult = info()
        if (infoResult is HyperCycleResult.Failure) {
            return HyperCycleResult.Failure(infoResult.error, infoResult.statusCode)
        }
        val aims = (infoResult as HyperCycleResult.Success).data.aims
        return HyperCycleResult.Success(
            if (runningOnly) aims.filter { it.status == "running" } else aims
        )
    }

    // -------------------------------------------------------------------------
    // Health
    // -------------------------------------------------------------------------

    /**
     * GET /aim/<slot>/health — check AIM liveness and model readiness.
     *
     * @param slot AIM slot number (from [discover] or [info])
     */
    suspend fun health(slot: Int): HyperCycleResult<JSONObject> =
        withContext(Dispatchers.IO) { get("/aim/$slot/health") }

    // -------------------------------------------------------------------------
    // Cost estimation
    // -------------------------------------------------------------------------

    /**
     * POST with cost_only header — returns estimated cost without executing.
     * No charge. No signature required.
     *
     * When an AIM has zero-cost endpoints (e.g. open beta), all values are 0.
     *
     * @param slot      AIM slot number
     * @param endpoint  Endpoint name, e.g. "infer"
     * @param body      Full request body (same shape as [execute])
     */
    suspend fun estimate(
        slot:     Int,
        endpoint: String,
        body:     JSONObject,
    ): HyperCycleResult<JSONObject> = withContext(Dispatchers.IO) {
        post(
            path         = "/aim/$slot/$endpoint",
            body         = body,
            extraHeaders = mapOf("cost_only" to "true"),
        )
    }

    // -------------------------------------------------------------------------
    // Execution
    // -------------------------------------------------------------------------

    /**
     * POST /aim/<slot>/<endpoint> — execute an AIM endpoint.
     *
     * The Node Manager authenticates, meters, and routes this to the AIM.
     * For zero-cost AIMs no wallet signature or balance is required.
     *
     * @param slot      AIM slot number
     * @param endpoint  Endpoint name, e.g. "infer"
     * @param body      Request body — will be JSON serialized
     */
    suspend fun execute(
        slot:     Int,
        endpoint: String,
        body:     JSONObject,
    ): HyperCycleResult<JSONObject> = withContext(Dispatchers.IO) {
        post("/aim/$slot/$endpoint", body)
    }

    // -------------------------------------------------------------------------
    // Convenience: ping
    // -------------------------------------------------------------------------

    /** Quick connectivity check. Returns true if the node is reachable. */
    suspend fun ping(): Boolean {
        val result = withContext(Dispatchers.IO) { get("/info") }
        return result is HyperCycleResult.Success
    }

    // -------------------------------------------------------------------------
    // Internal helpers
    // -------------------------------------------------------------------------

    private fun parseAIM(a: JSONObject): AIMInfo {
        val costs = mutableListOf<EndpointCost>()
        a.optJSONObject("uri_cost")?.let { uriCost ->
            for (endpointKey in uriCost.keys()) {
                uriCost.optJSONObject(endpointKey)?.let { currencies ->
                    for (currency in currencies.keys()) {
                        currencies.optJSONObject(currency)?.let { cd ->
                            costs.add(EndpointCost(
                                currency      = cd.optString("currency", currency),
                                fixed         = if (cd.has("fixed"))         cd.getDouble("fixed")         else null,
                                estimatedCost = if (cd.has("estimated_cost")) cd.getDouble("estimated_cost") else null,
                                min           = if (cd.has("min"))           cd.getDouble("min")           else null,
                                max           = if (cd.has("max"))           cd.getDouble("max")           else null,
                            ))
                        }
                    }
                }
            }
        }
        val labelsObj = a.optJSONObject("labels")
        val labels = labelsObj?.keys()?.asSequence()
            ?.associateWith { labelsObj.optString(it) } ?: emptyMap()

        return AIMInfo(
            slot        = a.optInt("slot", 0),
            port        = a.optInt("port", 0),
            imageName   = a.optString("image_name", ""),
            imageTag    = a.optString("image_tag", "latest"),
            status      = a.optString("status", "unknown"),
            labels      = labels,
            containerID = a.optString("container_id", ""),
            costs       = costs,
        )
    }

    private fun get(path: String): HyperCycleResult<JSONObject> {
        val request = Request.Builder().url("$baseUrl$path").get().build()
        return executeRequest(request)
    }

    private fun post(
        path:         String,
        body:         JSONObject,
        extraHeaders: Map<String, String> = emptyMap(),
    ): HyperCycleResult<JSONObject> {
        val requestBody = body.toString().toRequestBody(JSON_TYPE)
        val builder     = Request.Builder().url("$baseUrl$path").post(requestBody)
        extraHeaders.forEach { (k, v) -> builder.addHeader(k, v) }
        return executeRequest(builder.build())
    }

    private fun executeRequest(request: Request): HyperCycleResult<JSONObject> {
        return try {
            val response   = http.newCall(request).execute()
            val bodyString = response.body?.string()
                ?: return HyperCycleResult.Failure("Empty response", response.code)
            val json = try {
                JSONObject(bodyString)
            } catch (e: Exception) {
                return HyperCycleResult.Failure(
                    "Invalid JSON response: $bodyString", response.code
                )
            }
            if (!response.isSuccessful) {
                return HyperCycleResult.Failure(
                    "HTTP ${response.code} from ${request.url}: $bodyString",
                    response.code
                )
            }
            HyperCycleResult.Success(json, response.code)
        } catch (e: IOException) {
            HyperCycleResult.Failure("Request failed: ${e.message}")
        }
    }
}
