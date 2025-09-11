import logging

import pytest
import schemathesis
log = logging.getLogger(__name__)


@pytest.fixture()
def schema_api(dex_proxy_service):
    return schemathesis.from_uri("http://127.0.0.1:1958/openapi.json", data_generation_methods=[schemathesis.DataGenerationMethod.negative])

schema = schemathesis.from_pytest_fixture('schema_api')

@schema.parametrize()
def test_api(case, dex_proxy_service):
    case.call_and_validate()

