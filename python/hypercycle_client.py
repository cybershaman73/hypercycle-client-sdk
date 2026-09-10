"""
hypercycle_client.py — HyperCycle AIM Client SDK (Python)
Version: 0.3.1-beta

Generic client for connecting to any public AIM on any HyperCycle node.
Designed for frontend app developers building on top of the HyperCycle
network — iOS, Android, and desktop applications.

All interaction flows through the Node Manager (NM) on port 8000.
AIM containers are never addressed directly.

    Your App
      └─► HyperCycleClient(node_url)
            └─► GET  /info                     → discover AIMs + endpoints + costs
            └─► GET  /aim/<slot>/health        → liveness check
            └─► POST /aim/<slot>/<endpoint>    → estimate (cost_only) or execute
                  └─► Node Manager routes to AIM container
                        └─► Result returned to your app

Quick start (4 steps):
    client = HyperCycleClient(node_url)
    aim    = client.discover("yamnet-classifier").data
    health = client.health(aim.slot)
    result = client.execute(aim.slot, "infer", body)

Environment variable:
    HYPERCYCLE_NODE_URL — set this instead of hardcoding a node URL.

Usage:
    from hypercycle_client import HyperCycleClient

    import os
    client = HyperCycleClient(os.environ["HYPERCYCLE_NODE_URL"])

Zero dependencies — stdlib only (Python 3.8+).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, TypeVar

import urllib.request
import urllib.error

SDK_VERSION = "0.3.1-beta"

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Result type — never raises, always check .ok before using .data
# ---------------------------------------------------------------------------

@dataclass
class HyperCycleResult(Generic[T]):
    """
    Typed result wrapper. Every SDK method returns one of these.

    Attributes
    ----------
    ok      : True if the call succeeded
    data    : Response payload on success, None on failure
    error   : Human-readable error message on failure, None on success
    status  : HTTP status code, or None if no HTTP response was received
    """
    ok: bool
    data: Optional[T] = None
    error: Optional[str] = None
    status: Optional[int] = None

    @classmethod
    def success(cls, data: T, status: int = 200) -> "HyperCycleResult[T]":
        return cls(ok=True, data=data, status=status)

    @classmethod
    def failure(cls, error: str, status: Optional[int] = None) -> "HyperCycleResult[T]":
        return cls(ok=False, error=error, status=status)


# ---------------------------------------------------------------------------
# Endpoint cost info — parsed from /info uri_cost or manifest.json costs
# ---------------------------------------------------------------------------

@dataclass
class EndpointCost:
    """
    Cost declaration for a single AIM endpoint and currency.

    Parsed from the uri_cost block in /info. Each key in uri_cost is an
    endpoint name (e.g. "/speak", "/infer", "default"), and each value
    is a dict of currency → cost data.

    When an AIM sets cost to zero (e.g. during open beta / hackathon),
    fixed will be 0 and estimated_cost will be 0.
    """
    endpoint: str                          # URI key from uri_cost, e.g. "/speak"
    currency: str
    fixed: Optional[float] = None          # fixed cost per call (if declared)
    estimated_cost: Optional[float] = None # estimated cost range mid-point
    min: Optional[float] = None
    max: Optional[float] = None


# ---------------------------------------------------------------------------
# AIM info — populated from /info endpoint
# ---------------------------------------------------------------------------

@dataclass
class AIMInfo:
    """
    Metadata for a discovered AIM, sourced from the node's /info endpoint.

    The /info endpoint is the primary discovery mechanism for running AIMs.
    It contains identity, slot/port, status, labels, endpoint names, and
    cost declarations.

    Attributes
    ----------
    slot         : AIM slot number (used in all /aim/<slot>/... requests)
    port         : Internal container port (informational; not called directly)
    image_name   : Docker image name used to deploy this AIM
    image_tag    : Docker image tag (e.g. "latest")
    status       : Container status — only "running" AIMs are callable
    labels       : Docker labels declared by the AIM (GPU requirements, etc.)
    container_id : Short Docker container ID
    endpoints    : List of endpoint URIs declared in uri_cost
                   e.g. ["/speak", "/list-voices"] or ["/infer"]
                   Empty if the AIM uses manifest.json costs instead.
    costs        : Per-endpoint, per-currency cost declarations from uri_cost
    """
    slot: int
    port: int
    image_name: str
    image_tag: str
    status: str
    labels: Dict[str, str]
    container_id: str
    endpoints: List[str] = field(default_factory=list)
    costs: List[EndpointCost] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Node info — top-level /info response
# ---------------------------------------------------------------------------

@dataclass
class NodeInfo:
    """
    Full node info from the /info endpoint.

    The /info endpoint is the primary entry point for any app integrating
    with a HyperCycle node. It exposes node identity, hardware, network,
    and — most importantly — the list of deployed AIMs with their metadata.

    Key fields for app developers
    ------------------------------
    aims          : List of AIMInfo objects — iterate to find the AIM you need
    node_id       : Unique node identifier on the network
    network       : "mainnet" or "testnet"
    accepting_currencies : Which currencies this node accepts for payment
    address       : Public address of this node on the network
    """
    status: str
    name: str
    address: str
    node_id: str
    network: str
    node_version: str
    platform: str
    aims: List[AIMInfo]
    accepting_currencies: List[str]
    raw: Dict  # Full raw /info response — available for advanced parsing


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class HyperCycleClient:
    """
    Generic HyperCycle node client for frontend app developers.

    Connects your app (iOS, Android, desktop) to any AIM deployed on a
    HyperCycle node via the Node Manager API.

    The recommended way to configure the node URL is via environment variable:

        export HYPERCYCLE_NODE_URL=http://<your-node-ip>:8000

    Then in code:

        import os
        from hypercycle_client import HyperCycleClient
        client = HyperCycleClient(os.environ["HYPERCYCLE_NODE_URL"])

    Or pass the URL directly (useful for testing):

        client = HyperCycleClient("http://<your-node-ip>:8000")

    Parameters
    ----------
    node_url : Base URL of the Node Manager, e.g. "http://192.168.1.10:8000"
               If omitted, reads HYPERCYCLE_NODE_URL from the environment.
    timeout  : Request timeout in seconds (default 30)
    """

    SDK_VERSION = SDK_VERSION

    def __init__(self, node_url: Optional[str] = None, timeout: int = 30):
        url = node_url or os.environ.get("HYPERCYCLE_NODE_URL")
        if not url:
            raise ValueError(
                "node_url is required. Pass it directly or set the "
                "HYPERCYCLE_NODE_URL environment variable."
            )
        self.node_url = url.rstrip("/")
        self.timeout = timeout

    # -----------------------------------------------------------------------
    # Node info — primary discovery endpoint
    # -----------------------------------------------------------------------

    def info(self) -> HyperCycleResult[NodeInfo]:
        """
        GET /info — fetch full node info including all deployed AIMs.

        This is the most important endpoint for app developers. The response
        includes every running AIM, its slot, port, cost declarations, and
        Docker labels. Parse this to discover what the node offers before
        calling any AIM endpoint.

        Returns a NodeInfo object with a structured .aims list, plus the
        full raw response in .raw for any fields not mapped by this SDK.
        """
        result = self._get("/info")
        if not result.ok:
            return HyperCycleResult.failure(result.error, result.status)

        raw = result.data
        aims_raw = raw.get("aim", {}).get("aims", [])
        aims = [self._parse_aim(a) for a in aims_raw]

        node = NodeInfo(
            status=raw.get("status", ""),
            name=raw.get("name", ""),
            address=raw.get("address", ""),
            node_id=raw.get("node_id", ""),
            network=raw.get("network", ""),
            node_version=raw.get("node_version", ""),
            platform=raw.get("platform", ""),
            aims=aims,
            accepting_currencies=raw.get("accepting_currencies", []),
            raw=raw,
        )
        return HyperCycleResult.success(node, status=result.status)

    # -----------------------------------------------------------------------
    # Discovery
    # -----------------------------------------------------------------------

    def discover(self, image_name: str) -> HyperCycleResult[AIMInfo]:
        """
        Find a deployed, running AIM by Docker image name.

        Calls /info and searches the aims list for a matching image_name
        with status == "running". Returns the AIM's slot, port, and cost info.

        Parameters
        ----------
        image_name : Docker image name to search for, e.g. "yamnet-classifier"

        Example
        -------
            result = client.discover("yamnet-classifier")
            if result.ok:
                slot = result.data.slot
        """
        info_result = self.info()
        if not info_result.ok:
            return HyperCycleResult.failure(
                f"Failed to fetch node info: {info_result.error}",
                status=info_result.status,
            )

        aims = info_result.data.aims
        matches = [a for a in aims if a.image_name == image_name]
        match = next((a for a in matches if a.status == "running"), None)
        if match is None and matches:
            match = matches[0]

        if match is None:
            available = [a.image_name for a in aims]
            return HyperCycleResult.failure(
                f"AIM '{image_name}' not found on node. "
                f"Available: {available}"
            )

        if match.status != "running":
            return HyperCycleResult.failure(
                f"AIM '{image_name}' found at slot {match.slot} "
                f"but status is '{match.status}', not 'running'."
            )

        return HyperCycleResult.success(match)

    def discover_all(self, running_only: bool = True) -> HyperCycleResult[List[AIMInfo]]:
        """
        Return metadata for all AIMs on the node.

        Parameters
        ----------
        running_only : If True (default), return only AIMs with status "running".
                       Set to False to include all AIMs regardless of status.
        """
        info_result = self.info()
        if not info_result.ok:
            return HyperCycleResult.failure(
                f"Failed to fetch node info: {info_result.error}",
                status=info_result.status,
            )
        aims = info_result.data.aims
        if running_only:
            aims = [a for a in aims if a.status == "running"]
        return HyperCycleResult.success(aims)

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    def health(self, slot: int) -> HyperCycleResult[Dict]:
        """
        GET /aim/<slot>/health — check AIM liveness and model readiness.

        Returns a dict with at minimum {"status": "ok"}.
        Some AIMs include a "model_ready" boolean.

        If the AIM has no /health endpoint, returns a failure with
        status 404. Callers should treat 404 as "no health endpoint"
        rather than "AIM is down" and fall through to probing the
        active endpoint directly.

        Parameters
        ----------
        slot : AIM slot number (from discover() or info())
        """
        result = self._get(f"/aim/{slot}/health")
        if not result.ok and result.status == 404:
            return HyperCycleResult.failure(
                f"AIM at slot {slot} has no /health endpoint — "
                "probe the active endpoint directly to confirm readiness.",
                status=404,
            )
        return result

    # -----------------------------------------------------------------------
    # Cost estimation
    # -----------------------------------------------------------------------

    def estimate(
        self,
        slot: int,
        endpoint: str,
        body: Dict,
    ) -> HyperCycleResult[Dict]:
        """
        POST /aim/<slot>/<endpoint> with cost_only header.

        Returns the estimated cost of an execution without performing it.
        No charge. No signature required.

        The response includes a "costs" list with currency, min, max, and
        estimated_cost fields. When an AIM has set zero cost (e.g. during
        beta/hackathon), all values will be 0.

        Parameters
        ----------
        slot     : AIM slot number
        endpoint : Endpoint path without leading slash, e.g. "infer"
        body     : Full request body (same shape as execute)
        """
        return self._post(
            f"/aim/{slot}/{endpoint}",
            body=body,
            headers={"cost_only": "true"},
        )

    # -----------------------------------------------------------------------
    # Execution
    # -----------------------------------------------------------------------

    def execute(
        self,
        slot: int,
        endpoint: str,
        body: Dict,
    ) -> HyperCycleResult[Dict]:
        """
        POST /aim/<slot>/<endpoint> — execute an AIM endpoint.

        The Node Manager authenticates, meters, and routes this request to
        the AIM container. The AIM executes and returns a result alongside
        actual usage costs.

        Parameters
        ----------
        slot     : AIM slot number
        endpoint : Endpoint path without leading slash, e.g. "infer"
        body     : Request body as a dict — will be JSON serialized

        Note: For AIMs with zero-cost endpoints (e.g. during open beta),
        no wallet signature or balance is required.
        """
        return self._post(f"/aim/{slot}/{endpoint}", body=body)

    # -----------------------------------------------------------------------
    # Convenience: ping
    # -----------------------------------------------------------------------

    def ping(self) -> bool:
        """
        Quick connectivity check. Returns True if the node is reachable.

        Useful for bootstrapping: call this before discover() to confirm
        you have a valid node URL.
        """
        result = self._get("/info")
        return result.ok

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_aim(a: Dict) -> AIMInfo:
        """Parse a raw AIM dict from /info into an AIMInfo dataclass."""
        uri_cost  = a.get("uri_cost", {})
        costs     = []
        endpoints = list(uri_cost.keys())   # preserve all declared endpoint names
        for endpoint_name, currencies in uri_cost.items():
            for currency_key, cost_data in currencies.items():
                if isinstance(cost_data, dict):
                    costs.append(EndpointCost(
                        endpoint=endpoint_name,
                        currency=cost_data.get("currency", currency_key),
                        fixed=cost_data.get("fixed"),
                        estimated_cost=cost_data.get("estimated_cost"),
                        min=cost_data.get("min"),
                        max=cost_data.get("max"),
                    ))
        return AIMInfo(
            slot=a.get("slot", 0),
            port=a.get("port", 0),
            image_name=a.get("image_name", ""),
            image_tag=a.get("image_tag", "latest"),
            status=a.get("status", "unknown"),
            labels=a.get("labels", {}),
            container_id=a.get("container_id", ""),
            endpoints=endpoints,
            costs=costs,
        )

    def _get(self, path: str) -> HyperCycleResult[Dict]:
        url = f"{self.node_url}{path}"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return HyperCycleResult.success(data, status=resp.status)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return HyperCycleResult.failure(
                f"HTTP {e.code} from {url}: {body}", status=e.code
            )
        except urllib.error.URLError as e:
            return HyperCycleResult.failure(f"Connection error to {url}: {e.reason}")
        except Exception as e:
            return HyperCycleResult.failure(f"Unexpected error: {e}")

    def _post(
        self,
        path: str,
        body: Dict,
        headers: Optional[Dict[str, str]] = None,
    ) -> HyperCycleResult[Dict]:
        url = f"{self.node_url}{path}"
        try:
            payload = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return HyperCycleResult.success(data, status=resp.status)
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            return HyperCycleResult.failure(
                f"HTTP {e.code} from {url}: {body_text}", status=e.code
            )
        except urllib.error.URLError as e:
            return HyperCycleResult.failure(f"Connection error to {url}: {e.reason}")
        except Exception as e:
            return HyperCycleResult.failure(f"Unexpected error: {e}")
