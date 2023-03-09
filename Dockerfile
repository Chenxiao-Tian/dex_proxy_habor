FROM registry.gitlab.com/auros/baseimg/ubuntu@sha256:dd015accda9632ca934006586fbc285e8a0e9f6159aab9c27db4c866676d9120 as builder

ARG SSH_PRIVATE_KEY_BASE64

RUN /bin/bash -c '[[ "${SSH_PRIVATE_KEY_BASE64}" ]] || { echo "SSH_PRIVATE_KEY_BASE64 build argument not set"; exit 1; }'

COPY . /app/auros

WORKDIR /app/auros

RUN apt-get update \
  && apt-get install -y openssh-client python3-venv \
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


FROM registry.gitlab.com/auros/baseimg/ubuntu@sha256:615f2d3b5ef00841effc8647c60893bfdb509e66e9b5b1fff0406378a1c3c17f

# Valet/authentication/enclave configuration
# Context ID is unique to this enclave.
ARG CONTEXT_ID
ARG PROCESS_NAME
ARG VAULT_APPROLE_ID
ARG VAULT_SECRET_ID
ARG VAULT_WALLET_NAME
ARG CONFIG_PATH
ENV CONTEXT_ID=${CONTEXT_ID}
ENV PROCESS_NAME=${PROCESS_NAME}
ENV VAULT_APPROLE_ID=${VAULT_APPROLE_ID}
ENV VAULT_SECRET_ID=${VAULT_SECRET_ID}
ENV VAULT_WALLET_NAME=${VAULT_WALLET_NAME}

# Set some defaults
ENV WALLET_FORMAT=eth

# Application configuration
ENV APPLICATION_LISTEN_PORT=8000

COPY --from=builder /app/auros/ /app/auros/
COPY container/02-hosts-application /etc/02-hosts-application
COPY container/run /app/auros/run
COPY config/${PROCESS_NAME}.json /app/auros/${PROCESS_NAME}.json

ENTRYPOINT [ "/init" ]
