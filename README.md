# Tests

## Install environment for tests

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

# Development Guide

### Development via localhost (This won't be possible for some projects like 'paradex' due to some dependency issues)
- Navigate to the project you are working on
  - ```cd gte```
  - Create virtual environment
  - ```python3 -m venv venv```
  - ```source venv/bin/activate```
- Make sure you are using correct `pip` and `setuptools` versions:
  - ```pip install pip==22.3.1 setuptools==59.6.0```
- Install in editable mode (changes to the dex you are working on are seen immediately in the environment):
  - ```pip install -e .```

- Run your dex
  - ```python3 -u -m dex_proxy.main -s -c gte.config.json -n gte```

- Navigate to the openapi webpage to test the endpoints
  - ```http://localhost:1958/docs```

### Development via docker

- Our recommended development environment is through ```Dockerfile.local```
- Following steps assume ```dex_proxy``` repo as a working directory


#### GTE
- Building the image
  - ```docker build -t dex-proxy-gte -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:22222:22 -p 127.0.0.1:2958:2958 --name dex-proxy-gte -d dex-proxy-gte```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 22222```
- While inside the container
  - ```cd gte```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c gte/gte.config.json -n gte```

#### Paradex
- Building the image
  - ```docker build -t dex-proxy-pdex -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:32222:22 -p 127.0.0.1:3958:3958 --name dex-proxy-pdex -d dex-proxy-pdex```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 32222```
- While inside the container
  - ```cd paradex```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c paradex.config.json -n pdex```

#### Hype
- Building the image
  - ```docker build -t dex-proxy-hype -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:42222:22 -p 127.0.0.1:4958:4958 --name dex-proxy-hype -d dex-proxy-hype```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 42222```
- While inside the container
  - ```cd hype```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c hype.config.json -n hype```

#### Lyra
- Building the image
  - ```docker build -t dex-proxy-lyra -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:52222:22 -p 127.0.0.1:5958:5958 --name dex-proxy-lyra -d dex-proxy-lyra```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 52222```
- While inside the container
  - ```cd lyra```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c lyra.config.json -n lyra```

#### Native
- Building the image
  - ```docker build -t dex-proxy-native -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62222:22 -p 127.0.0.1:6958:6958 --name dex-proxy-native -d dex-proxy-native```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62222```
- While inside the container
  - ```cd native```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c native.config.json -n native```

#### Per
- Building the image
  - ```docker build -t dex-proxy-per -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62223:22 -p 127.0.0.1:7958:7958 --name dex-proxy-per -d dex-proxy-per```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62223```
- While inside the container
  - ```cd native```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c per.config.json -n per```


#### Uni3
- Building the image
  - ```docker build -t dex-proxy-uniswap_v3 -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62224:22 -p 127.0.0.1:8958:7958 --name dex-proxy-uniswap_v4 -d dex-proxy-uniswap_v3```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62224```
- While inside the container
  - ```cd uniswap_v3```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c uniswap_v3-arbitrum.config.json -n uniswap_v3```

#### Uni4
- Building the image
  - ```docker build -t dex-proxy-uniswap_v4 -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62225:22 -p 127.0.0.1:9958:9958 --name dex-proxy-uniswap_v4 -d dex-proxy-uniswap_v4```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62225```
- While inside the container
  - ```cd uniswap_v4```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c uniswap_v4.config.json -n uniswap_v4```

#### Vert
- Building the image
  - ```docker build -t dex-proxy-vert -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62226:22 -p 127.0.0.1:10958:10958 --name dex-proxy-vert -d dex-proxy-vert```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62226```
- While inside the container
  - ```cd vert```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c vert.config.json -n vert```

#### Drft
- Building the image
  - ```docker build -t dex-proxy-drft -f ./Dockerfile.local .```
- Running the container starts an image with an ```sshd``` listening binded to the host network
  - ```docker run --volume ./:/app/auros -p 127.0.0.1:62227:22 -p 127.0.0.1:11958:11958 --name dex-proxy-drft -d dex-proxy-drft```
- Attaching to an image can be accomplished with ```ssh``` (this allows us to forward ```ssh-agent``` through ```ssh```)
  - ```ssh -o NoHostAuthenticationForLocalhost=yes -A root@localhost -p 62227```
- While inside the container
  - ```cd drft```
  - ```pip install .```
  - ```python3 -u -m dex_proxy.main -s -c drft.config.json -n drft```

#### Notes
- We are mounting our working directory directly to the image so you shouldn't need to rebuild the image to develop
- We assume existence of valid ssh keys in the host ```ssh-agent``` and they are forwarded to the ```sshd``` inside the Docker image
- If you are on MacOS you are probably using ```podman``` and want to replace ```docker``` accordingly
- If you are having dns problems inside container, you should try running the container with ```--net=host``` to bridge the network interfaces



### Verifying Exchange Whitelists in the resources directory
- Checks to be performed by reviewers:
  - Verify that ```token contract addresses``` are present in the ```token_contracts``` table in the ```prod TradingDB```.
  ```postgresql
  select  address, token_name, chain, added_timestamp from token_contracts where chain='<chain_name>' and address='<address>' and token_name='<token_name>';
  ```
  - Verify that ```pool adresses``` are present in the ```pools``` table in the ```prod TradingDB```.
  ```postgresql
  select id, address, dex_name, chain from pools where chain='<chain_name>' and dex_name='<dex_name>' and address='<address>';
  ```
  - Verify that the ```withdrawal_addresses``` are present in the ```exchange_addresses``` table in the ```prod TradingDB```.
  ```postgresql
  select account, token, address from exchange_addresses where token='<token_name>' and address='<address>';
  ```
  - Verify the existence and correctness of the addresses on chain using a ```block explorer```.
