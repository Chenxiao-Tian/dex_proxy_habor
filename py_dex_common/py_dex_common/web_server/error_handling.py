from typing import Any, Union

from fastopenapi.error_handler import APIError
from pydantic import BaseModel


class DexProxyGenericAPIError(APIError):
    def __init__(self, error_data: Union[dict[str, Any], BaseModel], status_code: int = 500):
        self.status_code = status_code
        self.error_data = error_data

    def to_response(self) -> dict[str, Any]:
        if isinstance(self.error_data, BaseModel):
            return self.error_data.model_dump(mode="json")
        else:
            return self.error_data

