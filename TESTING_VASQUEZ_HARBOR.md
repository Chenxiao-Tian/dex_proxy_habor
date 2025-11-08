# Vasquez ↔ Harbor dex-proxy Test Plan

This guide explains how to run the Harbor dex-proxy adapter locally, connect the Vasquez
strategy runner as an external process, and validate order lifecycle flows using Binance
Spot market data for `ETHUSDT`.

> **Key behaviours**
> - Honor Harbor `priceTick`/`qtyTick` before submitting orders.
> - All timestamps are string nanoseconds in API responses.
> - Error payloads always include a `request_id` field.
> - Do **not** cache vault or inbound addresses; always fetch `/xnode/inbound_addresses`
>   when you need deposit details (not required for this smoke test).

---

## 1. Environment setup

### 1.1 Clone and bootstrap

```bash
cd /path/to/workspace
python -m venv .venv
source .venv/bin/activate  # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e py_dex_common
pip install -e harbor
pip install -e vasquez
```

> Windows `cmd.exe`:
> ```cmd
> python -m venv .venv
> .\.venv\Scripts\activate.bat
> pip install -e py_dex_common
> pip install -e harbor
> pip install -e vasquez
> ```

### 1.2 Environment variables

Copy the example file, then update it with your Harbor staging API key (ASCII characters only):
Copy the example file and update it with your Harbor staging API key (ASCII characters only).
The repo ships with the current staging key (`6c30c576-f7db-4ae5-ac19-118d456c082e`) so
you can run smoke tests immediately, but rotate it if your team issues a replacement:
Copy the example file and update it with your Harbor staging API key (ASCII characters only):

```bash
cp .env.example .env
```

Edit `.env` or export variables manually. Equivalent commands:

- **bash / zsh**
  ```bash
  export HARBOR_API_KEY="<your-harbor-api-key>"
  export HARBOR_API_KEY="6c30c576-f7db-4ae5-ac19-118d456c082e"
  export HARBOR_API_KEY="xxxxxxxxxxxxxxxx"
  export DEX_PROXY_BASE="http://127.0.0.1:1958"
  ```

- **Windows cmd.exe**
  ```cmd
  set HARBOR_API_KEY=<your-harbor-api-key>
  set HARBOR_API_KEY=6c30c576-f7db-4ae5-ac19-118d456c082e
  set HARBOR_API_KEY=xxxxxxxxxxxxxxxx
  set DEX_PROXY_BASE=http://127.0.0.1:1958
  ```

- **Windows PowerShell**
  ```powershell
  $env:HARBOR_API_KEY = "<your-harbor-api-key>"
  $env:HARBOR_API_KEY = "6c30c576-f7db-4ae5-ac19-118d456c082e"
  $env:HARBOR_API_KEY = "xxxxxxxxxxxxxxxx"
  $env:DEX_PROXY_BASE = "http://127.0.0.1:1958"
  ```

Keep the key free of spaces or angle brackets to avoid Harbor 401 responses.

### 1.3 Harbor config (harbor/harbor.config.json)

`harbor/harbor.config.json` is committed to the repo with the latest stagenet defaults so you
can boot the proxy immediately. Review the snippet below to confirm the values or tweak them
for custom setups:
Create `harbor/harbor.config.json` using the template below. The adapter reads the key from
`HARBOR_API_KEY` via `api_key_env` and exposes HTTP on port `1958`.

```json
{
  "logging": {
    "level": "debug",
    "overrides": [
      { "logger_name": "aiohttp.access", "level": "warning" },
      { "logger_name": "pantheon.app_health", "level": "info" }
    ]
    "level": "info"
  },
  "server": {
    "host": "0.0.0.0",
    "port": 1958
  },
  "RabbitMQ": { "url": "amqp://localhost" },
  "key_store_file_path": "kuru/test-local-wallet.json",
  "dex": {
    "name": "harbor",
    "env": "stagenet",
    "base_url": "https://api.harbor-dev.xyz/api/v1",
    "ws_url": "wss://api.harbor-dev.xyz/api/v1/ws",
    "rest": {
      "base_url": "https://api.harbor-dev.xyz/api/v1",
      "api_key_env": "HARBOR_API_KEY",
      "default_time_in_force": "gtc",
      "timeout": 20,
      "proxy": null,
      "trust_env": true,
      "verify_ssl": true
    },
    "ws": {
      "url": "wss://api.harbor-dev.xyz/api/v1/ws",
      "reconnect_interval": 10
    },
    "request_cache": {
      "enabled": true,
      "request_ttl_s": 2,
      "capacity": 512,
      "finalised_requests_cleanup_after_s": 600,
      "store_in_redis": false
    },
    "transactions_status_poller": {
      "poll_interval_s": 30
    },
    "eth_from_addr": "0xD1287859F3197C05c67578E3d64092e6639b1000",
    "btc_from_addr": "bc1qu5s2s97g0s0a0pnhe7h2jxj0aexue8u6wjgxsj"
  },
  "app": {
    "name": "dex-proxy-harbor",
    "version": "0.1.0",
    "env": "local"
  "key_store_file_path": [
    "harbor/kuru/test-local-wallet.json"
  ],
  "dex": {
    "name": "harbor",
    "rest": {
      "base_url": "https://api.harbor-dev.xyz/api/v1",
      "api_key_env": "HARBOR_API_KEY",
      "timeout": 30,
      "default_time_in_force": "gtc"
    },
    "ws": {
      "url": "wss://api.harbor-dev.xyz/ws/v1"
    }
  }
}
```

> The bundled keystore is encrypted with an empty password and suitable for local smoke tests only.

---

## 2. Start the Harbor dex-proxy locally

The helper scripts automatically load `.env`, print the API key length, and confirm the
listening port.

- **bash / zsh**
  ```bash
  scripts/run_harbor_proxy_local.sh
  ```

- **Windows cmd.exe**
  ```cmd
  scripts\run_harbor_proxy_local.bat
  ```

Expected banner:
```
[run_harbor_proxy_local] Using config: /repo/harbor/harbor.config.json
[run_harbor_proxy_local] Harbor API key length: 32
[run_harbor_proxy_local] Listening on: http://127.0.0.1:1958 (port 1958)
```

The server exposes Swagger at `http://127.0.0.1:1958/docs`. Keep this terminal open while
running Vasquez.

> Sanity check the port with curl:
> ```bash
> curl http://127.0.0.1:1958/ping
> ```

---

## 3. Run Vasquez as a separate process

The example runner sources Binance Spot data and speaks to the local dex-proxy over HTTP.

- **bash / zsh**
  ```bash
  scripts/run_vasquez_local.sh --symbol ETHUSDT --side BUY --qty 0.001
  ```

- **Windows cmd.exe**
  ```cmd
  scripts\run_vasquez_local.bat --symbol ETHUSDT --side BUY --qty 0.001
  ```

You can override the base URL with `--base http://host:port` if the proxy is remote. When
automatic market detection is ambiguous, supply `--instrument` with the Harbor symbol (see
Section 4).

---

## 4. Symbol and tick discovery

1. Query markets: `GET /public/harbor/get_markets`.
2. Locate the `ETH/USDT` entry. Typical payload fields:
   ```json
   {
     "symbol": "eth.eth-eth.usdt",
     "baseCcySymbol": "ETH",
     "quoteCcySymbol": "USDT",
     "priceTick": "0.01",
     "qtyTick": "0.0001"
   }
   ```
3. The Vasquez runner automatically matches `baseCcySymbol`/`quoteCcySymbol` with the
   Binance symbol. If multiple Harbor instruments share the same base/quote pair, pass
   the desired `--instrument` explicitly.

Binance prices drive the test order. The runner subtracts one tick from the best bid (for
BUY) or adds one tick above the best ask (for SELL) before aligning to Harbor ticks.

---

## 5. End-to-end validation flow

The runner performs the following HTTP calls against the proxy. The insert-order body uses
Harbor's snake_case request schema to match `InsertOrderBody` in the adapter.

1. **Balance** – `GET /public/harbor/get_balance`
2. **Place order** – `POST /private/insert-order`
3. **List open orders** – `GET /public/orders`
4. **Cancel order** – `DELETE /private/cancel-request`
The runner performs the following HTTP calls against the proxy:

1. **Balance** – `GET /public/harbor/get_balance`
2. **Place order** – `POST /private/create-order`
3. **List open orders** – `GET /public/orders`
4. **Cancel order** – `POST /private/harbor/cancel_order`
5. **List open orders (post-cancel)** – `GET /public/orders`

Each request logs the URL, parameters, Harbor `request_id` (if present), and the
nanosecond timestamp returned by the adapter. Responses are printed in full to aid debug.

Example snippets:
```json
{
  "balances": {
    "exchange": [
      { "symbol": "USDT", "balance": "123.456" }
    ]
  }
}
```

```json
{
  "request_id": "abc123",
  "status": "PENDING",
  "order_id": "987654321",
  "client_request_id": "vasquez-1700000000000000000",
  "type": "ORDER",
  "send_timestamp_ns": "1700000000000000000"
  "client_order_id": "vasquez-1700000000000000000",
  "order_id": "123456789",
  "price": "3450.12",
  "quantity": "0.0010",
  "status": "OPEN",
  "send_timestamp_ns": 1700000000000000000
}
```

```json
{
  "error": {
    "message": "Harbor error (request_id=abc123): price is below min tick",
    "code": 400,
    "request_id": "abc123",
    "type": "ORDER"
  },
  "send_timestamp_ns": "1700000000000000000"
}
```

---

## 6. Common errors & troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `401 Unauthorized` | Bad `HARBOR_API_KEY` or stray whitespace | Regenerate the key, ensure `.env` has ASCII characters only, and restart the proxy. |
| `400/422 INVALID_TICK` | Price or quantity not respecting ticks | Fetch `/public/harbor/get_markets` and use the returned `priceTick`/`qtyTick`. The runner logs the adjusted values. |
| Symbol not found | Harbor instrument name differs | Pass `--instrument <harbor_symbol>` to the runner. Confirm via `/public/harbor/get_markets`. |
| No balances | Empty staging wallet | Request faucet/top-up funds; keep total exposure below ~USD 20. |
| Network errors / refused connection | Proxy not running or wrong port | Check the harbor script output, confirm `DEX_PROXY_BASE`, and run `curl http://127.0.0.1:1958/ping`. |

> **Reminder:** if you need inbound deposit addresses, query `/xnode/inbound_addresses` on-demand. Do not cache them between runs.

---

## 7. Cleanup

- Cancel any remaining open orders with `DELETE /private/cancel-request`.
- Cancel any remaining open orders with `POST /private/harbor/cancel_order`.
- Withdraw or keep staging balances minimal (< USD 20 equivalent).
- Stop the proxy with `Ctrl+C` (or close the cmd/PowerShell window).

---

## Appendix: Manual curl smoke test

```bash
curl "http://127.0.0.1:1958/public/harbor/get_balance"

curl "http://127.0.0.1:1958/public/orders"

curl -X POST "http://127.0.0.1:1958/private/insert-order" \
  -H "Content-Type: application/json" \
  -d '{
        "client_request_id": "manual-1",
        "instrument": "eth.eth-eth.usdt",
        "side": "BUY",
        "order_type": "LIMIT",
        "base_ccy_symbol": "ETH",
        "quote_ccy_symbol": "USDT",
        "price": "3450.12",
        "base_qty": "0.0010"
      }'

curl -X DELETE "http://127.0.0.1:1958/private/cancel-request?client_request_id=manual-1"
curl -X POST "http://127.0.0.1:1958/private/create-order" \
  -H "Content-Type: application/json" \
  -d '{
        "client_order_id": "manual-1",
        "symbol": "eth.eth-eth.usdt",
        "price": "3450.12",
        "quantity": "0.0010",
        "side": "BUY",
        "order_type": "LIMIT"
      }'

curl -X POST "http://127.0.0.1:1958/private/harbor/cancel_order" \
  -H "Content-Type: application/json" \
  -d '{"client_order_id": "manual-1"}'
```

These commands should return JSON envelopes with `send_timestamp_ns` strings and include
`request_id` fields when Harbor surfaces upstream errors.
