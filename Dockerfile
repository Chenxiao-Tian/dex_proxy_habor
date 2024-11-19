# SHASUM pin of registry.gitlab.com/auros/baseimg/ubuntu:22.04
FROM registry.gitlab.com/auros/baseimg/ubuntu@sha256:dcc12ea35886641ad46771c037f8541585ba105a0bc2634845df082b8748f1bf as builder

ARG SSH_PRIVATE_KEY_BASE64

RUN /bin/bash -c '[[ "${SSH_PRIVATE_KEY_BASE64}" ]] || { echo "SSH_PRIVATE_KEY_BASE64 build argument not set"; exit 1; }'

COPY . /app/auros

WORKDIR /app/auros

RUN apt-get update \
  && apt-get install -y openssh-client python3-venv libgmp3-dev curl \
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
  && rm -rf /app/auros/.git

# Add the high performance starknet signing library - be careful to ensure that the code from which this was built has
# been through the protected branch review process.
# https://gitlab.com/auros/starknet-signing-cpp
RUN curl -L --fail-with-body -o /tmp/libsigner.tar.gz --user "gitlab-com-auros-starknet-signing-cpp-ro:gldt-JBMfUTUU6yEt6HKxymfH" https://gitlab.com/api/v4/projects/57964836/packages/generic/starknet-signing-cpp/b952e640/starknet-signing-cpp-x86_64.b952e640.tar.gz \
  && cd /tmp \
  && echo 80fda92f221dbcec96a82760ecf2a0f44f4d8c5baf951fc581d48d8f0ed2a892 libsigner.tar.gz >> libsigner-shasums.txt \
  && sha256sum -c libsigner-shasums.txt \
  && tar xf libsigner.tar.gz


# SHASUM pin of registry.gitlab.com/auros/baseimg/ubuntu:22.04-enclave
FROM registry.gitlab.com/auros/baseimg/ubuntu@sha256:8495adfc1b75763a64b809fb00ad202ea59948a2ac0cff0c3ac2a9013a9ac268

# Valet/authentication/enclave configuration
# Context ID is unique to this enclave.
ARG CONTEXT_ID
ARG PROCESS_NAME
ARG VAULT_APPROLE_ID
ARG VAULT_SECRET_ID
ARG VAULT_WALLET_NAME
ARG KMS_KEY_ID
ARG CONFIG_PATH
ARG SSH_PRIVATE_KEY_BASE64
ARG CONFIG_REPO_URI

ENV CONTEXT_ID=${CONTEXT_ID}
ENV PROCESS_NAME=${PROCESS_NAME}
ENV VAULT_APPROLE_ID=${VAULT_APPROLE_ID}
ENV VAULT_SECRET_ID=${VAULT_SECRET_ID}
ENV VAULT_WALLET_NAME=${VAULT_WALLET_NAME}
ENV KMS_KEY_ID=${KMS_KEY_ID}
ENV CONFIG_REPO_URI=${CONFIG_REPO_URI}
# Private key is required to pull down CONFIG_REPO_URI at enclave boot.
ENV SSH_PRIVATE_KEY_BASE64=${SSH_PRIVATE_KEY_BASE64}

# Set some defaults
ENV WALLET_FORMAT=eth

# Application configuration
ENV APPLICATION_LISTEN_PORT=8000

COPY --from=builder /app/auros/ /app/auros/
COPY --from=builder /tmp/libsigner.so /app/auros/lib64/python3.10/site-packages/libsigner.so
COPY container/run /app/auros/run

ENTRYPOINT [ "/init" ]
