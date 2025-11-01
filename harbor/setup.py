import os
import sys
import setuptools

# Ensure dex-proxy root path is available (for relative imports if needed)
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# --- Use setuptools directly (skip dex_proxy_common_setup) ---
setuptools.setup(
    name="harbor",
    version="0.1.0",
    packages=setuptools.find_packages(),
    install_requires=[
        # 注意：路径请保持斜杠 / 格式，且 py_dex_common 名称必须与文件夹一致
        "py_dex_common @ file://C:/Users/92585/new3/dex-proxy/py_dex_common",
        "aiohttp>=3.9.0",
    ],
    python_requires=">=3.10",
    description="Harbor DEX adapter for dex-proxy",
)
