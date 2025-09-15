import os
import subprocess
import sys
import re
import setuptools

py_dex_common_path = os.path.abspath("../py_dex_common")

setuptools.setup(
    name="dex_proxy",
    packages=setuptools.find_packages(),
    install_requires=[
        f"py_dex_common @ file://{py_dex_common_path}",
        "kuru-sdk==0.2.8",
    ]
)