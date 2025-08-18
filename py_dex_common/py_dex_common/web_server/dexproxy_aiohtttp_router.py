import logging
from http import HTTPStatus
from typing import Any

from aiohttp import web
from fastopenapi.routers import AioHttpRouter

_logger = logging.getLogger(__name__)

class DexProxyAioHttpRouter(AioHttpRouter):
    def __init__(self, app: web.Application = None, **kwargs):
        super().__init__(app, **kwargs)

    def _build_responses(self, meta: dict, definitions: dict, status_code: str) -> dict:
        """Adding response_errors handling additionaly to parent implementation."""

        responses = super()._build_responses(meta, definitions, status_code)

        if 'response_errors' in meta and len(meta['response_errors']) > 0:
            for code in meta['response_errors']:
                if int(code) >= 400:
                    if 'model' in meta['response_errors'][code] and 'model' in meta['response_errors'][code]['model']:
                        model = meta['response_errors'][code]['model']['model']
                        error_schema = self._get_model_schema(model, definitions)
                        _logger.debug(f"Error schema for {model.__name__}: {error_schema}")

        return responses

    def _build_error_responses(self, meta) -> dict[str, Any]:
        """Redefine parent implementation."""

        errors_responses = {}
        if 'response_errors' in meta and len(meta['response_errors']) > 0:
            for code in meta['response_errors']:
                if int(code) >= 400:
                    if 'model' in meta['response_errors'][code] and 'model' in meta['response_errors'][code]['model']:
                        model = meta['response_errors'][code]['model']['model']
                        error_ref = {"$ref": f"#/components/schemas/{model.__name__}"}
                        status = HTTPStatus(int(code))
                        errors_responses[str(code)] = {
                            "description": status.phrase,
                            "content": {"application/json": {"schema": error_ref}},
                        }
        return errors_responses