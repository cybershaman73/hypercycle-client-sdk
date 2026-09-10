from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

PYTHON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_DIR))

import hypercycle_pay
import smoke_paid_call
from hypercycle_pay import DelegateSigner, PayingClient


# Oracle ports of TransactionService.get_protocol2_message (0.5.4:651-679)
# and the EVM branch used by verify_nonce_and_signature (0.5.4:729-795).
def oracle_protocol2_message(method, uri, headers, body):
    message = f"AIM ProtocolV2 Signature:\n{method}\n{uri}\n"
    signed_headers_match = [
        r"^tx-",
        r"^currency-type$",
        r"^cost_only$",
        r"^cost-only$",
        r"^ispublic$",
        r"^aim-header-",
    ]
    message_headers = {}
    ignored_headers = ["tx-signature", "tx-signed-headers"]
    valid = True
    for header in sorted(headers):
        for test_string in signed_headers_match:
            if header not in ignored_headers and re.match(test_string, header):
                message += header + ": " + headers[header] + "\n"
                message_headers[header] = 1
                break
    if "tx-nonce" not in message_headers:
        valid = False
    if body:
        body = hashlib.sha256(body).hexdigest()
        message = message + "hash-body: " + body
    return message, valid


def oracle_verify_nonce_and_signature(
    sender,
    stored_raw_nonce,
    nonce,
    signature,
    protocol,
    method,
    uri,
    headers,
    body,
    next_raw_nonce="HYPC_sender_1_next",
):
    def hn(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    valid_message = True
    if str(protocol) == "1":
        message = nonce
    elif str(protocol) == "2":
        message, valid_message = oracle_protocol2_message(method, uri, headers, body)
    else:
        return False
    if not valid_message:
        signature_valid = False
    else:
        recovered = Account.recover_message(
            encode_defunct(text=message), signature=bytes.fromhex(signature)
        )
        signature_valid = recovered.lower() == sender.lower()
    if hn(stored_raw_nonce) != nonce:
        return {"error": f"Invalid nonce: [{nonce}]", "next_nonce": hn(stored_raw_nonce)}
    if not signature_valid:
        return {"error": "Signature invalid for nonce", "next_nonce": hn(stored_raw_nonce)}
    return {"signature_valid": True, "next_nonce": hn(next_raw_nonce)}


@pytest.fixture
def private_key():
    return Account.create().key.hex()


@pytest.mark.parametrize(
    "headers,body",
    [
        ({"tx-nonce": "abc", "tx-sender": "0x123"}, b""),
        (
            {
                "tx-sender": "0x123",
                "currency-type": "HyPC",
                "tx-nonce": "def",
                "tx-signature": "excluded",
                "tx-signed-headers": "excluded",
                "aim-header-trace": "yes",
                "content-type": "application/json",
                "x-extra": "excluded",
            },
            b'{"prompt": "hi"}',
        ),
        (
            {
                "TX-NONCE": "case-sensitive-and-excluded",
                "Currency-Type": "also-excluded",
                "tx-nonce": "included",
                "cost-only": "1",
                "ispublic": "false",
            },
            b"\x00binary\xff",
        ),
    ],
)
def test_protocol2_builder_matches_server_oracle(headers, body):
    expected, _ = oracle_protocol2_message("POST", "/aim/0/chat", headers, body)
    actual = PayingClient.build_protocol2_message(
        "POST", "/aim/0/chat", headers, body
    )
    assert actual == expected


def test_protocol1_signature_recovers_to_sender(private_key):
    client = PayingClient("http://127.0.0.1:1", private_key=private_key)
    nonce = hashlib.sha256(b"nonce").hexdigest()
    signature = client.sign_nonce(nonce)

    assert not signature.startswith("0x")
    verified = oracle_verify_nonce_and_signature(
        client.sender, "nonce", nonce, signature, 1, "POST", "/aim/0/chat", {}, b""
    )
    assert verified["signature_valid"] is True


def test_protocol2_signature_recovers_to_sender(private_key):
    client = PayingClient(
        "http://127.0.0.1:1",
        private_key=private_key,
        protocol=2,
        driver="ethereum",
        currency_type="HyPC",
    )
    body = json.dumps({"prompt": "hi"}).encode("utf-8")
    raw_nonce = "nonce-2"
    nonce = hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()
    headers = client._paid_headers(nonce, protocol=2)
    message = client.build_protocol2_message(
        "POST", "/aim/0/chat", headers, body
    )
    signature = client._signature_hex(
        Account.sign_message(
            encode_defunct(text=message), private_key=private_key
        ).signature
    )

    verified = oracle_verify_nonce_and_signature(
        client.sender,
        raw_nonce,
        nonce,
        signature,
        2,
        "POST",
        "/aim/0/chat",
        headers,
        body,
    )
    assert verified["signature_valid"] is True


def test_oracle_rejects_wrong_nonce(private_key):
    client = PayingClient("http://127.0.0.1:1", private_key=private_key)
    submitted_nonce = hashlib.sha256(b"different").hexdigest()
    result = oracle_verify_nonce_and_signature(
        client.sender,
        "stored",
        submitted_nonce,
        client.sign_nonce(submitted_nonce),
        1,
        "POST",
        "/aim/0/chat",
        {},
        b"",
    )
    assert "Invalid nonce" in result["error"]


class StubHandler(BaseHTTPRequestHandler):
    requests = []
    nonce_calls = 0
    aim_calls = 0
    raw_nonce = "raw-nonce-one"
    session_key = "stub-session-key"
    payment_driver = "basechain"
    accepting_currencies = ["USDC"]
    currencies = {
        "USDC": {
            "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "decimals": 6,
        },
        "HyPC": {
            "address": "0x1111111111111111111111111111111111111111",
            "decimals": 18,
        },
    }

    def log_message(self, format, *args):
        pass

    @classmethod
    def dispatch(cls, method, path, headers, body=b""):
        cls.requests.append(
            {
                "method": method,
                "path": path,
                "headers": headers,
                "body": body,
            }
        )
        parsed = urllib.parse.urlsplit(path)
        if method == "GET" and parsed.path == "/info":
            return 200, {
                "tm": {
                    "driver": cls.payment_driver,
                    "chain_id": 8453,
                    "address": "0x2222222222222222222222222222222222222222",
                    "currencies": cls.currencies,
                },
                "accepting_currencies": cls.accepting_currencies,
            }, {}
        if method == "GET" and parsed.path == "/nonce":
            cls.nonce_calls += 1
            nonce = hashlib.sha256(cls.raw_nonce.encode("utf-8")).hexdigest()
            return 200, {"nonce": nonce}, {}
        if method == "GET" and parsed.path == "/create_session":
            return 200, {"data": cls.session_key}, {}
        if method == "POST" and parsed.path == "/balance":
            return 200, {"verified": "true", "balance": {}}, {}
        if method == "POST" and parsed.path == "/create_session":
            return 200, {"status": "success", "message": "Session validated"}, {}
        if method == "POST" and parsed.path == "/aim/0/chat":
            if headers.get("cost_only"):
                return 200, {"costs": []}, {}
            cls.aim_calls += 1
            next_nonce = "nonce-two" if cls.aim_calls == 1 else "nonce-three"
            response_headers = {
                "value-used": json.dumps({"HyPC": {"used": 7}}),
                "next_nonce": next_nonce,
                "verified-input-tx": "true",
                "verification_message": "Processed: Valid Payment",
                "latest-valid-tx": json.dumps([["0xtx", 1.0]]),
                "registered-deposit-tx": "",
            }
            return 200, {"answer": "ok"}, response_headers
        return 404, {"error": "not found"}, {}

    def _json(self, payload, headers=None):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        status, payload, headers = type(self).dispatch(
            "GET",
            self.path,
            {key.lower(): value for key, value in self.headers.items()},
        )
        if status == 200:
            self._json(payload, headers)
        else:
            self.send_error(status)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        status, payload, headers = type(self).dispatch(
            "POST",
            self.path,
            {key.lower(): value for key, value in self.headers.items()},
            body,
        )
        if status == 200:
            self._json(payload, headers)
        else:
            self.send_error(status)


class StubResponse:
    def __init__(self, status, payload, headers):
        self.status = status
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key] = value
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self._body


@pytest.fixture
def stub_server(monkeypatch):
    StubHandler.requests = []
    StubHandler.nonce_calls = 0
    StubHandler.aim_calls = 0
    StubHandler.payment_driver = "basechain"
    StubHandler.accepting_currencies = ["USDC"]
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    except PermissionError:
        def urlopen(request, timeout):
            parsed = urllib.parse.urlsplit(request.full_url)
            path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            status, payload, headers = StubHandler.dispatch(
                request.get_method(),
                path,
                {key.lower(): value for key, value in request.header_items()},
                request.data or b"",
            )
            assert status == 200, (request.get_method(), path, payload)
            return StubResponse(status, payload, headers)

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        yield "http://stub.invalid"
        return
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_stub_server_full_flow_and_nonce_reuse(stub_server, private_key):
    client = PayingClient(
        stub_server,
        private_key=private_key,
        driver="ethereum",
        currency_type="HyPC",
    )

    deposit = client.register_deposit("0xdeposit", 25)
    first = client.execute_paid(
        0,
        "chat",
        {"prompt": "one"},
        spend_order=["USDC", "HyPC"],
        max_spend={"HyPC": {"used": 10}},
    )
    second = client.execute_paid(0, "chat", {"prompt": "two"})
    estimate = client.estimate(0, "chat", {"prompt": "estimate"})

    assert deposit.ok
    assert first.ok and second.ok and estimate.ok
    assert first.value_used == {"HyPC": {"used": 7}}
    assert first.next_nonce == "nonce-two"
    assert first.verified_input_tx is True
    assert first.latest_valid_tx == [["0xtx", 1.0]]
    assert StubHandler.nonce_calls == 1

    deposit_request = next(r for r in StubHandler.requests if r["path"] == "/balance")
    deposit_headers = {
        key: value
        for key, value in deposit_request["headers"].items()
        if key.startswith("tx-") or key == "currency-type"
    }
    assert deposit_headers == {
        "tx-id": "0xdeposit",
        "tx-sender": client.sender,
        "tx-origin": client.sender,
        "currency-type": "HyPC",
        "tx-value": "25",
        "tx-driver": "ethereum",
    }

    paid = [
        r
        for r in StubHandler.requests
        if r["path"] == "/aim/0/chat" and "tx-signature" in r["headers"]
    ]
    assert len(paid) == 2
    required = {
        "tx-id",
        "tx-sender",
        "tx-origin",
        "tx-hypc-program",
        "tx-protocol",
        "currency-type",
        "tx-value",
        "tx-driver",
        "tx-nonce",
        "tx-spend-order",
        "tx-max-spend",
        "tx-signature",
    }
    assert required <= paid[0]["headers"].keys()
    expected_first_nonce = hashlib.sha256(b"raw-nonce-one").hexdigest()
    assert paid[0]["headers"]["tx-nonce"] == expected_first_nonce
    assert paid[1]["headers"]["tx-nonce"] == "nonce-two"
    assert paid[0]["headers"]["tx-spend-order"] == "USDC,HyPC"
    assert json.loads(paid[0]["headers"]["tx-max-spend"]) == {
        "HyPC": {"used": 10}
    }
    assert not paid[0]["headers"]["tx-signature"].startswith("0x")
    first_payment_headers = {
        key: value
        for key, value in paid[0]["headers"].items()
        if key.startswith("tx-") or key == "currency-type"
    }
    signature = first_payment_headers.pop("tx-signature")
    assert signature
    assert first_payment_headers == {
        "tx-id": "",
        "tx-sender": client.sender,
        "tx-origin": client.sender,
        "tx-hypc-program": "",
        "tx-protocol": "1",
        "currency-type": "HyPC",
        "tx-value": "0",
        "tx-driver": "ethereum",
        "tx-nonce": expected_first_nonce,
        "tx-spend-order": "USDC,HyPC",
        "tx-max-spend": '{"HyPC":{"used":10}}',
    }

    estimate_request = StubHandler.requests[-1]
    assert estimate_request["headers"]["cost_only"] == "true"
    assert not any(key.startswith("tx-") for key in estimate_request["headers"])


def test_configure_from_node_derives_payment_headers(stub_server, private_key):
    client = PayingClient(stub_server, private_key=private_key)

    result = client.configure_from_node()

    assert result.ok
    assert client.driver == "basechain"
    assert client.currency_type == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    assert client.currency_symbol == "USDC"
    assert client.currency_decimals == 6
    assert client.node_hotwallet == "0x2222222222222222222222222222222222222222"
    assert client.to_base_units("12.50") == 12_500_000
    assert client.to_base_units(Decimal("0.000001")) == 1


def test_configure_from_node_rejects_ambiguous_currency(
    stub_server, private_key
):
    StubHandler.accepting_currencies = ["USDC", "HyPC"]
    client = PayingClient(stub_server, private_key=private_key)

    result = client.configure_from_node()

    assert not result.ok
    assert "multiple currencies" in result.error
    assert "specify one explicitly" in result.error


def test_configure_from_node_preserves_explicit_overrides(
    stub_server, private_key
):
    client = PayingClient(
        stub_server,
        private_key=private_key,
        driver="custom-driver",
        currency_type="custom-currency-type",
    )

    result = client.configure_from_node("USDC")

    assert result.ok
    assert client.driver == "custom-driver"
    assert client.currency_type == "custom-currency-type"
    assert client.currency_symbol == "USDC"
    assert client.currency_decimals == 6


def test_unset_payment_configuration_fails_before_request(
    stub_server, private_key
):
    client = PayingClient(stub_server, private_key=private_key)

    with pytest.raises(ValueError, match="Payment configuration is unset"):
        client.register_deposit("0xdeposit", 1)
    with pytest.raises(ValueError, match="Payment configuration is unset"):
        client.execute_paid(0, "chat", {"prompt": "blocked"})

    assert StubHandler.requests == []


def test_nullpay_uses_currency_symbol(stub_server, private_key):
    StubHandler.payment_driver = "nullpay"
    client = PayingClient(stub_server, private_key=private_key)

    result = client.configure_from_node("USDC")

    assert result.ok
    assert client.driver == "nullpay"
    assert client.currency_type == "USDC"


def test_protocol2_execute_signature_matches_oracle(stub_server, private_key):
    client = PayingClient(
        stub_server,
        private_key=private_key,
        protocol=2,
        driver="ethereum",
        currency_type="HyPC",
    )
    result = client.execute_paid(0, "chat", {"prompt": "signed"})

    assert result.ok
    request = next(
        item
        for item in StubHandler.requests
        if item["path"] == "/aim/0/chat" and "tx-signature" in item["headers"]
    )
    verified = oracle_verify_nonce_and_signature(
        client.sender,
        StubHandler.raw_nonce,
        request["headers"]["tx-nonce"],
        request["headers"]["tx-signature"],
        2,
        "POST",
        request["path"],
        request["headers"],
        request["body"],
    )
    assert verified["signature_valid"] is True


def test_protocol2_execute_signs_full_request_path_with_query(
    stub_server, private_key
):
    client = PayingClient(
        stub_server,
        private_key=private_key,
        protocol=2,
        driver="ethereum",
        currency_type="HyPC",
    )
    result = client.execute_paid(0, "chat?mode=fast", {"prompt": "signed"})

    assert result.ok
    request = next(
        item
        for item in StubHandler.requests
        if item["path"] == "/aim/0/chat?mode=fast"
        and "tx-signature" in item["headers"]
    )
    verified = oracle_verify_nonce_and_signature(
        client.sender,
        StubHandler.raw_nonce,
        request["headers"]["tx-nonce"],
        request["headers"]["tx-signature"],
        2,
        "POST",
        request["path"],
        request["headers"],
        request["body"],
    )
    assert verified["signature_valid"] is True


def test_create_session_activation_is_signed_by_wallet(
    stub_server, private_key
):
    delegate = Account.create()
    client = PayingClient(stub_server, private_key=private_key)

    result = client.create_session(delegate.address, duration=3600)

    assert result.ok
    assert result.data == StubHandler.session_key
    creation = next(
        item
        for item in StubHandler.requests
        if item["method"] == "GET"
        and urllib.parse.urlsplit(item["path"]).path == "/create_session"
    )
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(creation["path"]).query)
    assert query == {"user_address": [client.sender], "duration": ["3600"]}

    activation = next(
        item
        for item in StubHandler.requests
        if item["method"] == "POST" and item["path"] == "/create_session"
    )
    payload = json.loads(activation["body"])
    assert payload["signer_address"] == client.sender
    assert payload["public_key"] == delegate.address
    assert payload["session_key"] == StubHandler.session_key
    recovered = Account.recover_message(
        encode_defunct(text=f"{delegate.address}_{StubHandler.session_key}"),
        signature=bytes.fromhex(payload["signature"]),
    )
    assert recovered.lower() == client.sender.lower()


@pytest.mark.parametrize("duration", [0, -1, 86401])
def test_create_session_rejects_duration_outside_bounds(
    stub_server, private_key, duration
):
    client = PayingClient(stub_server, private_key=private_key)

    result = client.create_session(Account.create().address, duration=duration)

    assert not result.ok
    assert "between 1 and 86400" in result.error
    assert StubHandler.requests == []


@pytest.mark.parametrize("protocol", [1, 2])
def test_session_call_uses_wallet_sender_and_delegate_signature(
    stub_server, private_key, protocol
):
    wallet = Account.from_key(private_key)
    delegate = Account.create()
    client = DelegateSigner(
        stub_server,
        session_key=StubHandler.session_key,
        delegate_private_key=delegate.key,
        wallet_address=wallet.address,
        protocol=protocol,
        driver="ethereum",
        currency_type="HyPC",
    )

    result = client.execute_paid(0, "chat", {"prompt": "delegated"})

    assert result.ok
    request = next(
        item
        for item in StubHandler.requests
        if item["path"] == "/aim/0/chat" and "tx-signature" in item["headers"]
    )
    assert request["headers"]["tx-sender"] == wallet.address
    assert request["headers"]["tx-session-key"] == StubHandler.session_key
    if protocol == 1:
        signed_message = request["headers"]["tx-nonce"]
    else:
        signed_message, valid = oracle_protocol2_message(
            "POST",
            request["path"],
            request["headers"],
            request["body"],
        )
        assert valid
    recovered = Account.recover_message(
        encode_defunct(text=signed_message),
        signature=bytes.fromhex(request["headers"]["tx-signature"]),
    )
    assert recovered.lower() == delegate.address.lower()
    assert recovered.lower() != wallet.address.lower()


def test_paid_result_accepts_underscore_response_headers():
    headers = Message()
    headers["value_used"] = json.dumps({"USDC": {"used": 3}})
    headers["next-nonce"] = "next"
    headers["verified_input_tx"] = "FALSE"
    headers["verification-message"] = "pending"
    headers["latest_valid_tx"] = json.dumps(["0x1"])
    headers["registered_deposit_tx"] = "0x2"

    result = PayingClient._paid_result((True, {"ok": 1}, None, 200, headers))

    assert result.value_used == {"USDC": {"used": 3}}
    assert result.next_nonce == "next"
    assert result.verified_input_tx is False
    assert result.verification_message == "pending"
    assert result.latest_valid_tx == ["0x1"]
    assert result.registered_deposit_tx == "0x2"


def test_missing_eth_account_has_clear_error(monkeypatch, private_key):
    monkeypatch.setattr(hypercycle_pay, "Account", None)
    with pytest.raises(ImportError, match="pip install eth-account"):
        PayingClient("http://127.0.0.1:1", private_key=private_key)


def test_missing_key_has_clear_error(monkeypatch):
    monkeypatch.delenv("HYPERCYCLE_WALLET_KEY", raising=False)
    with pytest.raises(ValueError, match="private_key is required"):
        PayingClient("http://127.0.0.1:1")


@pytest.mark.parametrize(
    "mode,expected_aim_calls,expected_exit", [("--dry-run", 0, 0), ("--live", 1, 0)]
)
def test_smoke_configures_from_info_before_dry_run_or_live_call(
    stub_server,
    monkeypatch,
    capsys,
    private_key,
    mode,
    expected_aim_calls,
    expected_exit,
):
    monkeypatch.setenv("HYPERCYCLE_NODE_URL", stub_server)
    monkeypatch.setenv("HYPERCYCLE_WALLET_KEY", private_key)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_paid_call.py",
            mode,
            "--slot",
            "0",
            "--endpoint",
            "chat",
            "--currency",
            "USDC",
            "--body-json",
            '{"prompt":"hi"}',
        ],
    )

    assert smoke_paid_call.main() == expected_exit
    output = json.loads(capsys.readouterr().out)
    if mode == "--dry-run":
        assert output["headers"]["tx-driver"] == "basechain"
        assert (
            output["headers"]["currency-type"]
            == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        )
    else:
        assert output["value_used"] == {"HyPC": {"used": 7}}
    assert StubHandler.aim_calls == expected_aim_calls
    assert StubHandler.requests[0]["path"] == "/info"


@pytest.mark.parametrize("mode", ["--dry-run", "--session-delegate"])
def test_smoke_preview_handles_missing_node_url(
    monkeypatch, capsys, private_key, mode
):
    monkeypatch.delenv("HYPERCYCLE_NODE_URL", raising=False)
    monkeypatch.setenv("HYPERCYCLE_WALLET_KEY", private_key)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("stub unavailable")
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_paid_call.py",
            mode,
            "--slot",
            "0",
            "--endpoint",
            "chat",
            "--body-json",
            '{"prompt":"hi"}',
        ],
    )

    assert smoke_paid_call.main() == 0
    preview = json.loads(capsys.readouterr().out)
    if mode == "--dry-run":
        assert preview["path"] == "/aim/0/chat"
        assert preview["headers"]["tx-driver"] == "<from /info>"
        assert preview["headers"]["currency-type"] == "<from /info>"
    else:
        assert preview["mode"] == "session-delegate-dry-run"
        assert preview["steps"][2]["headers"]["tx-session-key"]
