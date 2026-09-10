# Payments (Python)

The payment layer extends `HyperCycleClient` with EVM wallet signing for
HyperCycle Node Manager 0.5.4 paid AIM calls.

## Install

Python 3.8+ is supported. Payments add one optional dependency:

```bash
python -m pip install eth-account
python -m pip install pytest # tests only
```

Set configuration without putting keys in source code:

```bash
export HYPERCYCLE_NODE_URL=http://127.0.0.1:8000
export HYPERCYCLE_WALLET_KEY=... # enter locally; never commit it
```

## Payment flow

1. Call `configure_from_node()` to select an accepted currency and load its
   driver, contract address, decimals, and node hot-wallet address.
2. Transfer that currency to the node using your own wallet tooling.
3. Call `register_deposit(tx_id, value)` to register that chain transaction.
4. Call `execute_paid(slot, endpoint, body)`.
5. The first paid call fetches `/nonce`; later calls reuse response `next_nonce`.
6. Inspect `PaidResult.value_used` and `verified_input_tx`.

`register_deposit` does not create or submit an on-chain transaction. It only
asks Node Manager to verify and credit an already-existing transaction ID.

Call `configure_from_node()` before registering a deposit or executing a paid
call. It reads the node's payment engine from `/info`, uses `tm.driver` for
`tx-driver`, and uses the selected currency's ERC-20 contract address for
`currency-type` (`nullpay` nodes use the currency symbol). If the node accepts
more than one currency, pass the desired symbol explicitly. Constructor values
for `driver` or `currency_type` remain explicit overrides.

Deposit values are integer base units. Convert a human-readable amount without
floating-point rounding:

```python
configured = client.configure_from_node("USDC")
if not configured.ok:
    raise RuntimeError(configured.error)
tx_value = client.to_base_units("12.50")  # 12500000 when decimals is 6
client.register_deposit(tx_id, tx_value)
```

## Protocol 1 and protocol 2

Protocol 1 EIP-191-signs the nonce string and is the default.

Protocol 2 signs the method, URI, selected sorted payment headers, and SHA-256
hash of the exact JSON bytes, binding the signature to the request.

The deployed AIM handler passes the full request path and query string to the
verifier. Accordingly, this SDK signs `/aim/<slot>/<endpoint>` plus the exact
`?query` suffix when one is present.

## Delegated session keys

Session keys let a short-lived delegate sign requests while the wallet remains
the balance owner. Create and activate one with the wallet client:

```python
from eth_account import Account
from hypercycle_pay import DelegateSigner, PayingClient

wallet = PayingClient()
delegate = Account.create()
session = wallet.create_session(delegate.address, duration=21600)
if not session.ok:
    raise RuntimeError(session.error)

client = DelegateSigner(
    wallet.node_url,
    session_key=session.data,
    delegate_private_key=delegate.key,
    wallet_address=wallet.sender,
)
configured = client.configure_from_node()
if not configured.ok:
    raise RuntimeError(configured.error)
result = client.execute_paid(0, "chat", {"prompt": "hi"})
```

`create_session` performs `GET /create_session`, then wallet-signs
`<delegate_address>_<session_key>` using EIP-191 and activates it with
`POST /create_session`. Delegated paid calls keep `tx-sender` set to the wallet,
add `tx-session-key`, and sign the nonce or protocol-2 message with the delegate
key. Durations must be between 1 and 86400 seconds.

## Security and spend controls

Keep `HYPERCYCLE_WALLET_KEY` out of source control, shell history, logs,
OneDrive, screenshots, and support messages. Use a dedicated low-balance
wallet, scoped to this purpose, rather than a treasury wallet.

Protect delegate private keys as credentials, expire sessions promptly, and do
not treat sessions as server-enforced spend caps. The referenced Node Manager
validates expiry and delegate identity but does not apply a session spend limit.

Node Manager 0.5.4 parses `tx-max-spend`, but the supplied server source does
not enforce it during deduction. Treat it as advisory; enforce real limits
through wallet balances and application policy.

Never retry a failed paid call blindly: a timeout can occur after execution.
Reconcile the returned nonce and accounting state before retrying.

## Tests and smoke test

Tests use only a loopback stub server and throwaway keys:

```bash
python -m pytest python/tests -q
```

Preview a request after read-only payment discovery from `GET /info`:

```bash
python python/smoke_paid_call.py --dry-run --slot 0 --endpoint chat \
  --currency USDC --body-json '{"prompt":"hi"}'
```

If `/info` is unreachable, dry-run reports the reason and still prints the
header plan with `<from /info>` placeholders. It makes no paid or mutating
request.

Preview the wallet activation and delegated-call flow without network calls:

```bash
python python/smoke_paid_call.py --session-delegate --slot 0 --endpoint chat \
  --body-json '{"prompt":"hi"}'
```

Use `--live` only after confirming the node, currency, driver, deposit, and
wallet boundary. It succeeds only for positive `value_used`.
