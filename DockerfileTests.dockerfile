# syntax=docker/dockerfile:1.4
# Use Ubuntu 22.04 as a parent image
FROM ubuntu:22.04

COPY --from=ghcr.io/astral-sh/uv:0.8-python3.10-bookworm-slim /usr/local/bin/uv /usr/local/bin/uvx /bin/

WORKDIR /app

RUN apt-get update && \
    apt-get install -y build-essential curl git openssh-client && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* && \
    uv python install 3.10 && \
    uv venv --prompt "dex_proxy" --python 3.10 .venv && \
    uv pip install "setuptools==80.9.0" && \
    mkdir -p -m 0700 ~/.ssh && ssh-keyscan bitbucket.org >> ~/.ssh/known_hosts

COPY . .

ARG DEX_NAME=default_must_be_redefined

WORKDIR /app/${DEX_NAME}

# Install python dependencies using setup.py, with SSH access for private repos
# Requires build with --ssh flag, e.g., `docker build --ssh default`
RUN --mount=type=ssh,id=default uv pip install ".[dev]"


# Activate virtual environment by default
ENV PATH="/app/.venv/bin:$PATH"
