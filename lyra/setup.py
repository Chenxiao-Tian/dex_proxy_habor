import os
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)
from dex_proxy_common_setup import setup

setup(
    [
        "pyutils[web3] @ git+ssh://git@bitbucket.org/kenetic/pyutils.git@pyutils-1.18.11",
        "websockets==10.4"
    ]
)
