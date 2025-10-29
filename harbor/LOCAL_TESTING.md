# Harbor Connector Local Testing Guide

This guide explains how to exercise the Harbor adapter inside the `dex-proxy` framework using
command-line tools on a development workstation. The commands assume you are in the
repository root and have Python 3.11+ available.

## 1. Environment preparation

1. Create a virtual environment and install the shared stubs + Harbor package in editable mode:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e py_dex_common
   pip install -e harbor
   ```

   > **Note**
   >
   > The repository now bundles light-weight replacements for the internal
   > `pantheon`, `pyutils`, `fastopenapi`, `aiohttp`, and related dependencies
   > so that editable installs work on machines without access to the private
   > Bitbucket/GitLab packages. Installing the two editable packages above is
   > sufficient for local smoke tests.
   >
   > On Windows `cmd.exe`/PowerShell the same commands work; ensure you run
   > them from the repository root so the helper can resolve the local
   > dependencies. No manual `PYTHONPATH` adjustments are required.

2. Export the Harbor API key that was issued for the staging environment:

   ```bash
   export HARBOR_API_KEY="<your-stagenet-api-key>"
   ```

   The config file `harbor/harbor.config.json` reads the key from this environment variable.

## 2. Running the proxy service

Launch the aiohttp web server that exposes the dex-proxy endpoints:

```bash
python -m dex_proxy.main -s -c harbor/harbor.config.json -n harbor
```

Useful flags:

- `-s` starts the service in the foreground.
- `-c` points to the Harbor-specific config.
- `-n harbor` advertises the service name to Pantheon.

The process only needs the keystore listed in the config (`kuru/test-local-wallet.json`), which is
already part of the repository for local testing. Press `Ctrl+C` (or close the
PowerShell window) to terminate the service when you are done testing.

## 3. HTTP smoke tests

With the server running locally (default `http://localhost:1958`), you can perform quick
sanity checks using `curl`:

```bash
curl "http://localhost:1958/ping"

curl "http://localhost:1958/public/harbor/get_balance"

curl -X POST "http://localhost:1958/private/harbor/create_order" \
  -H 'Content-Type: application/json' \
  -d '{
        "client_order_id": "demo-1",
        "symbol": "btc.btc-eth.usdt",
        "price": "100000.00",
        "quantity": "0.0002",
        "side": "BUY",
        "order_type": "LIMIT"
      }'
```

If a parameter violates Harbor tick sizes the adapter returns a 400 with a descriptive error
message including the Harbor request id when available.

To cancel an order, issue:

```bash
curl -X POST "http://localhost:1958/private/harbor/cancel_order" \
  -H 'Content-Type: application/json' \
  -d '{"client_order_id": "demo-1"}'
```

Retrieve live orders:

```bash
curl "http://localhost:1958/private/harbor/list_open_orders"
```

Fetch a depth snapshot:

```bash
curl "http://localhost:1958/public/harbor/get_depth_snapshot?symbol=btc.btc-eth.usdt"
```

> **Compatibility note:** Legacy paths such as `/public/balance` and
> `/public/depth` remain available, but new development should target the
> `/harbor/` namespaced endpoints demonstrated above.

## 4. Demo script (place + cancel)

The script `harbor/demo_place_cancel.py` demonstrates placing a limit order and canceling it
via the raw Harbor REST API. Run it with the required environment variables:

```bash
export HARBOR_API_KEY="<your-stagenet-api-key>"
python harbor/demo_place_cancel.py --symbol btc.btc-eth.usdt --price 100000 --quantity 0.0002
```

Optional flags:

- `--side BUY|SELL` defaults to `BUY`.
- `--time-in-force` defaults to `gtc`.

The script prints the JSON responses for the create and cancel calls and exits with a non-zero
code if Harbor returns an error.

## 5. Automated tests

The Harbor adapter ships with pytest coverage focused on HTTP behaviour. Execute them with:

```bash
pytest -q tests/harbor
```

The tests use asyncio and stubbed HTTP clients, so no real network calls are made.
