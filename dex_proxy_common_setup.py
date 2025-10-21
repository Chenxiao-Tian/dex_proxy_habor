import os
import setuptools
import subprocess
from typing import List, Optional, Dict


def _run(*cmd):
    wd = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, cwd=wd)
    return p.stdout.read().decode().rstrip()


def setup(install_requires: List[str], name: str = "dex_proxy", extras_require: Optional[Dict[str, List[str]]] = None):
    version = _run("git", "rev-parse", "--short=7", "HEAD")

    if name != "py_dex_common":
        py_dex_common_path = os.path.abspath("../py_dex_common")
        install_requires.append(f"py_dex_common @ file://{py_dex_common_path}")

    setuptools.setup(
        name=name,
        version=f"0.0.0+{version}",
        packages=setuptools.find_packages(),
        install_requires=install_requires,
        extras_require=extras_require,
    )
