import logging
import sys
import json
import os
from eth_account import Account

# TO investigate how to set the following option by configuring pytest https://docs.pytest.org/en/stable/how-to/logging.html
# from the first time it did not work

def configure_test_logging():
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s [%(name)s]')

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

def read_config():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    config_path = os.path.join(project_root, 'dexes', 'kuru', 'kuru.local.config.json')
    with open(config_path, 'r') as f:
        config_data = json.load(f)
    wallet_path = os.path.join(project_root, 'dexes', 'kuru', 'test-local-wallet.json')
    with open(wallet_path, 'r') as f:
        wallet_data = json.load(f)
    private_key_hex = Account.decrypt(wallet_data, "").hex()
    return config_data, private_key_hex