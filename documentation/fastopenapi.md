## OpenAPI Schema Validation and Documentation using FastOpenAPI with aiohttp

### Overview

This project uses `fastopenapi` together with `aiohttp` to:

- **Enforce runtime request/response validation** using [Pydantic](https://docs.pydantic.dev/latest/) models.
- **Automatically generate OpenAPI 3 documentation** from the registered routes and attached schemas.
- **Organize endpoints** by logical categories via tagging.

The FastOpenAPI-powered aiohttp server listens on **port `1958`** and supports both **shared** and **DEX-specific** API schemas.

* * *

### Directory Structure and Schema Layout

Each DEX has its own module with a structure similar to:

```
├── edex/
│   ├── edex_dex_proxy.py     # The entry point
│   ├── edex.py               # The aiohttp handler/registration logic
│   ├── edex.config.json      # DEX-specific configuration
│   ├── schemas/              # Pydantic models for this DEX's endpoints
│   │   ├── cancels.py
│   │   ├── initialize_user.py
│   │   ├── margin_trading.py
│   │   ├── portfolio.py
│   │   ├── contract_data.py
│   │   ├── order_trade.py
│   │   ├── public_records.py
│   │   ├── transfers.py
│   │   └── __init__.py
```

Shared/common Pydantic types live in:

```
py_dex_common/py_dex_common/schemas
```

This file contains widely used request and response models such as:

- `ApproveTokenRequest`
- `TxResponse`
- `TransferParams`
- `TransferResponse`

* * *

### Endpoint Registration

FastOpenAPI allows seamless integration with aiohttp by providing an extension to register endpoints with optional validation and documentation metadata.

#### Basic Registration (no schema validation)

You can register endpoints exactly as before:

```python
self._server.register('POST', '/private/approve-token', self.__approve_token)
```

This continues to work but does not provide schema enforcement or documentation.

* * *

#### Validated and Documented Registration

When `request_model`, `response_model`, and `oapi_in` are supplied, the handler enforces full Pydantic validation on incoming requests and outgoing responses. Example:

```python
oapi_support = ["edex"]  # typically inferred from DEX name

self._server.register(
    'POST', '/private/approve-token', self.__approve_token,
    request_model=common_schemas.ApproveTokenRequest,
    response_model=common_schemas.TxResponse,
    summary="Approve ERC20 allowance",
    tags=["private"],
    oapi_in=oapi_support
)
```

This ensures:

- Incoming request JSON or query params are parsed into the provided request model and validated.
- Response must conform to the given response model.
- An OpenAPI summary and `POST /private/approve-token` endpoint is generated under the **"private"** tag in the Swagger UI.

* * *

### Runtime Validation

If validation fails on input:

- The server **automatically returns 400** with a validation error message.

If the handler's return type is incompatible with the response model:

- An **internal server error** or schema mismatch warning is raised.

* * *

### Tags and Summary

- `summary`: A short description shown in the OpenAPI UI.
- `tags`: Used to group endpoints logically in the documentation UI, e.g., "private", "public", "margin", etc.

These fields are optional for code execution, help organize the documentation, and are also used by external developers accessing the OpenAPI interface.

* * *

### Swagger and "Try Me" Integration

FastOpenAPI provides an automatically generated **Swagger UI**, accessible from the server's documentation endpoint. This interface supports the "Try Me" feature, allowing users to:

- Interactively call endpoints with generated example data.
- View structured request/response models.
- Automatically populate request bodies from the `example` values declared in each Pydantic model.

All documented endpoints include example values and return schemas to ensure Swagger's "Try it out" behaves consistently.

* * *

### Redoc Support

In addition to Swagger, FastOpenAPI serves a **Redoc** documentation view. Redoc provides a clean, responsive layout ideal for read-only API exploration. It is also used by external developers.

* * *

### Documentation Endpoints

The following endpoints are available for accessing the OpenAPI interface:

- **Swagger UI**: http://<hostname>:1958/docs</hostname>
- **Redoc UI**: http://<hostname>:1958/redoc</hostname>
- **Raw OpenAPI schema (JSON)**: http://<hostname>:1958/openapi.json</hostname>

Replace `<hostname>` with your actual server hostname. For example:

- Swagger: http://devhost.internal:1958/docs
- Redoc: http://devhost.internal:1958/redoc
- OpenAPI JSON: http://devhost.internal:1958/openapi.json

* * *

### Benefits

- **Zero-maintenance documentation**: OpenAPI is generated directly from registration metadata.
- **Runtime safety**: Guarantees that incoming data conforms to expected shapes and that all documented output is accurate.
- **Consistency**: Ensures schema definitions stay in sync with the code handling them.
- **Swagger & Redoc**: Offers both interactive (Swagger) and static (Redoc) views for development and integration.

* * *

### Example: Schema Enforcement in Practice

**common_schemas.py**

```python
from pydantic import BaseModel

class ApproveTokenRequest(BaseModel):
    token: str
    amount: int

class TxResponse(BaseModel):
    status: str
    txid: str
```

**edex.py**

```python
self._server.register(
    'POST', '/private/approve-token', self.__approve_token,
    request_model=common_schemas.ApproveTokenRequest,
    response_model=common_schemas.TxResponse,
    summary="Approve ERC20 allowance",
    tags=["private"],
    oapi_in=["edex"]
)
```

**Effect**:

- Request must be a JSON object like:

```json
{ "token": "USDC", "amount": 100000 }
```

- Response must be a JSON object like:

```json
{ "status": "success", "txid": "0xabc123" }
```


