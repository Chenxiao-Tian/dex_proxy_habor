# SHASUM pin of registry.gitlab.com/auros/baseimg/ubuntu:22.04
FROM registry.gitlab.com/auros/baseimg/ubuntu@sha256:dd015accda9632ca934006586fbc285e8a0e9f6159aab9c27db4c866676d9120 as builder

ARG SSH_PRIVATE_KEY_BASE64

RUN /bin/bash -c '[[ "${SSH_PRIVATE_KEY_BASE64}" ]] || { echo "SSH_PRIVATE_KEY_BASE64 build argument not set"; exit 1; }'

COPY . /app/auros

WORKDIR /app/auros

RUN apt-get update \
  && apt-get install -y openssh-client python3-venv libgmp3-dev \
  && mkdir -p /build/private ~/.ssh \
  && chmod 700 /build/private \
  && echo ${SSH_PRIVATE_KEY_BASE64} | base64 -i -d > /build/private/key \
  && chmod 600 /build/private/key \
  && eval $(ssh-agent) \
  && ssh-add /build/private/key \
  && ssh-keyscan bitbucket.org >> ~/.ssh/known_hosts \
  && python3 -m venv /app/auros \
  && . /app/auros/bin/activate \
  && pip3 install . \
  && rm -f /build/private/key \
  && rm -rf .git


# SHASUM pin of registry.gitlab.com/auros/baseimg/ubuntu:22.04-enclave
FROM registry.gitlab.com/auros/baseimg/ubuntu@sha256:61813c84d66dd32b461ac7469eb99fa3168de6df1b3dca53e7d8f7e50d0d0b8b

# Valet/authentication/enclave configuration
# Context ID is unique to this enclave.
ARG CONTEXT_ID
ARG PROCESS_NAME
ARG VAULT_APPROLE_ID
ARG VAULT_SECRET_ID
ARG VAULT_WALLET_NAME
ARG CONFIG_PATH
ARG SSH_PRIVATE_KEY_BASE64
ARG CONFIG_REPO_URI

ENV CONTEXT_ID=${CONTEXT_ID}
ENV PROCESS_NAME=${PROCESS_NAME}
ENV VAULT_APPROLE_ID=${VAULT_APPROLE_ID}
ENV VAULT_SECRET_ID=${VAULT_SECRET_ID}
ENV VAULT_WALLET_NAME=${VAULT_WALLET_NAME}
ENV CONFIG_REPO_URI=${CONFIG_REPO_URI}
# Private key is required to pull down CONFIG_REPO_URI at enclave boot.
ENV SSH_PRIVATE_KEY_BASE64=${SSH_PRIVATE_KEY_BASE64}

# Set some defaults
ENV WALLET_FORMAT=eth

# Application configuration
ENV APPLICATION_LISTEN_PORT=8000

COPY --from=builder /app/auros/ /app/auros/
COPY container/run /app/auros/run

ENTRYPOINT [ "/init" ]
