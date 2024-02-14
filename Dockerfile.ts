# SHASUM pin of registry.gitlab.com/auros/baseimg/ubuntu:22.04
FROM registry.gitlab.com/auros/baseimg/ubuntu@sha256:dcc12ea35886641ad46771c037f8541585ba105a0bc2634845df082b8748f1bf as builder

ARG TS_DEX_PATH
ARG SSH_PRIVATE_KEY_BASE64

RUN /bin/bash -c '[[ "${SSH_PRIVATE_KEY_BASE64}" ]] || { echo "SSH_PRIVATE_KEY_BASE64 build argument not set"; exit 1; }'

COPY . /app/auros

WORKDIR /app/auros

# Major version of nodejs to use
ENV NODE_MAJOR=20

RUN apt-get update \
  && apt-get install -y curl gpg \
  && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
  && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
  && apt-get update \
  && apt-get install -y nodejs \
  && npm i -g typescript \
  && cd /app/auros/${TS_DEX_PATH} \
  && npm i \
  && tsc \
  && rm -rf /app/auros/.git


# SHASUM pin of registry.gitlab.com/auros/baseimg/ubuntu:22.04-enclave
FROM registry.gitlab.com/auros/baseimg/ubuntu@sha256:5770b3b986905330f00b7b4cf364e05dc7f4ea22f892f6d439482bb7e04e0725

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
ARG TS_DEX_PATH
ARG WALLET_FORMAT=eth

ENV CONTEXT_ID=${CONTEXT_ID}
ENV PROCESS_NAME=${PROCESS_NAME}
ENV VAULT_APPROLE_ID=${VAULT_APPROLE_ID}
ENV VAULT_SECRET_ID=${VAULT_SECRET_ID}
ENV VAULT_WALLET_NAME=${VAULT_WALLET_NAME}
ENV CONFIG_REPO_URI=${CONFIG_REPO_URI}
# Need to know where the `dist` files are.
ENV TS_DEX_PATH=${TS_DEX_PATH}
# Private key is required to pull down CONFIG_REPO_URI at enclave boot.
ENV SSH_PRIVATE_KEY_BASE64=${SSH_PRIVATE_KEY_BASE64}

# Set some defaults
ENV WALLET_FORMAT=${WALLET_FORMAT}

# Application configuration
ENV APPLICATION_LISTEN_PORT=8000

COPY --from=builder /app/auros/ /app/auros/
COPY container/run.ts /app/auros/run
COPY container/egress-implicit-postgres-5432.toml /etc/horust/services/

ENTRYPOINT [ "/init" ]
