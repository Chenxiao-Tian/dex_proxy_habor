#!/bin/bash


set -o pipefail

trap 'log_crash $?' ERR

log_crash() {
    DATE=$(date "+%Y-%m-%d %H:%M:%S.%3N")
    echo "[${DATE}] [CRITICAL] ${PROCESS_NAME:=unknown process} exited with error code ${1} (CRASH)"
    exit ${1}
}

log_error() {
    DATE=$(date "+%Y-%m-%d %H:%M:%S.%3N")
    echo "[${DATE}] [CRITICAL] $@"
    log_crash 1
}

[[ "${PROCESS_NAME}" ]] || log_error "PROCESS_NAME environment variable not set"
[[ "${TS_DEX_PATH}" ]] || log_error "TS_DEX_PATH environment variable not set"

# /app/auros/config will be cloned by an enclave init process.

node ${TS_DEX_PATH}/dist/dex_proxy.js -c /app/auros/config/${PROCESS_NAME}.json

exit $?
