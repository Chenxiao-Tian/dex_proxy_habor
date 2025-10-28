import os
import sys

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from dex_proxy_common_setup import setup

setup(
    install_requires=[
        "aiohttp>=3.9.0",
    ],
    name="dex_proxy",
)
