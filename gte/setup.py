import os
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)
from dex_proxy_common_setup import setup

setup(
    [
        "gte-py @ git+https://github.com/liquid-labs-inc/gte-python-sdk.git@497f09a46dbf99ca22e4119b5865d1ff67d69b8f"
    ]
)
