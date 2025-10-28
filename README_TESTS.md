# Tests

## Alternative environment for tests

- Install `uv` tool
    - `pip install uv`
- Install Python 3.10 and create venv
    - `uv python install 3.10`
    - `uv venv --prompt "dex_proxy" --python 3.10 .venv`
    - `uv pip install "setuptools==80.9.0"`
- Change directory to a specific DEX, e.g. `cd ethereal`
- Install dependencies
    - `uv pip install ".[dev]"`


## Modes of Running Functional Tests

Test may be run in two modes:

### 1. External (default) – proxy runs as separate process
- Make targets:
    - `make test-functional` (basic run)
    - `make test-functional-outside` (run against externally started dex_proxy; uses --outside-proxy-host/--outside-proxy-port)
    - `make test-functional-verbose` (adds -s -p no:logging)
- Direct Pytest:
    - `pytest tests/functional`
    - `pytest -s -p no:logging tests/functional`
- With explicit config (relative to the DEX directory, e.g ethereal/ dir):
    - `pytest -s -p no:logging tests/functional --dex-proxy-config=ethereal.config.json`
- Outside proxy (connect to an already running dex_proxy; tests won't spawn xprocess):
    - `pytest tests/functional --outside-proxy-host=localhost --outside-proxy-port=1958`
    - `pytest -s -p no:logging tests/functional --outside-proxy-host=localhost --outside-proxy-port=1958`

Behavior:
- Starts Dex Proxy once (managed by xprocess) before tests and shuts it down after suite.
- Faster overall; state persists across tests
- To reuse an already running proxy instead of xprocess, pass --outside-proxy-host/--outside-proxy-port (see examples below). In that case, tests connect to the specified host:port and do not spawn the proxy.

View proxy logs (xprocess-managed only):
- `make logs-test-xprocess` (opens with `less`)

### 2. Internal – proxy in same process / per test function
- Make target:
    - `make test-functional-internal`
- Direct Pytest:
    - `pytest -s -p no:logging --internal-proxy=True tests/functional`
    - `pytest -s -p no:logging --internal-proxy=True --dex-proxy-config=ethereal.config.json tests/functional`

Behavior:
- Spins up the proxy inside the pytest process per test function.
- Used for tighter event loop integration & debugging subtle async issues.
- Slower; state isolation between tests.

## Debugging in VSCode

You can debug tests in VSCode by setting up a launch configuration in `.vscode/launch.json`:

```json
{
    "name": "Pytest: Debug Tests External",
    "type": "debugpy",
    "request": "launch",
    "program": "${file}",
    "purpose": ["debug-test"],
    "env": {
      "PYTEST_ADDOPTS": "-s -p no:logging --internal-proxy=True"
    },
    "cwd": "${workspaceFolder}/dex_dir/",
    "justMyCode": false,
    "console": "integratedTerminal"
}
```

This configuration:
- Uses the `debugpy` debugger for Python
- Runs the currently open test file (`${file}`)
- Sets pytest options via `PYTEST_ADDOPTS` environment variable
- Uses internal proxy mode for easier debugging (`--internal-proxy=True`)
- Sets working directory to `dex_dir/` subdirectory
- Allows debugging into library code (`justMyCode: false`)

To use: Open a test file, set breakpoints, and run the debug configuration from VSCode's Run and Debug panel. This configuration will also be automatically used when debugging tests from VSCode's Testing panel because `"purpose": ["debug-test"]` is set.

## Optional Flags
- `--dex-proxy-config=<file>`: Override default config. Path is resolved relative to the dex_dir/ dex root (working dir when using Make targets).
- `--internal-proxy=True`: Switch to internal mode (see above).
- `--outside-proxy-host=<host>`: Connect tests to an already running dex_proxy instead of spawning via xprocess (external mode variant).
- `--outside-proxy-port=<port>`: Port of the already running dex_proxy. Typical: 1958 (see *.config.json server.port).

## Defaults (pytest.ini)
Default values for these custom options are set in `dex_dir/pytest.ini` so you usually don't need to pass them explicitly:
```
dex-proxy-config = dex.config.json
internal-proxy = False
outside-proxy-host =
outside-proxy-port =
```
Notes:
- If you intend to connect to an outside proxy, set both outside-proxy-host and outside-proxy-port. The default port in dex_dir/*.config.json ("server.port") is 1958.

Override any of them on the command line, e.g.:
```
# Use internal mode
pytest -s -p no:logging tests/functional --internal-proxy=True

# Use outside proxy (already running at localhost:1958)
pytest -s -p no:logging tests/functional --outside-proxy-host=localhost --outside-proxy-port=1958
```

## Skipping Tests in CI/CD

Functional tests run in the `test` stage of the GitLab CI/CD pipeline. **Important: Test jobs do not block build jobs** - they run in parallel, so builds proceed regardless of test results (see [`.gitlab-ci.yml`](.gitlab-ci.yml) stages configuration).

However, you can skip running functional tests entirely using one of the following methods:

### Method 1: Pipeline Parameter

When manually triggering a pipeline, set the `SKIP_FUNC_TESTS` variable:

- **Skip all tests**: Set `SKIP_FUNC_TESTS` to `all`
- **Skip specific DEX tests**: Set `SKIP_FUNC_TESTS` to the DEX name(s), e.g.:
    - `drft` - skips only drft tests
    - `drft,ethereal` - skips multiple DEX tests (comma-separated)

### Method 2: Commit Message Marker

Include a skip marker in your commit message:

- **Skip drft tests**: Include `[skip-func-tests-drft]` in the commit message
- **Skip ethereal tests**: Include `[skip-func-tests-ethereal]` in the commit message

Example:
```bash
git commit -m "feat: update config [skip-func-tests-drft]"
```
