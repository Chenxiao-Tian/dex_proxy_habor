import os
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)
from dex_proxy_common_setup import setup

uniswap_shared_path = os.path.abspath("../uniswap_shared")

setup(
    [
        f"uniswap_shared @ file://{uniswap_shared_path}",
        "pyutils[web3] @ git+ssh://git@bitbucket.org/kenetic/pyutils.git@pyutils-1.18.17",
    ]
)
