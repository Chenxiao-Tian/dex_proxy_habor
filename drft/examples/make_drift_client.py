import json
from pathlib import Path

from dex_proxy.drift_api import DriftApi
from dex_proxy.drift_connector import DriftConnector, DriftConfiguration

from anchorpy import Wallet
from solders.keypair import Keypair


def get_config() -> dict:
    config_file = "../drft.config.json"
    path = Path(__file__).parent / config_file
    with open(path) as f:
        config = json.load(f)

    config = config["dex"]
    return config


def load_config() -> DriftConfiguration:
    config = get_config()
    return DriftConfiguration(
        url=config["url"],
        public_key=config["clients_pool"]["public_key"],
        env=config["env"],
        subaccount=config["clients_pool"]["subaccount"],
    )


def get_secret() -> list:
    config = get_config()
    wallet = Wallet(Keypair.from_base58_string(config["_private_key"]))

    frame = wallet.payer.to_bytes()
    secret = [x for x in frame]
    return secret


async def make_drift_client() -> DriftApi:
    config = load_config()
    secret = get_secret()
    client = await DriftConnector(config).get_connection(secret=secret)
    client.show_user_info()
    return DriftApi(client)
