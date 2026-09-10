#!/usr/bin/env python3
"""Dry-run or perform one wallet-signed HyperCycle AIM call."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from typing import Any, Mapping

from hypercycle_pay import PayingClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", required=True, type=int)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--body-json", required=True)
    parser.add_argument("--protocol", choices=(1, 2), default=1, type=int)
    parser.add_argument("--currency", help="accepted currency symbol from /info")
    parser.add_argument("--session-duration", default=21600, type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    mode.add_argument(
        "--session-delegate",
        action="store_true",
        help="print the wallet-to-delegate session flow without network calls",
    )
    return parser.parse_args()


def has_positive_usage(value_used: Mapping[str, Any]) -> bool:
    for value in value_used.values():
        amount = value.get("used", 0) if isinstance(value, dict) else value
        if (
            isinstance(amount, (int, float))
            and not isinstance(amount, bool)
            and amount > 0
        ):
            return True
    return False


def main() -> int:
    args = parse_args()
    try:
        body = json.loads(args.body_json)
    except json.JSONDecodeError as exc:
        print(f"Invalid --body-json: {exc}", file=sys.stderr)
        return 2
    if not isinstance(body, dict):
        print("--body-json must decode to a JSON object", file=sys.stderr)
        return 2

    try:
        node_url = (
            None
            if args.live
            else os.environ.get("HYPERCYCLE_NODE_URL", "http://dry-run.invalid")
        )
        client = PayingClient(node_url=node_url, protocol=args.protocol)
    except (ImportError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.session_delegate:
        if args.session_duration <= 0 or args.session_duration > 86400:
            print("--session-duration must be between 1 and 86400", file=sys.stderr)
            return 2
        delegate = "<delegate address>"
        session_key = "<session key from GET /create_session>"
        client.driver = "<from /info>"
        client.currency_type = "<from /info>"
        headers = client._paid_headers("<nonce from GET /nonce>")
        headers["tx-session-key"] = session_key
        headers["tx-signature"] = "<delegate signature; redacted>"
        query = urllib.parse.urlencode(
            {
                "user_address": client.sender,
                "duration": args.session_duration,
            }
        )
        preview = {
            "mode": "session-delegate-dry-run",
            "steps": [
                {
                    "method": "GET",
                    "path": f"/create_session?{query}",
                },
                {
                    "method": "POST",
                    "path": "/create_session",
                    "body": {
                        "signer_address": client.sender,
                        "public_key": delegate,
                        "session_key": session_key,
                        "signature": (
                            "<wallet signature over "
                            "'<delegate address>_<session key>'; redacted>"
                        ),
                    },
                },
                {
                    "method": "POST",
                    "path": f"/aim/{args.slot}/{args.endpoint.lstrip('/')}",
                    "headers": headers,
                    "body": body,
                },
            ],
        }
        print(json.dumps(preview, indent=2, sort_keys=True))
        return 0

    configured = client.configure_from_node(args.currency)
    if not configured.ok:
        if args.live:
            print(configured.error, file=sys.stderr)
            return 1
        print(configured.error, file=sys.stderr)
        client.driver = "<from /info>"
        client.currency_type = "<from /info>"

    if args.dry_run:
        nonce_placeholder = "<nonce from GET /nonce>"
        headers = client._paid_headers(nonce_placeholder, protocol=args.protocol)
        headers["tx-signature"] = "<redacted>"
        preview = {
            "method": "POST",
            "path": f"/aim/{args.slot}/{args.endpoint.lstrip('/')}",
            "headers": headers,
            "body": body,
        }
        print(json.dumps(preview, indent=2, sort_keys=True))
        return 0

    result = client.execute_paid(
        args.slot, args.endpoint, body, protocol=args.protocol
    )
    output = {"value_used": result.value_used, "next_nonce": result.next_nonce}
    print(json.dumps(output, sort_keys=True))
    if not result.ok:
        print(result.error or "Paid call failed", file=sys.stderr)
        return 1
    return 0 if has_positive_usage(result.value_used) else 1


if __name__ == "__main__":
    raise SystemExit(main())
