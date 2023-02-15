#!/bin/bash
#
# Author: greg.markey@auros.global
# Version: 20220111-1
# * Initial release.

set -o pipefail
set -e

while [ "${1}" ]; do
  case "${1}" in
    "--process-name") PROCESS_NAME=$2;;
    "-c") CONFIG_FILE=$2;;
  esac
  shift
done

log() {
  TIME=$(date +"%Y-%m-%d %H:%M:%S")
  echo -e "${TIME} $@"
}


fatal() {
  error $@
  exit 1
}


error() {
  log "[Error ] $@"
}


info() {
  log "[Info  ] $@"
}

command -v nitro-cli    || fatal "Missing nitro-cli binary"
[ -f "${CONFIG_FILE}" ] || fatal "Missing configuration file ${CONFIG_FILE}"

# Config includes arbitrary files as k/v; with the actual content a base64 encoded str.
# CUSTOM_CONFIG_FILES=( $( jq -r '.configs | keys[] ' ${CONFIG_FILE}) )

ENCLAVE=$(basename $0)-enclave.eif
ENCLAVE_PATH=app/${ENCLAVE}
BASE64_SOURCE_BINARY=$(jq -r .app.s3_app_name ${CONFIG_FILE}).base64

ENCLAVE_CID=$(jq -r '.enclave.cid // empty' ${CONFIG_FILE})
CPU_COUNT=$(jq -r '.enclave.cpus // empty' ${CONFIG_FILE})
CPU_COUNT=${CPU_COUNT:=1}
MEM_COUNT=$(jq -r '.enclave.mem_mb // empty' ${CONFIG_FILE})
MEM_COUNT=${MEM_COUNT:=1024}

CONSOLE=$(jq -r '.enclave.attach_console // empty' ${CONFIG_FILE})
[[ "${CONSOLE}" == "true" ]] && CONSOLE_ARGS="--attach-console --debug-mode"

[[ "${ENCLAVE_CID}" ]] || fatal "You must specify enclave.cid (int) in config.json"

halt_enclave() {
  info "Shutting down enclave"
  sudo nitro-cli terminate-enclave --enclave-name ${PROCESS_NAME} || fatal "Failed to terminate enclave"
  exit 0
}

# These traps are not functional when run with `au` as the process is wrapped by
# `kenetic-run-native`, which fails to pass through signals correctly.
# Use ExecStop instead for `au` units.
trap halt_enclave SIGTERM
trap halt_enclave SIGINT

if [ -f "${ENCLAVE_PATH}" ]; then
  info "Binary already exists, skip decoding"
else
  # decode the bundled binary.
  base64 -d ${BASE64_SOURCE_BINARY} > "${ENCLAVE_PATH}" || fatal "Unable to base64 decode binary"
fi

rm -f ${BASE64_SOURCE_BINARY} &>/dev/null

# decode the custom config (if there is one)
#for file in ${CUSTOM_CONFIG_FILES[@]}; do
#  CUSTOM_CONFIG_BASE64=$(jq -r ".configs.${file}" ${CONFIG_FILE})
#  info "Writing configuration file ${file}"
#  (( ${#CUSTOM_CONFIG_BASE64} )) && echo ${CUSTOM_CONFIG_BASE64} | base64 -d > ~/persistent/${file}
#done

info "Attempting to start enclaved application"
sudo nitro-cli run-enclave \
  ${CONSOLE_ARGS} \
  --eif-path ${ENCLAVE_PATH} \
  --memory ${MEM_COUNT} \
  --cpu-count ${CPU_COUNT} \
  --enclave-cid ${ENCLAVE_CID} \
  --enclave-name ${PROCESS_NAME} &

# Poll the process for liveness
if [[ "${CONSOLE_ARGS}" ]]; then
  while jobs %% &>/dev/null; do
    sleep 1
  done
else
  # Wait for enclave to start
  sleep 15
  while :; do
    sudo nitro-cli describe-enclaves | \
      jq -e '.[] | select(.EnclaveName | contains ("'${PROCESS_NAME}'"))' &>/dev/null
    [[ ${?} > 0 ]] && break
    sleep 5
  done
fi

halt_enclave
