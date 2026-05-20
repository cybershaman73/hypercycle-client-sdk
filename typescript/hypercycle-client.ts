/**
 * hypercycle-client.ts — HyperCycle AIM Client SDK (TypeScript)
 * Version: 0.3.1-beta
 *
 * Generic client for connecting to any public AIM on any HyperCycle node.
 * Designed for frontend app developers building on top of the HyperCycle
 * network — iOS (React Native), Android (React Native), and desktop (Electron/web).
 *
 * Zero dependencies — native fetch API (Node 18+, all modern browsers).
 *
 * All interaction flows through the Node Manager (NM) on port 8000.
 * AIM containers are never addressed directly.
 *
 * Quick start:
 *   const client = new HyperCycleClient(process.env.HYPERCYCLE_NODE_URL!);
 *   const aim    = (await client.discover("yamnet-classifier")).data!;
 *   const health = await client.health(aim.slot);
 *   const result = await client.execute(aim.slot, "infer", body);
 */

export const SDK_VERSION = "0.3.1-beta";

// ---------------------------------------------------------------------------
// Result type
// ---------------------------------------------------------------------------

export type HyperCycleResult<T> =
  | { ok: true;  data: T;     error: null;   status: number }
  | { ok: false; data: null;  error: string; status: number | null };

function success<T>(data: T, status: number = 200): HyperCycleResult<T> {
  return { ok: true, data, error: null, status };
}

function failure<T>(error: string, status: number | null = null): HyperCycleResult<T> {
  return { ok: false, data: null, error, status };
}

// ---------------------------------------------------------------------------
// Endpoint cost info — from /info uri_cost or manifest.json costs
// ---------------------------------------------------------------------------

export interface EndpointCost {
  currency:       string;
  fixed?:         number;   // fixed cost per call (if declared)
  estimated_cost?: number;  // mid-point estimate
  min?:           number;
  max?:           number;
}

// ---------------------------------------------------------------------------
// AIM info — populated from /info endpoint
// ---------------------------------------------------------------------------

/**
 * Metadata for a deployed AIM, sourced from the node's /info endpoint.
 *
 * The /info endpoint is the primary discovery mechanism for running AIMs.
 * slot and image_name are the key fields for app integration.
 */
export interface AIMInfo {
  slot:         number;
  port:         number;
  image_name:   string;
  image_tag:    string;
  status:       string;        // "running" = callable; other values = not ready
  labels:       Record<string, string>;
  container_id: string;
  costs:        EndpointCost[]; // from uri_cost block in /info
}

// ---------------------------------------------------------------------------
// Node info — top-level /info response
// ---------------------------------------------------------------------------

/**
 * Full node info from the /info endpoint.
 *
 * This is the primary entry point for any app integrating with a HyperCycle
 * node. The aims array contains every deployed AIM with its metadata.
 */
export interface NodeInfo {
  status:               string;
  name:                 string;
  address:              string;
  node_id:              string;
  network:              string;
  node_version:         string;
  platform:             string;
  aims:                 AIMInfo[];
  accepting_currencies: string[];
  raw:                  Record<string, unknown>; // full /info response
}

// ---------------------------------------------------------------------------
// Raw /info shape (internal)
// ---------------------------------------------------------------------------

interface RawAIM {
  slot:         number;
  port:         number;
  image_name:   string;
  image_tag?:   string;
  status:       string;
  labels?:      Record<string, string>;
  container_id?: string;
  uri_cost?:    Record<string, Record<string, Record<string, unknown>>>;
}

interface RawNodeInfo {
  status?:               string;
  name?:                 string;
  address?:              string;
  node_id?:              string;
  network?:              string;
  node_version?:         string;
  platform?:             string;
  accepting_currencies?: string[];
  aim?: { aims?: RawAIM[] };
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class HyperCycleClient {
  static readonly SDK_VERSION = SDK_VERSION;

  private readonly nodeUrl: string;
  private readonly timeoutMs: number;

  /**
   * @param nodeUrl   Base URL of the Node Manager, e.g. "http://192.168.1.10:8000"
   *                  If omitted, reads HYPERCYCLE_NODE_URL from the environment.
   * @param timeoutMs Request timeout in milliseconds (default 30000)
   */
  constructor(nodeUrl?: string, timeoutMs: number = 30_000) {
    const url =
      nodeUrl ??
      (typeof process !== "undefined" ? process.env?.HYPERCYCLE_NODE_URL : undefined);
    if (!url) {
      throw new Error(
        "nodeUrl is required. Pass it directly or set HYPERCYCLE_NODE_URL."
      );
    }
    this.nodeUrl  = url.replace(/\/$/, "");
    this.timeoutMs = timeoutMs;
  }

  // -------------------------------------------------------------------------
  // Node info
  // -------------------------------------------------------------------------

  /**
   * GET /info — fetch full node info including all deployed AIMs.
   *
   * This is the primary discovery endpoint. It returns every AIM deployed on
   * the node with slot numbers, costs, and status. Always call this (or
   * discover()) before calling health() or execute().
   */
  async info(): Promise<HyperCycleResult<NodeInfo>> {
    const raw = await this.get<RawNodeInfo>("/info");
    if (!raw.ok) return failure(raw.error, raw.status);

    const data = raw.data;
    const aims = (data.aim?.aims ?? []).map(this.parseAIM);

    return success<NodeInfo>({
      status:               data.status              ?? "",
      name:                 data.name                ?? "",
      address:              data.address             ?? "",
      node_id:              data.node_id             ?? "",
      network:              data.network             ?? "",
      node_version:         data.node_version        ?? "",
      platform:             data.platform            ?? "",
      aims,
      accepting_currencies: data.accepting_currencies ?? [],
      raw:                  data as Record<string, unknown>,
    });
  }

  // -------------------------------------------------------------------------
  // Discovery
  // -------------------------------------------------------------------------

  /**
   * Find a deployed, running AIM by Docker image name.
   *
   * @param imageName Docker image name, e.g. "yamnet-classifier"
   */
  async discover(imageName: string): Promise<HyperCycleResult<AIMInfo>> {
    const infoResult = await this.info();
    if (!infoResult.ok) {
      return failure(`Failed to fetch node info: ${infoResult.error}`, infoResult.status);
    }

    const aims = infoResult.data.aims;
    const match = aims.find(a => a.image_name === imageName);

    if (!match) {
      const available = aims.map(a => a.image_name);
      return failure(
        `AIM '${imageName}' not found on node. Available: [${available.join(", ")}]`
      );
    }

    if (match.status !== "running") {
      return failure(
        `AIM '${imageName}' found at slot ${match.slot} but status is '${match.status}', not 'running'.`
      );
    }

    return success<AIMInfo>(match);
  }

  /**
   * Return metadata for all AIMs on the node.
   *
   * @param runningOnly If true (default), return only AIMs with status "running".
   */
  async discoverAll(runningOnly = true): Promise<HyperCycleResult<AIMInfo[]>> {
    const infoResult = await this.info();
    if (!infoResult.ok) {
      return failure(`Failed to fetch node info: ${infoResult.error}`, infoResult.status);
    }
    const aims = runningOnly
      ? infoResult.data.aims.filter(a => a.status === "running")
      : infoResult.data.aims;
    return success(aims);
  }

  // -------------------------------------------------------------------------
  // Health
  // -------------------------------------------------------------------------

  /**
   * GET /aim/<slot>/health — check AIM liveness and model readiness.
   *
   * @param slot AIM slot number (from discover() or info())
   */
  async health(slot: number): Promise<HyperCycleResult<Record<string, unknown>>> {
    return this.get(`/aim/${slot}/health`);
  }

  // -------------------------------------------------------------------------
  // Cost estimation
  // -------------------------------------------------------------------------

  /**
   * POST /aim/<slot>/<endpoint> with cost_only header.
   *
   * Returns the estimated cost without performing execution.
   * No charge. No signature required.
   *
   * When an AIM has zero-cost endpoints (e.g. open beta), all cost values
   * will be 0 across all currencies.
   *
   * @param slot      AIM slot number
   * @param endpoint  Endpoint name without leading slash, e.g. "infer"
   * @param body      Full request body (same shape as execute)
   */
  async estimate(
    slot: number,
    endpoint: string,
    body: Record<string, unknown>,
  ): Promise<HyperCycleResult<Record<string, unknown>>> {
    return this.post(`/aim/${slot}/${endpoint}`, body, { cost_only: "true" });
  }

  // -------------------------------------------------------------------------
  // Execution
  // -------------------------------------------------------------------------

  /**
   * POST /aim/<slot>/<endpoint> — execute an AIM endpoint.
   *
   * The Node Manager authenticates, meters, and routes this to the AIM
   * container. For zero-cost AIMs no wallet signature or balance is required.
   *
   * @param slot      AIM slot number
   * @param endpoint  Endpoint name without leading slash, e.g. "infer"
   * @param body      Request body — will be JSON serialized
   */
  async execute<T = Record<string, unknown>>(
    slot: number,
    endpoint: string,
    body: Record<string, unknown>,
  ): Promise<HyperCycleResult<T>> {
    return this.post<T>(`/aim/${slot}/${endpoint}`, body);
  }

  // -------------------------------------------------------------------------
  // Convenience: ping
  // -------------------------------------------------------------------------

  /**
   * Quick connectivity check. Returns true if the node is reachable.
   */
  async ping(): Promise<boolean> {
    const result = await this.get("/info");
    return result.ok;
  }

  // -------------------------------------------------------------------------
  // Internal helpers
  // -------------------------------------------------------------------------

  private parseAIM(a: RawAIM): AIMInfo {
    const costs: EndpointCost[] = [];
    const uriCost = a.uri_cost ?? {};
    for (const _endpoint of Object.keys(uriCost)) {
      for (const [_currency, costData] of Object.entries(uriCost[_endpoint] ?? {})) {
        if (typeof costData === "object" && costData !== null) {
          const cd = costData as Record<string, unknown>;
          costs.push({
            currency:        (cd["currency"] as string) ?? _currency,
            fixed:           cd["fixed"] as number | undefined,
            estimated_cost:  cd["estimated_cost"] as number | undefined,
            min:             cd["min"] as number | undefined,
            max:             cd["max"] as number | undefined,
          });
        }
      }
    }
    return {
      slot:         a.slot,
      port:         a.port,
      image_name:   a.image_name,
      image_tag:    a.image_tag    ?? "latest",
      status:       a.status,
      labels:       a.labels       ?? {},
      container_id: a.container_id ?? "",
      costs,
    };
  }

  private async get<T>(path: string): Promise<HyperCycleResult<T>> {
    const url = `${this.nodeUrl}${path}`;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      const resp = await fetch(url, { method: "GET", signal: controller.signal });
      clearTimeout(timer);
      const data = await resp.json();
      if (!resp.ok) {
        return failure(`HTTP ${resp.status} from ${url}: ${JSON.stringify(data)}`, resp.status);
      }
      return success<T>(data as T, resp.status);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      return failure(`Request failed: ${msg}`);
    }
  }

  private async post<T>(
    path: string,
    body: Record<string, unknown>,
    extraHeaders: Record<string, string> = {},
  ): Promise<HyperCycleResult<T>> {
    const url = `${this.nodeUrl}${path}`;
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...extraHeaders },
        body:    JSON.stringify(body),
        signal:  controller.signal,
      });
      clearTimeout(timer);
      const data = await resp.json();
      if (!resp.ok) {
        return failure(`HTTP ${resp.status} from ${url}: ${JSON.stringify(data)}`, resp.status);
      }
      return success<T>(data as T, resp.status);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      return failure(`Request failed: ${msg}`);
    }
  }
}
