"""Payment support for the HyperCycle Python client.

This module implements the wallet- and session-signed request contracts
verified by Node Manager 0.5.4.

``eth-account`` is optional for the base SDK and required only when creating a
:class:`PayingClient`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from hypercycle_client import HyperCycleClient, HyperCycleResult

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except ImportError:  # pragma: no cover - exercised by monkeypatch in tests
    Account = None
    encode_defunct = None


JsonObject = Dict[str, Any]


@dataclass
class PaidResult:
    """Result and accounting metadata returned by a paid AIM call."""

    ok: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    status: Optional[int] = None
    value_used: Dict[str, Any] = field(default_factory=dict)
    next_nonce: Optional[str] = None
    verified_input_tx: Optional[bool] = None
    verification_message: Optional[str] = None
    latest_valid_tx: List[Any] = field(default_factory=list)
    registered_deposit_tx: Optional[str] = None


class PayingClient(HyperCycleClient):
    """HyperCycle client that signs and submits paid AIM requests."""

    def __init__(
        self,
        node_url: Optional[str] = None,
        *,
        private_key: Optional[Union[str, bytes]] = None,
        timeout: int = 30,
        driver: Optional[str] = None,
        currency_type: Optional[str] = None,
        protocol: int = 1,
    ):
        if Account is None or encode_defunct is None:
            raise ImportError(
                "PayingClient requires the optional dependency 'eth-account'. "
                "Install it with: python -m pip install eth-account"
            )
        key = private_key or os.environ.get("HYPERCYCLE_WALLET_KEY")
        if not key:
            raise ValueError(
                "private_key is required. Pass it directly or set "
                "HYPERCYCLE_WALLET_KEY."
            )
        if protocol not in (1, 2):
            raise ValueError("protocol must be 1 or 2")

        super().__init__(node_url=node_url, timeout=timeout)
        try:
            account = Account.from_key(key)
        except Exception:
            raise ValueError(
                "The wallet private key is not valid"
            ) from None

        self._private_key = key
        self.sender = account.address
        self.signer_address = account.address
        self._session_key: Optional[str] = None
        self.driver = driver
        self.currency_type = currency_type
        self.currency_symbol: Optional[str] = None
        self.currency_decimals: Optional[int] = None
        self.node_hotwallet: Optional[str] = None
        self._driver_explicit = driver is not None
        self._currency_type_explicit = currency_type is not None
        self.protocol = protocol
        self._next_nonce: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(node_url={self.node_url!r}, "
            f"sender={self.sender!r}, driver={self.driver!r}, "
            f"currency_type={self.currency_type!r}, protocol={self.protocol!r})"
        )

    def configure_from_node(
        self, currency: Optional[str] = None
    ) -> HyperCycleResult[JsonObject]:
        """Configure payment headers from the node's advertised payment engine."""
        info_result = self.info()
        if not info_result.ok:
            return HyperCycleResult.failure(
                f"Failed to fetch node payment configuration: {info_result.error}",
                status=info_result.status,
            )

        node_info = info_result.data
        raw = node_info.raw if node_info is not None else None
        if not isinstance(raw, dict):
            return HyperCycleResult.failure("Node /info response has no raw metadata")
        tm = raw.get("tm")
        if not isinstance(tm, dict):
            return HyperCycleResult.failure(
                "Node /info response is missing payment metadata 'tm'"
            )
        accepting = raw.get("accepting_currencies")
        if not isinstance(accepting, list) or not all(
            isinstance(item, str) and item for item in accepting
        ):
            return HyperCycleResult.failure(
                "Node /info response has invalid 'accepting_currencies'"
            )

        if currency is not None:
            if currency not in accepting:
                return HyperCycleResult.failure(
                    f"Currency {currency!r} is not accepted by this node; "
                    f"accepted currencies: {accepting}"
                )
            symbol = currency
        elif len(accepting) == 1:
            symbol = accepting[0]
        elif not accepting:
            return HyperCycleResult.failure(
                "Node accepts no currencies; specify a usable node"
            )
        else:
            return HyperCycleResult.failure(
                "Node accepts multiple currencies; specify one explicitly: "
                + ", ".join(accepting)
            )

        advertised_driver = tm.get("driver")
        if not self._driver_explicit and (
            not isinstance(advertised_driver, str) or not advertised_driver
        ):
            return HyperCycleResult.failure(
                "Node /info payment metadata is missing a valid 'tm.driver'"
            )
        effective_driver = (
            self.driver if self._driver_explicit else advertised_driver
        )

        currencies = tm.get("currencies")
        currency_metadata = (
            currencies.get(symbol) if isinstance(currencies, dict) else None
        )
        if not isinstance(currency_metadata, dict):
            return HyperCycleResult.failure(
                f"Node /info payment metadata is missing currency {symbol!r}"
            )

        decimals = currency_metadata.get("decimals")
        if not isinstance(decimals, int) or isinstance(decimals, bool) or decimals < 0:
            return HyperCycleResult.failure(
                f"Node /info currency {symbol!r} has invalid 'decimals'"
            )
        hotwallet = tm.get("address")
        if not isinstance(hotwallet, str) or not hotwallet:
            return HyperCycleResult.failure(
                "Node /info payment metadata is missing a valid 'tm.address'"
            )

        effective_currency_type = self.currency_type
        if not self._currency_type_explicit:
            if effective_driver == "nullpay":
                effective_currency_type = symbol
            else:
                contract_address = currency_metadata.get("address")
                if not isinstance(contract_address, str) or not contract_address:
                    return HyperCycleResult.failure(
                        f"Node /info currency {symbol!r} is missing a contract address"
                    )
                effective_currency_type = contract_address

        self.driver = effective_driver
        self.currency_type = effective_currency_type
        self.currency_symbol = symbol
        self.currency_decimals = decimals
        self.node_hotwallet = hotwallet
        return HyperCycleResult.success(
            {
                "driver": self.driver,
                "currency_type": self.currency_type,
                "currency_symbol": self.currency_symbol,
                "currency_decimals": self.currency_decimals,
                "node_hotwallet": self.node_hotwallet,
            },
            status=info_result.status or 200,
        )

    def to_base_units(self, amount: Union[str, Decimal]) -> int:
        """Convert a decimal currency amount to exact integer base units."""
        if self.currency_decimals is None:
            raise ValueError(
                "currency_decimals is unset; call configure_from_node() first"
            )
        if not isinstance(amount, (str, Decimal)):
            raise TypeError("amount must be a string or Decimal, not float")
        try:
            decimal_amount = Decimal(amount)
        except InvalidOperation:
            raise ValueError(f"Invalid currency amount: {amount!r}") from None
        if not decimal_amount.is_finite() or decimal_amount < 0:
            raise ValueError("amount must be a finite, non-negative decimal")
        base_units = decimal_amount * (Decimal(10) ** self.currency_decimals)
        if base_units != base_units.to_integral_value():
            raise ValueError(
                f"amount has more than {self.currency_decimals} decimal places"
            )
        return int(base_units)

    def _require_payment_configuration(
        self,
        *,
        driver: Optional[str] = None,
        currency_type: Optional[str] = None,
    ) -> tuple:
        active_driver = driver if driver is not None else self.driver
        active_currency_type = (
            currency_type if currency_type is not None else self.currency_type
        )
        missing = []
        if not active_driver:
            missing.append("driver")
        if not active_currency_type:
            missing.append("currency_type")
        if missing:
            raise ValueError(
                "Payment configuration is unset ("
                + ", ".join(missing)
                + "); call configure_from_node() or pass explicit values"
            )
        return active_driver, active_currency_type

    def register_deposit(
        self,
        tx_id: str,
        value: int,
        *,
        currency_type: Optional[str] = None,
        driver: Optional[str] = None,
        origin: Optional[str] = None,
    ) -> HyperCycleResult[JsonObject]:
        """Register an existing chain deposit with ``POST /balance``."""
        active_driver, active_currency_type = self._require_payment_configuration(
            driver=driver, currency_type=currency_type
        )
        headers = {
            "tx-id": str(tx_id),
            "tx-sender": self.sender,
            "tx-origin": origin or self.sender,
            "currency-type": active_currency_type,
            "tx-value": str(value),
            "tx-driver": active_driver,
        }
        return self._request_json("POST", "/balance", b"", headers)

    def get_nonce(self) -> HyperCycleResult[JsonObject]:
        """Fetch the sender's current anti-replay nonce from ``GET /nonce``."""
        return self._request_json("GET", "/nonce", None, {"sender": self.sender})

    def create_session(
        self, delegate_address: str, duration: int = 21600
    ) -> HyperCycleResult[str]:
        """Create and wallet-activate a delegated signing session."""
        if self._session_key is not None:
            return HyperCycleResult.failure(
                "A delegated signer cannot create another session"
            )
        if not isinstance(duration, int) or isinstance(duration, bool):
            return HyperCycleResult.failure(
                "duration must be an integer between 1 and 86400 seconds"
            )
        if duration <= 0 or duration > 86400:
            return HyperCycleResult.failure(
                "duration must be between 1 and 86400 seconds"
            )
        if not self._is_address(delegate_address):
            return HyperCycleResult.failure(
                "delegate_address must be a 20-byte hexadecimal EVM address"
            )

        query = urllib.parse.urlencode(
            {"user_address": self.sender, "duration": duration}
        )
        created = self._request_json(
            "GET", f"/create_session?{query}", None, {}
        )
        if not created.ok:
            return HyperCycleResult.failure(
                f"Failed to create session: {created.error}", created.status
            )
        session_key = (
            created.data.get("data") if isinstance(created.data, dict) else None
        )
        if not isinstance(session_key, str) or not session_key:
            return HyperCycleResult.failure(
                "Session creation response did not contain a non-empty 'data' value",
                created.status,
            )

        activation = {
            "signer_address": self.sender,
            "public_key": delegate_address,
            "session_key": session_key,
            "signature": self._sign_text(f"{delegate_address}_{session_key}"),
        }
        activation_bytes = json.dumps(activation).encode("utf-8")
        activated = self._request_json(
            "POST", "/create_session", activation_bytes, {}
        )
        if not activated.ok:
            return HyperCycleResult.failure(
                f"Failed to activate session: {activated.error}", activated.status
            )
        message = (
            activated.data.get("message")
            if isinstance(activated.data, dict)
            else None
        )
        if message != "Session validated":
            return HyperCycleResult.failure(
                "Session activation response did not confirm 'Session validated'",
                activated.status,
            )
        return HyperCycleResult.success(session_key, status=activated.status or 200)

    def sign_nonce(self, nonce: str) -> str:
        """EIP-191-sign a protocol-1 nonce and return hex without ``0x``."""
        return self._sign_text(str(nonce))

    @staticmethod
    def build_protocol2_message(
        method: str,
        uri: str,
        headers: Mapping[str, str],
        body_bytes: Optional[bytes],
    ) -> str:
        """Build the byte-exact Node Manager protocol-2 signing message.

        Ported from Node Manager 0.5.4
        ``transaction_service.py:651-679``. Header regexes, case-sensitive
        sorting, signature-header exclusions, newline placement, and the
        conditional SHA-256 body line intentionally match the server code.
        """
        message = f"AIM ProtocolV2 Signature:\n{method}\n{uri}\n"
        signed_headers_match = [
            r"^tx-",
            r"^currency-type$",
            r"^cost_only$",
            r"^cost-only$",
            r"^ispublic$",
            r"^aim-header-",
        ]
        ignored_headers = ["tx-signature", "tx-signed-headers"]
        for header in sorted(headers):
            for test_string in signed_headers_match:
                if header not in ignored_headers and re.match(test_string, header):
                    message += header + ": " + str(headers[header]) + "\n"
                    break
        if body_bytes:
            message += "hash-body: " + hashlib.sha256(body_bytes).hexdigest()
        return message

    def execute_paid(
        self,
        slot: int,
        endpoint: str,
        body: JsonObject,
        *,
        tx_id: str = "",
        spend_order: Optional[Union[str, Sequence[str]]] = None,
        max_spend: Optional[Mapping[str, Any]] = None,
        protocol: Optional[int] = None,
    ) -> PaidResult:
        """Sign and execute ``POST /aim/<slot>/<endpoint>``."""
        self._require_payment_configuration()
        active_protocol = self.protocol if protocol is None else protocol
        if active_protocol not in (1, 2):
            return PaidResult(ok=False, error="protocol must be 1 or 2")

        nonce = self._next_nonce
        if not nonce:
            nonce_result = self.get_nonce()
            if not nonce_result.ok:
                return PaidResult(
                    ok=False,
                    error=f"Failed to fetch nonce: {nonce_result.error}",
                    status=nonce_result.status,
                )
            nonce_data = nonce_result.data
            nonce = (
                str(nonce_data.get("nonce", ""))
                if isinstance(nonce_data, dict)
                else ""
            )
            if not nonce:
                return PaidResult(
                    ok=False,
                    error="Nonce response did not contain a non-empty 'nonce' value",
                    status=nonce_result.status,
                )

        path = f"/aim/{slot}/{endpoint.lstrip('/')}"
        body_bytes = json.dumps(body).encode("utf-8")
        headers = self._paid_headers(
            nonce,
            tx_id=tx_id,
            spend_order=spend_order,
            max_spend=max_spend,
            protocol=active_protocol,
        )
        if active_protocol == 1:
            signature = self.sign_nonce(nonce)
        else:
            message = self.build_protocol2_message("POST", path, headers, body_bytes)
            signature = self._sign_text(message)
        headers["tx-signature"] = signature

        response = self._request_with_headers("POST", path, body_bytes, headers)
        parsed = self._paid_result(response)
        if parsed.next_nonce:
            self._next_nonce = parsed.next_nonce
        return parsed

    def _paid_headers(
        self,
        nonce: str,
        *,
        tx_id: str = "",
        spend_order: Optional[Union[str, Sequence[str]]] = None,
        max_spend: Optional[Mapping[str, Any]] = None,
        protocol: Optional[int] = None,
    ) -> Dict[str, str]:
        active_protocol = self.protocol if protocol is None else protocol
        if isinstance(spend_order, str):
            spend_value = spend_order
        elif spend_order is None:
            spend_value = ""
        else:
            spend_value = ",".join(str(item) for item in spend_order)
        headers = {
            "tx-id": str(tx_id),
            "tx-sender": self.sender,
            "tx-origin": self.sender,
            "tx-hypc-program": "",
            "tx-protocol": str(active_protocol),
            "currency-type": self.currency_type,
            "tx-value": "0",
            "tx-driver": self.driver,
            "tx-nonce": str(nonce),
            "tx-spend-order": spend_value,
            "tx-max-spend": (
                json.dumps(max_spend, separators=(",", ":"), sort_keys=True)
                if max_spend is not None
                else ""
            ),
        }
        if self._session_key is not None:
            headers["tx-session-key"] = self._session_key
        return headers

    def _sign_text(self, message: str) -> str:
        signed = Account.sign_message(
            encode_defunct(text=message), private_key=self._private_key
        )
        return self._signature_hex(signed.signature)

    @staticmethod
    def _is_address(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(
            r"0x[0-9a-fA-F]{40}", value
        ) is not None

    @staticmethod
    def _signature_hex(signature: Any) -> str:
        value = (
            signature.hex() if hasattr(signature, "hex") else bytes(signature).hex()
        )
        return value[2:] if value.startswith("0x") else value

    def _request_json(
        self,
        method: str,
        path: str,
        body_bytes: Optional[bytes],
        headers: Mapping[str, str],
    ) -> HyperCycleResult[JsonObject]:
        response = self._request_with_headers(method, path, body_bytes, headers)
        if response[0]:
            return HyperCycleResult.success(response[1], status=response[3])
        return HyperCycleResult.failure(
            response[2] or "Request failed", status=response[3]
        )

    def _request_with_headers(
        self,
        method: str,
        path: str,
        body_bytes: Optional[bytes],
        headers: Mapping[str, str],
    ) -> tuple:
        url = f"{self.node_url}{path}"
        try:
            request = urllib.request.Request(url, data=body_bytes, method=method)
            if body_bytes:
                request.add_header("Content-Type", "application/json")
            for key, value in headers.items():
                request.add_header(key, value)
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = self._decode_json(response.read())
                return True, payload, None, response.status, response.headers
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            payload = self._decode_json(raw)
            text = raw.decode("utf-8", errors="replace")
            error = f"HTTP {exc.code} from {url}: {text}"
            return False, payload, error, exc.code, exc.headers
        except urllib.error.URLError as exc:
            return False, None, f"Connection error to {url}: {exc.reason}", None, {}
        except Exception as exc:
            return False, None, f"Unexpected error: {exc}", None, {}

    @staticmethod
    def _decode_json(raw: bytes) -> Any:
        if not raw:
            return {}
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @classmethod
    def _paid_result(cls, response: tuple) -> PaidResult:
        ok, data, error, status, raw_headers = response
        headers = {str(key).lower(): value for key, value in raw_headers.items()}

        def header(*names: str) -> Optional[str]:
            for name in names:
                value = headers.get(name.lower())
                if value is not None:
                    return value
            return None

        value_used = cls._json_header(header("value_used", "value-used"), {})
        latest_valid_tx = cls._json_header(
            header("latest-valid-tx", "latest_valid_tx"), []
        )
        verified_raw = header("verified_input_tx", "verified-input-tx")
        verified = None
        if verified_raw is not None:
            normalized = verified_raw.strip().lower()
            if normalized in ("true", "false"):
                verified = normalized == "true"
        return PaidResult(
            ok=ok,
            data=data if ok else None,
            error=error,
            status=status,
            value_used=value_used if isinstance(value_used, dict) else {},
            next_nonce=header("next_nonce", "next-nonce"),
            verified_input_tx=verified,
            verification_message=header(
                "verification_message", "verification-message"
            ),
            latest_valid_tx=(
                latest_valid_tx if isinstance(latest_valid_tx, list) else []
            ),
            registered_deposit_tx=header(
                "registered-deposit-tx", "registered_deposit_tx"
            ),
        )

    @staticmethod
    def _json_header(value: Optional[str], default: Any) -> Any:
        if value is None or value == "":
            return default
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default


class DelegateSigner(PayingClient):
    """Paid client that spends from a wallet and signs with a session delegate."""

    def __init__(
        self,
        node_url: Optional[str] = None,
        *,
        session_key: str,
        delegate_private_key: Union[str, bytes],
        wallet_address: str,
        timeout: int = 30,
        driver: Optional[str] = None,
        currency_type: Optional[str] = None,
        protocol: int = 1,
    ):
        if not isinstance(session_key, str) or not session_key:
            raise ValueError("session_key must be a non-empty string")
        if not self._is_address(wallet_address):
            raise ValueError(
                "wallet_address must be a 20-byte hexadecimal EVM address"
            )
        super().__init__(
            node_url=node_url,
            private_key=delegate_private_key,
            timeout=timeout,
            driver=driver,
            currency_type=currency_type,
            protocol=protocol,
        )
        self.signer_address = self.sender
        self.sender = wallet_address
        self._session_key = session_key
