import os
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)
from dex_proxy_common_setup import setup

setup(
    [
        "msgpack==1.0.8",
        "orjson==3.10.18",
        "fastopenapi",
        "pydantic>=2.0",
        "eth-account>=0.9",
    ],
    name="py_dex_common",
)
