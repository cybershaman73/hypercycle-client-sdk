// examples/audio/yamnet-classifier/swift/example.swift
// HyperCycle SDK v0.2.1-beta — YAMNet Acoustic Classifier (Swift/iOS)
// See python/example.py in this folder for full waveform documentation.
// Set HYPERCYCLE_NODE_URL in your scheme environment variables.

import Foundation

let IMAGE_NAME = "yamnet-classifier"
let AIM_VER    = "0.1"

func generateTestWaveform(durationSec: Double = 10.0, sampleRate: Int = 16000) -> [Double] {
    let n = Int(Double(sampleRate) * durationSec)
    return (0..<n).map { i in
        let v = 0.4 * sin(2.0 * .pi * 440.0 * Double(i) / Double(sampleRate))
        return (v * 1_000_000).rounded() / 1_000_000
    }
}

@main
struct YAMNetExample {
    static func main() async {
        print("HyperCycle SDK \(HyperCycleClient.sdkVersion) — yamnet-classifier example\n")
        guard let client = try? HyperCycleClient() else {
            print("Config error: set HYPERCYCLE_NODE_URL"); exit(1)
        }
        guard await client.ping() else { print("Node unreachable."); exit(1) }

        let discovery = await client.discover(imageName: IMAGE_NAME)
        guard case .success(let aim) = discovery else {
            if case .failure(let e) = discovery { print("Discovery failed: \(e.message)") }; exit(1)
        }
        print("Found '\(IMAGE_NAME)' at slot \(aim.slot)\n")

        let health = await client.health(slot: aim.slot)
        guard case .success = health else {
            if case .failure(let e) = health { print("Health failed: \(e.message)") }; exit(1)
        }

        let waveform = generateTestWaveform()
        let formatter = ISO8601DateFormatter()
        let body: [String: Any] = [
            "device_id": "swift-yamnet-example",
            "timestamp": formatter.string(from: Date()),
            "sample_rate": 16000, "channels": 1, "duration_sec": 10.0,
            "masked_waveform": waveform, "doa_deg": 0.0,
            "geo": ["lat": 42.3265, "lon": -122.8756],
            "sdk_version": AIM_VER,
        ]

        print("Submitting inference...")
        let result = await client.execute(slot: aim.slot, endpoint: "infer", body: body)
        switch result {
        case .success(let data):
            print("Top event: \(data["top_event"] ?? "n/a")")
        case .failure(let err):
            print("Error: \(err.message)"); exit(1)
        }
    }
}
