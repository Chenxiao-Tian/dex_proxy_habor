import os
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)
from dex_proxy_common_setup import setup

extras_require = {
    "dev": [
        "pytest==8.4.2",
        "pytest-asyncio==1.2.0",
        "pytest-xprocess==1.0.2",
        "pytest-aiohttp==1.0.5",
        "aiofiles==24.1.0"
    ]
}

setup(
    [
        "pyutils[web3] @ git+ssh://git@bitbucket.org/kenetic/pyutils.git@pyutils-1.18.17",
        "anchorpy==0.21.0",
        "driftpy==0.8.68"
    ],
    extras_require=extras_require
)
