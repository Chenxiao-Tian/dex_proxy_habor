## Synfutures Dex Proxy

### Setup
See ts/README.md

### Endpoints
1. `GET /status`
    - Description:
      - Used to confirm that the dex_proxy is alive and accepting user requests.
    - Response Schema:
      ```
      {
        "status": "ok"
      }
      ```
