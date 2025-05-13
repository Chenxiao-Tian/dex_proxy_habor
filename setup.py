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
        'orjson==3.6.1',
        # workaround; discussion in link below
        # https://auros-group.slack.com/archives/C039ZE7QS56/p1740366619748929
        "kafka-python==2.0.2",
        "pyutils @ git+ssh://git@bitbucket.org/kenetic/pyutils.git@pyutils-1.14.3"
    ]
)
