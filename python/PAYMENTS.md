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

Session keys: see follow-up PR.

## Security and spend controls

Keep `HYPERCYCLE_WALLET_KEY` out of source control, shell history, logs,
OneDrive, screenshots, and support messages. Use a dedicated low-balance
wallet, scoped to this purpose, rather than a treasury wallet.

Node Manager 0.5.4 parses `tx-max-spend`, but the supplied server source does
not enforce it during deduction. Treat it as advisory; enforce real limits
through wallet balances and application policy.

Never retry a failed paid call blindly: a timeout can occur after execution.
Reconcile the returned nonce and accounting state before retrying.

## Tests

Tests use only a loopback stub server and throwaway keys:

```bash
python -m pytest python/tests -q
```
