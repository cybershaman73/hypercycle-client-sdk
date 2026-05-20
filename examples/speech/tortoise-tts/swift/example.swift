// examples/speech/tortoise-tts/swift/example.swift
// HyperCycle SDK v0.3.0-beta — Tortoise TTS AIM (Swift/iOS)
//
// NOTE: tortoise-tts has no /health endpoint.
// Warmup detection works by retrying /speak directly until the model responds.
// Model loads ~4 min after container enters "running" state.
//
// Input:  { "text": "...", "voice": "daniel" }  max 100 chars
// Output: { "file": "<base64 WAV>" } → decode → AVAudioPlayer

import Foundation

class TortoiseTTSService {

    private static let imageName = "tortoise-tts"
    private let client: HyperCycleClient

    init(nodeURL: String? = nil) throws {
        self.client = try HyperCycleClient(nodeURL: nodeURL)
    }

    /// Attempt /speak with retry backoff — handles warmup window.
    /// tortoise-tts has no /health endpoint; retry is the only signal.
    func speakWithRetry(
        slot:          Int,
        text:          String,
        voice:         String,
        maxWaitSec:    Int    = 360,
        pollSec:       UInt64 = 20
    ) async -> HyperCycleResult<[String: Any]> {
        print("Attempting /speak (model warms ~4min, timeout \(maxWaitSec/60)min)...")
        var elapsed = 0
        var attempt = 0
        let body: [String: Any] = ["text": text, "voice": voice]

        while elapsed < maxWaitSec {
            attempt += 1
            let result = await client.execute(slot: slot, endpoint: "speak", body: body)

            switch result {
            case .success:
                print("  [\(elapsed)s] Success on attempt \(attempt)")
                return result
            case .failure(let err):
                // 400 = bad request — do not retry
                if err.statusCode == 400 {
                    print("  [\(elapsed)s] Bad request: \(err.message)")
                    return result
                }
                print("  [\(elapsed)s] Not ready (\(err.statusCode ?? 0)) — retrying in \(pollSec)s")
                try? await Task.sleep(nanoseconds: pollSec * 1_000_000_000)
                elapsed += Int(pollSec)
            }
        }

        return .failure(HyperCycleError("Timed out waiting for TTS model after \(maxWaitSec)s"))
    }

    /// Full flow: discover → speak with retry → return WAV data.
    func speak(text: String, voice: String = "daniel") async -> Result<Data, HyperCycleError> {
        guard text.count <= 100 else {
            return .failure(HyperCycleError("Text exceeds 100 char limit (\(text.count) chars)"))
        }

        let discovery = await client.discover(imageName: Self.imageName)
        guard case .success(let aim) = discovery else {
            if case .failure(let err) = discovery { return .failure(err) }
            return .failure(HyperCycleError("Discovery failed"))
        }
        print("Found '\(Self.imageName)' at slot \(aim.slot)\n")

        let result = await speakWithRetry(slot: aim.slot, text: text, voice: voice)
        switch result {
        case .success(let data):
            guard let b64 = data["file"] as? String,
                  let wavData = Data(base64Encoded: b64) else {
                return .failure(HyperCycleError("No audio in response or invalid base64"))
            }
            return .success(wavData)
        case .failure(let err):
            return .failure(err)
        }
    }
}

@main
struct TortoiseTTSExample {
    static func main() async {
        print("HyperCycle SDK \(HyperCycleClient.sdkVersion) — tortoise-tts\n")

        let service: TortoiseTTSService
        do {
            service = try TortoiseTTSService()
        } catch let err as HyperCycleError {
            print("Config error: \(err.message)"); exit(1)
        } catch { print("Error: \(error)"); exit(1) }

        let text  = "You are now hearing this in my voice, courtesy of the HyperCycle network."
        let voice = "daniel"
        print("Text : \"\(text)\"")
        print("Voice: \(voice)\n")

        switch await service.speak(text: text, voice: voice) {
        case .success(let wavData):
            // In a real iOS app: AVAudioPlayer(data: wavData)
            let outputURL = URL(fileURLWithPath: "output.wav")
            try? wavData.write(to: outputURL)
            print("\nAudio saved: output.wav (\(wavData.count / 1024) KB)")
        case .failure(let err):
            print("\nFailed: \(err.message)")
            print("Check: docker logs <container_id> --tail 50")
            exit(1)
        }
    }
}
