import logging

from aiohttp import web

from dexes.kuru.tests.common import configure_test_logging
from schemas import OrderErrorResponse
from web_server.dexproxy_aiohtttp_router import DexProxyAioHttpRouter

configure_test_logging()

logger = logging.getLogger(__name__)

class TestDexProxyAioHttpRouter:
    def test__build_responses(self):
        router = DexProxyAioHttpRouter()

        meta = {
            'response_errors': {
                400: {
                    'model': {
                        'model': OrderErrorResponse
                    }
                },
            },
        }
        definitions = {}
        router._build_responses(meta, definitions, '200')

        logger.info(f"responses: {definitions}")

        assert OrderErrorResponse.__name__ in definitions
        assert definitions[OrderErrorResponse.__name__]['title'] == OrderErrorResponse.__name__
        assert len(definitions) > 0


    def test__build_error_responses(self):
        router = DexProxyAioHttpRouter()

        meta = {
            'response_errors': {
                400: {
                    'model': {
                        'model': OrderErrorResponse
                    }
                },
                404: {
                    'model': {
                        'model': OrderErrorResponse
                    }
                },
            },
        }
        error_responses = router._build_error_responses(meta)

        logger.info(f"responses: {error_responses}")

        assert len(error_responses) > 0
        assert error_responses['400']['description'] == 'Bad Request'
        assert error_responses['404']['description'] == 'Not Found'

