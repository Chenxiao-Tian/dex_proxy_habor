"""Minimal subset of pyutils.exchange_apis.dex_common used for Harbor tests."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Tuple


class RequestStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class _RequestTypeItem:
    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - convenience
        return f"RequestType.{self.name}"


class RequestType:
    ORDER = _RequestTypeItem("ORDER")
    TRANSFER = _RequestTypeItem("TRANSFER")
    APPROVE = _RequestTypeItem("APPROVE")
    WRAP_UNWRAP = _RequestTypeItem("WRAP_UNWRAP")
    CANCEL = _RequestTypeItem("CANCEL")

    def __getitem__(self, item: str) -> _RequestTypeItem:
        return getattr(self, item)


@dataclass
class Request:
    client_request_id: str = ""
    request_type: _RequestTypeItem = RequestType.ORDER
    request_status: RequestStatus = RequestStatus.SUCCEEDED
    nonce: int | None = None
    tx_hashes: List[Tuple[str | None, str]] | None = None
    used_gas_prices_wei: List[int] | None = None
    dex_specific: Dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.tx_hashes = list(self.tx_hashes or [])
        self.used_gas_prices_wei = list(self.used_gas_prices_wei or [])
        self.dex_specific = dict(self.dex_specific or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_request_id": self.client_request_id,
            "request_type": self.request_type.name,
            "request_status": self.request_status.value,
            "nonce": self.nonce,
            "tx_hashes": self.tx_hashes,
            "used_gas_prices_wei": self.used_gas_prices_wei,
            "dex_specific": self.dex_specific,
        }

    def is_finalised(self) -> bool:
        return self.request_status in {RequestStatus.SUCCEEDED, RequestStatus.FAILED, RequestStatus.CANCELED}

    def finalise_request(self, status: RequestStatus) -> None:
        self.request_status = status


class _JsonBackedRequest(Request):
    @classmethod
    def from_json(cls, payload: Dict[str, Any]) -> "_JsonBackedRequest":
        request_type_name = payload.get("request_type", "ORDER")
        instance = cls(
            client_request_id=payload.get("client_request_id", ""),
            request_type=RequestType[request_type_name],
            request_status=RequestStatus(payload.get("request_status", RequestStatus.SUCCEEDED.value)),
            nonce=payload.get("nonce"),
            tx_hashes=list(payload.get("tx_hashes", [])),
            used_gas_prices_wei=list(payload.get("used_gas_prices_wei", [])),
            dex_specific=dict(payload.get("dex_specific", {})),
        )
        return instance


class OrderRequest(_JsonBackedRequest):
    pass


class TransferRequest(_JsonBackedRequest):
    pass


class ApproveRequest(_JsonBackedRequest):
    pass


class WrapUnwrapRequest(_JsonBackedRequest):
    pass


__all__ = [
    "ApproveRequest",
    "OrderRequest",
    "Request",
    "RequestStatus",
    "RequestType",
    "TransferRequest",
    "WrapUnwrapRequest",
]
