// examples/speech/tortoise-tts/swift/example.swift
// HyperCycle SDK v0.2.1-beta — Tortoise TTS AIM (Swift/iOS)
//
// AIM image: tortoise-tts
// Endpoints: GET /list-voices, POST /speak
// Warmup: ~4 min after "running" — model loads after container starts.
// Hardware: NVIDIA GPU 8+ GB free VRAM required on the node.
//
// Input:  { "text": "...", "voice": "daniel" }  max 100 chars
// Output: { "file": "<base64 WAV>" }
//         → decode with Data(base64Encoded:) → play with AVAudioPlayer
//
// In a real iOS app, call ttsService.speak() from a Task in your ViewModel.
// Play audio with AVAudioPlayer after decoding the base64 WAV.

import Foundation
import AVFoundation   // for audio playback in a real app

// ---------------------------------------------------------------------------
// TortoiseTTSService — wraps HyperCycleClient for tortoise-tts
// ---------------------------------------------------------------------------

class TortoiseTTSService {

    private static let imageName = "tortoise-tts"

    private let client: HyperCycleClient

    init(nodeURL: String? = nil) throws {
        self.client = try HyperCycleClient(nodeURL: nodeURL)
    }

    // Poll until TTS model is loaded (~4 min after "running")
    func waitForReady(slot: Int, maxWaitSec: Int = 300, pollSec: UInt64 = 15) async -> Bool {
        print("Waiting for TTS model (up to \(maxWaitSec / 60)min)...")
        var elapsed = 0
        while elapsed < maxWaitSec {
            let health = await client.health(slot: slot)
            if case .success(let data) = health {
                let ready = data["model_ready"] as? Bool ?? false
                print("  [\(elapsed)s] model_ready=\(ready)")
                if ready { return true }
            }
            try? await Task.sleep(nanoseconds: pollSec * 1_000_000_000)
            elapsed += Int(pollSec)
        }
        return false
    }

    // Fetch available voice names from /list-voices
    func listVoices(slot: Int) async -> [String] {
        let result = await client.execute(slot: slot, endpoint: "list-voices", body: [:])
        if case .success(let data) = result {
            return data["available_voices"] as? [String] ?? []
        }
        return []
    }

    // Full flow: discover → wait → list-voices → speak.
    // Returns raw WAV Data on success.
    func speak(text: String, voice: String = "daniel") async -> Result<Data, HyperCycleError> {
        guard text.count <= 100 else {
            return .failure(HyperCycleError("Text exceeds 100 character limit (\(text.count) chars)"))
        }

        let discovery = await client.discover(imageName: Self.imageName)
        guard case .success(let aim) = discovery else {
            if case .failure(let err) = discovery { return .failure(err) }
            return .failure(HyperCycleError("Discovery failed"))
        }

        guard await waitForReady(slot: aim.slot) else {
            return .failure(HyperCycleError("TTS model not ready after timeout."))
        }

        let body: [String: Any] = ["text": text, "voice": voice]
        let result = await client.execute(slot: aim.slot, endpoint: "speak", body: body)

        switch result {
        case .success(let data):
            guard let b64 = data["file"] as? String,
                  let wavData = Data(base64Encoded: b64) else {
                return .failure(HyperCycleError("No audio in response or invalid base64"))
            }
            return .success(wavData)
        case .failure(let err):
            let hint = err.statusCode == 400 ? " (invalid voice — use listVoices() to check)" : ""
            return .failure(HyperCycleError(err.message + hint, statusCode: err.statusCode))
        }
    }
}

// ---------------------------------------------------------------------------
// Demo entry point
// ---------------------------------------------------------------------------

@main
struct TortoiseTTSExample {
    static func main() async {
        print("HyperCycle SDK \(HyperCycleClient.sdkVersion) — tortoise-tts example\n")

        let service: TortoiseTTSService
        do {
            service = try TortoiseTTSService()
        } catch let err as HyperCycleError {
            print("Config error: \(err.message)")
            print("Set HYPERCYCLE_NODE_URL in your scheme environment variables.")
            exit(1)
        } catch { print("Error: \(error)"); exit(1) }

        let text  = "You are now hearing this in my voice, courtesy of the HyperCycle network."
        let voice = "daniel"
        print("Synthesizing: \"\(text)\"")
        print("Voice: \(voice)")
        print("Processing: 10s–1min depending on GPU...\n")

        let result = await service.speak(text: text, voice: voice)
        switch result {
        case .success(let wavData):
            // In a real iOS app: play with AVAudioPlayer
            // let player = try AVAudioPlayer(data: wavData)
            // player.play()

            // Save to temp file for CLI demo
            let outputURL = URL(fileURLWithPath: "output.wav")
            do {
                try wavData.write(to: outputURL)
                print("Audio saved to output.wav (\(wavData.count.formatted()) bytes)")
            } catch {
                print("Could not write file: \(error)")
            }

        case .failure(let err):
            print("Error: \(err.message)")
            exit(1)
        }
    }
}
