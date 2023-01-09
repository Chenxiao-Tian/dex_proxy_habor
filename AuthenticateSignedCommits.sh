#!/usr/bin/env bash
#
# Author: greg.markey@auros.global
# Version: 20220106-1
# * Print the name of the accepted signer.
# Version: 20220103-1
# * Initial release.

log() {
  echo "[${1}]" "${2}"
}

dbg() {
  log "DBG " "${1}"
}

info() {
  log "INFO" "${1}"
}

err() {
  log "ERR " "${1}"
}

[[ "${GPG_SIGNING_KEYS}" ]] || { err "GPG_SIGNING_KEYS is not defined. Use format GPG_SIGNING_KEYS=first.user@addr.com/PUBKEY,second.user@addr.com/PUBKEY"; exit 1; }

NEED_BINARIES=(gpg git)

for CMD in ${NEED_BINARIES[@]}; do
  command -v ${CMD} &>/dev/null || { err "${CMD} not found in path, is it installed?"; exit 1; }
done

IFS=',' GPG_PAIRS=(${GPG_SIGNING_KEYS})
for GPG_PAIR in ${GPG_PAIRS[@]}; do
  IFS='/' GPG_PAIR=(${GPG_PAIR})
  info "Adding trusted signer ${GPG_PAIR[0]} (${GPG_PAIR[1]})"
  gpg --keyserver keyserver.ubuntu.com --recv-key ${GPG_PAIR[1]} &> gpgout.log
  RC=$?
  if [[ $RC > 0 ]]; then
    err "Importing GPG key for ${GPG_PAIR[0]} failed: ${RC}"
    err "GPG output follows:"
    cat gpgout.log
    exit $RC
  fi
done

git status &> gitout.log
RC=$?
if [[ $RC > 0 ]]; then
  err "Error reading from repository"
  err "Git output follows:"
  cat gitout.log
  exit $RC
fi

# TODO: Improve this to look at all commits on the branch, rather than just the latest.
git verify-commit HEAD &> gitout.log
RC=$?
if [[ $RC > 0 ]]; then
  err "Commit verification failed!"
  err "Git output follows:"
  cat gitout.log
  exit $RC
fi

info "Signature OK"
cat gitout.log
