import os
import subprocess
import sys

import setuptools


def run(*cmd):
    wd = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, cwd=wd)
    return p.stdout.read().decode().rstrip()


tag = run("git", "for-each-ref", "--format=%(refname:short)", "--sort=-authordate", "--count=1", "refs/tags")
rev = run("git", "rev-parse", "--short=8", "HEAD")

setuptools.setup(
    name="dex_proxy",
    version=f"{tag}+{rev}",
    py_modules=[],
    install_requires=[
        'msgpack==1.0.8',
        "pyutils @ git+ssh://bitbucket.org/kenetic/pyutils.git@pyutils-1.11.16"
    ]
)
