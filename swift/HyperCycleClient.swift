// HyperCycleClient.swift — HyperCycle AIM Client SDK (Swift/iOS)
// Version: 0.3.1-beta
//
// Generic client for connecting to any public AIM on any HyperCycle node.
// Designed for iOS (and macOS) app developers building on HyperCycle.
//
// Requires iOS 15+ / macOS 12+ (async/await + URLSession).
// Zero dependencies — Foundation only.
//
// The node URL is read from the HYPERCYCLE_NODE_URL environment variable,
// or passed directly. Do not hardcode node IPs in shipping apps.
//
// Quick start:
//   let client = HyperCycleClient()   // reads HYPERCYCLE_NODE_URL
//   let aim    = try await client.discover(imageName: "yamnet-classifier").get()
//   let health = try await client.health(slot: aim.slot).get()
//   let result = try await client.execute(slot: aim.slot, endpoint: "infer", body: body).get()

import Foundation

// ---------------------------------------------------------------------------
// Version
// ---------------------------------------------------------------------------

public let SDK_VERSION = "0.3.1-beta"

// ---------------------------------------------------------------------------
// Result type
// ---------------------------------------------------------------------------

public enum HyperCycleResult<T> {
    case success(T)
    case failure(HyperCycleError)
}

public struct HyperCycleError: Error {
    public let message: String
    public let statusCode: Int?

    init(_ message: String, statusCode: Int? = nil) {
        self.message    = message
        self.statusCode = statusCode
    }
}

// ---------------------------------------------------------------------------
// Endpoint cost info
// ---------------------------------------------------------------------------

public struct EndpointCost {
    public let currency:      String
    public let fixed:         Double?
    public let estimatedCost: Double?
    public let min:           Double?
    public let max:           Double?
}

// ---------------------------------------------------------------------------
// AIM info — from /info endpoint
// ---------------------------------------------------------------------------

/// Metadata for a deployed AIM, sourced from the node's /info endpoint.
///
/// The /info endpoint is the primary discovery mechanism for running AIMs.
/// `slot` and `imageName` are the key fields for app integration.
public struct AIMInfo {
    public let slot:        Int
    public let port:        Int
    public let imageName:   String
    public let imageTag:    String
    public let status:      String      // "running" = callable
    public let labels:      [String: String]
    public let containerID: String
    public let costs:       [EndpointCost]
}

// ---------------------------------------------------------------------------
// Node info — from /info endpoint
// ---------------------------------------------------------------------------

/// Full node info from the /info endpoint.
///
/// This is the primary entry point for any app integrating with a HyperCycle
/// node. The `aims` array contains every deployed AIM with its metadata.
public struct NodeInfo {
    public let status:               String
    public let name:                 String
    public let address:              String
    public let nodeID:               String
    public let network:              String
    public let nodeVersion:          String
    public let platform:             String
    public let aims:                 [AIMInfo]
    public let acceptingCurrencies:  [String]
    public let raw:                  [String: Any]   // full /info response
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

public class HyperCycleClient {

    public static let sdkVersion = SDK_VERSION

    private let nodeURL:         String
    private let timeoutInterval: TimeInterval
    private let session:         URLSession

    /// - Parameters:
    ///   - nodeURL: Base URL of the Node Manager, e.g. "http://192.168.1.10:8000"
    ///              If nil, reads HYPERCYCLE_NODE_URL from the environment.
    ///   - timeout: Request timeout in seconds (default 30)
    public init(nodeURL: String? = nil, timeout: TimeInterval = 30) throws {
        let url = nodeURL ?? ProcessInfo.processInfo.environment["HYPERCYCLE_NODE_URL"]
        guard let url = url, !url.isEmpty else {
            throw HyperCycleError(
                "nodeURL is required. Pass it directly or set HYPERCYCLE_NODE_URL."
            )
        }
        self.nodeURL         = url.hasSuffix("/") ? String(url.dropLast()) : url
        self.timeoutInterval = timeout
        let config           = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = timeout
        self.session         = URLSession(configuration: config)
    }

    // -------------------------------------------------------------------------
    // Node info
    // -------------------------------------------------------------------------

    /// GET /info — fetch full node info including all deployed AIMs.
    ///
    /// This is the primary discovery endpoint. Call this (or discover()) before
    /// calling health() or execute().
    public func info() async -> HyperCycleResult<NodeInfo> {
        let raw = await get(path: "/info")
        guard case .success(let data) = raw else {
            if case .failure(let err) = raw { return .failure(err) }
            return .failure(HyperCycleError("Failed to fetch /info"))
        }

        guard
            let aimBlock = data["aim"] as? [String: Any],
            let aimsRaw  = aimBlock["aims"] as? [[String: Any]]
        else {
            return .failure(HyperCycleError("Invalid /info response: missing aim.aims"))
        }

        let aims = aimsRaw.map { self.parseAIM($0) }

        return .success(NodeInfo(
            status:              data["status"]               as? String ?? "",
            name:                data["name"]                 as? String ?? "",
            address:             data["address"]              as? String ?? "",
            nodeID:              data["node_id"]              as? String ?? "",
            network:             data["network"]              as? String ?? "",
            nodeVersion:         data["node_version"]         as? String ?? "",
            platform:            data["platform"]             as? String ?? "",
            aims:                aims,
            acceptingCurrencies: data["accepting_currencies"] as? [String] ?? [],
            raw:                 data
        ))
    }

    // -------------------------------------------------------------------------
    // Discovery
    // -------------------------------------------------------------------------

    /// Find a deployed, running AIM by Docker image name.
    /// - Parameter imageName: Docker image name, e.g. "yamnet-classifier"
    public func discover(imageName: String) async -> HyperCycleResult<AIMInfo> {
        let infoResult = await info()
        guard case .success(let nodeInfo) = infoResult else {
            if case .failure(let err) = infoResult {
                return .failure(HyperCycleError(
                    "Failed to fetch node info: \(err.message)", statusCode: err.statusCode
                ))
            }
            return .failure(HyperCycleError("Failed to fetch node info"))
        }

        guard let match = nodeInfo.aims.first(where: { $0.imageName == imageName }) else {
            let available = nodeInfo.aims.map { $0.imageName }
            return .failure(HyperCycleError(
                "AIM '\(imageName)' not found on node. Available: \(available)"
            ))
        }

        guard match.status == "running" else {
            return .failure(HyperCycleError(
                "AIM '\(imageName)' found at slot \(match.slot) but status is '\(match.status)', not 'running'."
            ))
        }

        return .success(match)
    }

    /// Return metadata for all AIMs on the node.
    /// - Parameter runningOnly: If true (default), return only AIMs with status "running".
    public func discoverAll(runningOnly: Bool = true) async -> HyperCycleResult<[AIMInfo]> {
        let infoResult = await info()
        guard case .success(let nodeInfo) = infoResult else {
            if case .failure(let err) = infoResult { return .failure(err) }
            return .failure(HyperCycleError("Failed to fetch node info"))
        }
        let aims = runningOnly
            ? nodeInfo.aims.filter { $0.status == "running" }
            : nodeInfo.aims
        return .success(aims)
    }

    // -------------------------------------------------------------------------
    // Health
    // -------------------------------------------------------------------------

    /// GET /aim/<slot>/health — check AIM liveness and model readiness.
    /// - Parameter slot: AIM slot number (from discover() or info())
    public func health(slot: Int) async -> HyperCycleResult<[String: Any]> {
        return await get(path: "/aim/\(slot)/health")
    }

    // -------------------------------------------------------------------------
    // Cost estimation
    // -------------------------------------------------------------------------

    /// POST with cost_only header — returns estimated cost without executing.
    /// No charge. No signature required.
    ///
    /// When an AIM has zero-cost endpoints (e.g. open beta), all cost values
    /// will be 0 across all currencies.
    ///
    /// - Parameters:
    ///   - slot:     AIM slot number
    ///   - endpoint: Endpoint name, e.g. "infer"
    ///   - body:     Full request body (same shape as execute)
    public func estimate(
        slot:     Int,
        endpoint: String,
        body:     [String: Any]
    ) async -> HyperCycleResult<[String: Any]> {
        return await post(
            path:         "/aim/\(slot)/\(endpoint)",
            body:         body,
            extraHeaders: ["cost_only": "true"]
        )
    }

    // -------------------------------------------------------------------------
    // Execution
    // -------------------------------------------------------------------------

    /// POST /aim/<slot>/<endpoint> — execute an AIM endpoint.
    ///
    /// The Node Manager authenticates, meters, and routes this to the AIM.
    /// For zero-cost AIMs no wallet signature or balance is required.
    ///
    /// - Parameters:
    ///   - slot:     AIM slot number
    ///   - endpoint: Endpoint name, e.g. "infer"
    ///   - body:     Request body dict — will be JSON serialized
    public func execute(
        slot:     Int,
        endpoint: String,
        body:     [String: Any]
    ) async -> HyperCycleResult<[String: Any]> {
        return await post(path: "/aim/\(slot)/\(endpoint)", body: body)
    }

    // -------------------------------------------------------------------------
    // Convenience: ping
    // -------------------------------------------------------------------------

    /// Quick connectivity check. Returns true if the node is reachable.
    public func ping() async -> Bool {
        let result = await get(path: "/info")
        if case .success = result { return true }
        return false
    }

    // -------------------------------------------------------------------------
    // Internal helpers
    // -------------------------------------------------------------------------

    private func parseAIM(_ a: [String: Any]) -> AIMInfo {
        var costs: [EndpointCost] = []
        if let uriCost = a["uri_cost"] as? [String: Any] {
            for (_, endpointCosts) in uriCost {
                if let currencies = endpointCosts as? [String: Any] {
                    for (currency, costData) in currencies {
                        if let cd = costData as? [String: Any] {
                            costs.append(EndpointCost(
                                currency:      cd["currency"] as? String ?? currency,
                                fixed:         cd["fixed"] as? Double,
                                estimatedCost: cd["estimated_cost"] as? Double,
                                min:           cd["min"] as? Double,
                                max:           cd["max"] as? Double
                            ))
                        }
                    }
                }
            }
        }
        return AIMInfo(
            slot:        a["slot"]         as? Int    ?? 0,
            port:        a["port"]         as? Int    ?? 0,
            imageName:   a["image_name"]   as? String ?? "",
            imageTag:    a["image_tag"]    as? String ?? "latest",
            status:      a["status"]       as? String ?? "unknown",
            labels:      a["labels"]       as? [String: String] ?? [:],
            containerID: a["container_id"] as? String ?? "",
            costs:       costs
        )
    }

    private func get(path: String) async -> HyperCycleResult<[String: Any]> {
        guard let url = URL(string: "\(nodeURL)\(path)") else {
            return .failure(HyperCycleError("Invalid URL: \(nodeURL)\(path)"))
        }
        do {
            let (data, response) = try await session.data(from: url)
            let statusCode = (response as? HTTPURLResponse)?.statusCode
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .failure(HyperCycleError("Invalid JSON response", statusCode: statusCode))
            }
            if let code = statusCode, code >= 400 {
                return .failure(HyperCycleError("HTTP \(code) from \(url)", statusCode: code))
            }
            return .success(json)
        } catch {
            return .failure(HyperCycleError("Request failed: \(error.localizedDescription)"))
        }
    }

    private func post(
        path:         String,
        body:         [String: Any],
        extraHeaders: [String: String] = [:]
    ) async -> HyperCycleResult<[String: Any]> {
        guard let url = URL(string: "\(nodeURL)\(path)") else {
            return .failure(HyperCycleError("Invalid URL: \(nodeURL)\(path)"))
        }
        do {
            var request            = URLRequest(url: url)
            request.httpMethod     = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            extraHeaders.forEach { request.setValue($1, forHTTPHeaderField: $0) }
            request.httpBody       = try JSONSerialization.data(withJSONObject: body)
            let (data, response)   = try await session.data(for: request)
            let statusCode         = (response as? HTTPURLResponse)?.statusCode
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .failure(HyperCycleError("Invalid JSON response", statusCode: statusCode))
            }
            if let code = statusCode, code >= 400 {
                return .failure(HyperCycleError(
                    "HTTP \(code) from \(url): \(json)", statusCode: code
                ))
            }
            return .success(json)
        } catch {
            return .failure(HyperCycleError("Request failed: \(error.localizedDescription)"))
        }
    }
}
