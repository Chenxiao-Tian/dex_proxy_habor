"""Shared setup helpers for editable installs used in local testing.

The real dex-proxy repository depends on a number of internal packages that
are not available in this kata environment.  In order to keep the same
``setup.py`` entry points we expose a tiny helper that mirrors the behaviour
of the real project while remaining self-contained.

Historically this helper returned the seven-character git hash directly as the
package version.  ``setuptools`` delegates version parsing to
``packaging.version`` which enforces [PEP 440](https://peps.python.org/pep-0440/).
The raw short hash (e.g. ``"3ace557"``) is not a valid PEP 440 version and
therefore editable installs failed on Windows and other environments when
``pip`` attempted to normalise the value.  We now translate the git hash into a
``0.0.dev0+g<sha>`` style local version identifier and fall back to
``0.0.dev0`` whenever git metadata is unavailable.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List
from urllib.parse import urlunparse
from urllib.request import pathname2url

import setuptools

import setuptools


import setuptools


_DEFAULT_VERSION = "0.0.dev0"

import setuptools


_DEFAULT_VERSION = "0.0.dev0"


def _run_command(*cmd: str) -> str:
    """Execute *cmd* in the repository root and return stdout.

    ``pip`` invokes ``setup.py`` from temporary build directories, therefore we
    need to ensure the command runs relative to this file.  Any failure simply
    propagates to the caller so the version helper can fall back gracefully.
    """

    repo_root = os.path.dirname(os.path.abspath(__file__))
    completed = subprocess.run(
        cmd,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"command {cmd!r} exited with {completed.returncode}: {completed.stderr}")
    return (completed.stdout or "").strip()


def _normalise_version(raw: str | None) -> str:
    """Convert a raw git hash into a PEP-440 compliant version string."""


def _run_command(*cmd: str) -> str:
    """Execute *cmd* in the repository root and return stdout.

    ``pip`` invokes ``setup.py`` from temporary build directories, therefore we
    need to ensure the command runs relative to this file.  Any failure simply
    propagates to the caller so the version helper can fall back gracefully.
    """

    repo_root = os.path.dirname(os.path.abspath(__file__))
    completed = subprocess.run(
        cmd,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"command {cmd!r} exited with {completed.returncode}: {completed.stderr}")
    return (completed.stdout or "").strip()

def _normalise_version(raw: str | None) -> str:
    """Convert a raw git hash into a PEP-440 compliant version string."""

_DEFAULT_VERSION = "0.0.dev0"


def _run_command(*cmd: str) -> str:
    """Execute *cmd* in the repository root and return stdout.

    ``pip`` invokes ``setup.py`` from temporary build directories, therefore we
    need to ensure the command runs relative to this file.  Any failure simply
    propagates to the caller so the version helper can fall back gracefully.
    """

    repo_root = os.path.dirname(os.path.abspath(__file__))
    completed = subprocess.run(
        cmd,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"command {cmd!r} exited with {completed.returncode}: {completed.stderr}")
    return (completed.stdout or "").strip()

def _normalise_version(raw: str | None) -> str:
    """Convert a raw git hash into a PEP-440 compliant version string."""

def _normalise_version(raw: str | None) -> str:
    """Convert a raw git hash into a PEP-440 compliant version string."""

    if raw:
        short = raw.strip().lower()
        if short:
            return f"{_DEFAULT_VERSION}+g{short}"
    return _DEFAULT_VERSION


def _compute_version() -> str:
    """Best-effort retrieval of the current git revision."""

    try:
        raw = _run_command("git", "rev-parse", "--short", "HEAD")
    except Exception:
        return _DEFAULT_VERSION
    return _normalise_version(raw)


def _path_to_file_uri(path: Path) -> str:
    """Return a ``file://`` URI for *path* with proper escaping."""

    uri = path.resolve().as_uri()
    # ``Path.as_uri`` does not escape parentheses which causes ``pip`` to reject
    # the resulting requirement specifier when the repository lives inside a
    # directory such as ``"New Folder (3)"`` on Windows.  Percent-encode those
    # characters manually while leaving the already encoded portions intact.
    return uri.replace("(", "%28").replace(")", "%29")
    return path.resolve().as_uri()
    resolved = path.resolve()
    return urlunparse(("file", "", pathname2url(str(resolved)), "", "", ""))


def _normalise_version(raw: str | None) -> str:
    """Convert a raw git hash into a PEP-440 compliant version string."""

    if raw:
        short = raw.strip().lower()
        if short:
            return f"{_DEFAULT_VERSION}+g{short}"
    return _DEFAULT_VERSION


def _compute_version() -> str:
    """Best-effort retrieval of the current git revision."""

    try:
        raw = _run_command("git", "rev-parse", "--short", "HEAD")
    except Exception:
        return _DEFAULT_VERSION
    return _normalise_version(raw)


def setup(install_requires: List[str], name: str = "dex_proxy") -> None:
    """Invoke :func:`setuptools.setup` with consistent defaults.

    The helper appends ``py_dex_common`` as an editable dependency unless the
    caller is the package itself, mirroring the structure of the original
    project.  This keeps ``pip install -e harbor`` working on both Linux and
    Windows after fixing the version incompatibility described above.
    """

    version = _compute_version()

    if name != "py_dex_common":
        py_dex_common_path = Path(__file__).resolve().parent / "py_dex_common"
        install_requires = list(install_requires) + [
            f"py_dex_common @ {_path_to_file_uri(py_dex_common_path)}"
        ]
        install_requires = list(install_requires) + [f"py_dex_common @ {py_dex_common_path.as_uri()}"]
        py_dex_common_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "py_dex_common"))
        install_requires = list(install_requires) + [f"py_dex_common @ file://{py_dex_common_path}"]

    setuptools.setup(
        name=name,
        version=version,
        packages=setuptools.find_packages(),
        install_requires=list(install_requires),
    )


__all__ = [
    "setup",
    "_compute_version",
    "_normalise_version",
    "_run_command",
    "_path_to_file_uri",
]
