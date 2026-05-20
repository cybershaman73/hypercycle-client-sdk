// examples/text/ollama-aim/swift/example.swift
// HyperCycle SDK v0.2.1-beta — Ollama LLM AIM (Swift/iOS)
//
// AIM image: ollama-aim     Endpoint: POST /aim/<slot>/request
// Warmup: ~4 min after "running" — model downloads after container starts.
//
// In a real iOS app, call ollamaService.chat() from a Task inside your ViewModel.
// Never call directly from the main thread — all network calls are async.
//
// Usage: Set HYPERCYCLE_NODE_URL in Xcode scheme environment variables.

import Foundation

// ---------------------------------------------------------------------------
// OllamaAIMService — wraps HyperCycleClient for the ollama-aim
// ---------------------------------------------------------------------------

class OllamaAIMService {

    private static let imageName = "ollama-aim"

    private let client: HyperCycleClient

    init(nodeURL: String? = nil) throws {
        self.client = try HyperCycleClient(nodeURL: nodeURL)
    }

    // Poll /health until model_ready is true.
    // ollama-aim downloads its model AFTER entering "running" state (~4 min).
    func waitForReady(slot: Int, maxWaitSec: Int = 300, pollSec: UInt64 = 15) async -> Bool {
        print("Waiting for model (up to \(maxWaitSec / 60)min)...")
        var elapsed = 0
        while elapsed < maxWaitSec {
            let health = await client.health(slot: slot)
            if case .success(let data) = health {
                let ready     = data["model_ready"] as? Bool ?? false
                let modelName = data["model"] as? String ?? ""
                print("  [\(elapsed)s] model_ready=\(ready)  model=\(modelName)")
                if ready { return true }
            }
            try? await Task.sleep(nanoseconds: pollSec * 1_000_000_000)
            elapsed += Int(pollSec)
        }
        return false
    }

    // Full flow: discover → wait for ready → execute.
    func chat(prompt: String) async -> Result<String, HyperCycleError> {
        let discovery = await client.discover(imageName: Self.imageName)
        guard case .success(let aim) = discovery else {
            if case .failure(let err) = discovery { return .failure(err) }
            return .failure(HyperCycleError("Discovery failed"))
        }

        guard await waitForReady(slot: aim.slot) else {
            return .failure(HyperCycleError("Model not ready after timeout."))
        }

        let body: [String: Any] = ["prompt": prompt]
        let result = await client.execute(slot: aim.slot, endpoint: "request", body: body)

        switch result {
        case .success(let data):
            let text = (data["response"] as? String) ?? (data["text"] as? String) ?? ""
            return .success(text)
        case .failure(let err):
            return .failure(err)
        }
    }
}

// ---------------------------------------------------------------------------
// Demo entry point
// ---------------------------------------------------------------------------

@main
struct OllamaExample {
    static func main() async {
        print("HyperCycle SDK \(HyperCycleClient.sdkVersion) — ollama-aim example\n")

        let service: OllamaAIMService
        do {
            service = try OllamaAIMService()
        } catch let err as HyperCycleError {
            print("Config error: \(err.message)")
            print("Set HYPERCYCLE_NODE_URL in your scheme environment variables.")
            exit(1)
        } catch {
            print("Error: \(error)"); exit(1)
        }

        let prompts = [
            "List Earth's atmosphere layers with altitude ranges, one sentence each.",
            "Return JSON only: {\"layers\": [{\"name\": \"str\", \"min_km\": 0, \"max_km\": 0}]}",
        ]

        for prompt in prompts {
            print("Prompt: \(prompt.prefix(60))...")
            let result = await service.chat(prompt: prompt)
            switch result {
            case .success(let text):
                let preview = text.count > 300 ? String(text.prefix(300)) + "..." : text
                print("Response: \(preview)\n")
            case .failure(let err):
                print("Error: \(err.message)\n")
            }
        }
    }
}
