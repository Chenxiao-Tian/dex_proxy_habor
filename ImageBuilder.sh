#!/usr/bin/env bash
#
# Author: greg.markey@auros.global
# Version: 20220420-1
# * Implicit lowercase of container URI; fixes mixed case PROCESS_NAME.
# Version: 20220216-2
# * Fix static lockdir.
# Version: 20220216-1
# * Switch to compressed, binary shars.
# Version: 20220206-1
# * Require CONTEXT_ID.
# Version: 20220203-1
# * Add CONTEXT_ID as consumed var.
# Version: 20220202-1
# * Fix duplication of image name.
# Version: 20220131-2
# * Separate credentials for ECR and S3 publishing.
# Version: 20220131-1
# * Look for AuStartEnclave.sh inside the build container.
# Version: 20220130-2
# * Fix up registry paths for Gitlab.
# Version: 20220130-1
# * Do not try to ECR login when running in Gitlab CI.
# Version: 20220126-1
# * Fix `WITH_ENCLAVE` tests.
# Version: 20220123-1
# * Optional SSH_PRIVATE_KEY_BASE64
# Version: 20220112-1
# * Add ability to disable caching.
# Version: 20220111-1
# * Initial release.

set -o pipefail
set -e

usage() {
  echo "usage: $0 [--enclave] [--skip-image-push] [--skip-registry-login]"
  echo
  echo "options:"
  echo "  --enclave             Create an enclave image"
  echo "  --skip-image-push     Prevent push of finalised container and/or enclave image"
  echo "  --skip-registry-login Do not attempt login to a remote registry (ECR, GitLab) for local builds"
  echo "  --no-cache            Build the container with caching disabled"
  echo
  echo "environment variables:"
  echo "  DOCKERFILE               Path to the Dockerfile used during build. Default: Dockerfile."
  echo "  CONTAINER_NAME           Arbitrary name for the container being built. This is used as part of the upload"
  echo "                           path, as well as being used to find the secret pointers. Default: project name."
  echo "  CONTAINER_ADDITIONAL_TAG By default, the resulting container (or enclave) image will be tagged with the git"
  echo "                           shasum. The contents of CONTAINER_ADDITIONAL_TAG will be appended to the image tag"
  echo "                           in the format \"\${GIT_SHASUM}-\${CONTAINER_ADDITIONAL_TAG}\". Optional"
  echo "  REGISTRY_PATH            Subpath for the image; \"\${REGISTRY}/\${REGISTRY_PATH}\". Default: project name."
  echo "  SSH_PRIVATE_KEY_BASE64   Auros applications generally need to be able to fetch dependencies from our CVS."
  echo "                           In order to achieve this, a read-only SSH private key in base64 format needs to be"
  echo "                           passed during the container build process. Optional (requirement depends on"
  echo "                           container)."
  echo "  ADDITIONAL_BUILD_ARGS    Arbitrary build CLI arguments. Optional."
  echo
  echo "enclave environment variables:"
  echo "  CONTEXT_ID        Enclave context ID. If this is not defined, we assume it is set"
  echo "                    in the target Dockerfile instead."
  echo "  PROCESS_NAME      Name of the application instance inside the enclave. Required."
  echo "  VAULT_APPROLE_ID  AppRole authentication UUID used to authenticate to Vault. This is"
  echo "                    embedded into the resulting image and consumed by \`valet\`. Required"
  echo "  VAULT_SECRET_ID   Name of the AWS SecretsManager secret that contains the second stage"
  echo "                    authentication. Required."
  echo "  VAULT_WALLET_NAME Key in Vault containing the wallet mnemonic. Required."
  echo
  exit 1
}


_setArgs(){
  while [ "${1:-}" != "" ]; do
    case "$1" in
      "--enclave")
        WITH_ENCLAVE=1
        ;;
      "--skip-image-push")
        SKIP_IMAGE_PUSH=1
        ;;
      "--skip-registry-login")
        SKIP_REGISTRY_LOGIN=1
        ;;
      "--no-cache")
        NO_CACHE="--no-cache"
        ;;
      *)
        usage
        ;;
    esac
    shift
  done
}

_setArgs $@

# Ensure we have required bins.
ROOTDIR=$(dirname $0)
command -v docker &>/dev/null && CONTAINER_ENGINE=docker
command -v podman &>/dev/null && CONTAINER_ENGINE=podman
command -v aws &>/dev/null    || { echo "Missing aws binary"; exit 1; }
command -v git &>/dev/null    || { echo "Missing git binary"; exit 1; }
[[ "${CONTAINER_ENGINE}" ]]   || { echo "Missing container engine (docker or podman)"; exit 1; }

if [[ "${WITH_ENCLAVE}" ]]; then
  [ -x /opt/auros/AuStartEnclave.sh ]   && AU_ENCLAVE_INIT_SCRIPT=/opt/auros/AuStartEnclave.sh
  [ -x "${ROOTDIR}/AuStartEnclave.sh" ] && AU_ENCLAVE_INIT_SCRIPT="${ROOTDIR}/AuStartEnclave.sh"
  command -v nitro-cli &>/dev/null      || { echo "Missing nitro-cli binary"; exit 1; }
  command -v skopeo &>/dev/null         || { echo "Missing skopeo binary"; exit 1; }
  command -v base64 &>/dev/null         || { echo "Missing base64 binary"; exit 1; }
  command -v shar &>/dev/null           || { echo "Missing shar binary"; exit 1; }
  command -v cat &>/dev/null            || { echo "Missing cat binary"; exit 1; }
  command -v sed &>/dev/null            || { echo "Missing sed binary"; exit 1; }
  [[ "${AU_ENCLAVE_INIT_SCRIPT}" ]]     || { echo "Missing ${ROOTDIR}/AuStartEnclave.sh script (see pipeline-tools repo)"; exit 1; }
fi


# Setup environment
DOCKERFILE=${DOCKERFILE:=Dockerfile}

[ -f "${DOCKERFILE}" ] || { echo "Missing Dockerfile at path ${DOCKERFILE}"; exit 1; }

# Handle multiple CI platforms.
COMMIT_SHASUM=$(git rev-parse HEAD)
COMMIT_SHORTSHA=${COMMIT_SHASUM:0:7}
COMMIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
REGISTRY=${CI_REGISTRY:=307205023173.dkr.ecr.us-west-2.amazonaws.com}
REGISTRY_PATH=${REGISTRY_PATH:=${CI_PROJECT_PATH}}
[[ "${CONTAINER_NAME}" ]] || CONTAINER_NAME=${BITBUCKET_REPO_SLUG:=${CI_PROJECT_NAME}}
$(git diff --quiet) || DIRTY=1


[[ "${REGISTRY_PATH}" || "${CONTAINER_NAME}" ]] || { echo "CONTAINER_NAME env must be provided when run outside CI/CD"; exit 1; }

if [[ "${SKIP_REGISTRY_LOGIN}" == "" && "${SKIP_IMAGE_PUSH}" == "" && "${CI_SERVER_NAME}" != "GitLab" ]]; then
  [[ "${AWS_ECR_ACCESS_KEY_ID}" ]]     || { echo "Missing env AWS_ECR_ACCESS_KEY_ID (for ECR access)"; exit 1; }
  [[ "${AWS_ECR_SECRET_ACCESS_KEY}" ]] || { echo "Missing env AWS_ECR_SECRET_ACCESS_KEY (for ECR access)"; exit 1; }
  [[ "${AWS_PUBLISH_ACCESS_KEY_ID}" ]]     || { echo "Missing env AWS_PUBLISH_ACCESS_KEY_ID (for S3 publish access)"; exit 1; }
  [[ "${AWS_PUBLISH_SECRET_ACCESS_KEY}" ]] || { echo "Missing env AWS_PUBLISH_SECRET_ACCESS_KEY (for S3 publish access)"; exit 1; }
fi

# If we are providing some arbitrary additional tagging, add it here.
if [[ "${CONTAINER_ADDITIONAL_TAG}" ]]; then
  CONTAINER_ADDITIONAL_TAG="${CONTAINER_ADDITIONAL_TAG}-"
fi

# Tag images when they're dirty.
[[ "${DIRTY}" ]] && DIRTY_TAG="-dirty"

if [[ "${REGISTRY_PATH}" == "" ]]; then
  REGISTRY_PATH=${CONTAINER_NAME}
else
  # prevent name duplication
  [[ "$(basename ${REGISTRY_PATH})" != "${CONTAINER_NAME}" ]] && REGISTRY_PATH=${REGISTRY_PATH}/${CONTAINER_NAME}
fi

CONTAINER_URI=${REGISTRY}/${REGISTRY_PATH}
# Must be lowercase
CONTAINER_URI=${CONTAINER_URI,,}

[[ "${COMMIT_SHASUM}" ]]  || COMMIT_SHASUM=unknown-sha
[[ "${COMMIT_BRANCH}" ]]  || COMMIT_BRANCH=unknown-branch

# Setup build args
[[ "${SSH_PRIVATE_KEY_BASE64}" ]] && ADDITIONAL_BUILD_ARGS="${ADDITIONAL_BUILD_ARGS} --build-arg SSH_PRIVATE_KEY_BASE64=${SSH_PRIVATE_KEY_BASE64}"

if [[ "${WITH_ENCLAVE}" ]]; then
  # Enclaved applications must have their PROCESS_NAME embedded.
  [[ "${PROCESS_NAME}" ]]      || { echo "Missing env PROCESS_NAME"; exit 1; }
  [[ "${CONTEXT_ID}" ]]        || { echo "Missing env CONTEXT_ID"; exit 1; }
  # Test that secret information provided by CI is not null.
  [[ "${VAULT_WALLET_NAME}" ]] || { echo "Missing env VAULT_WALLET_NAME (set in CI pipeline)"; exit 1; }
  [[ "${VAULT_SECRET_ID}" ]]   || { echo "Missing env VAULT_SECRET_ID (set in CI pipeline)"; exit 1; }
  [[ "${VAULT_APPROLE_ID}" ]]  || { echo "Missing env VAULT_APPROLE_ID (set in CI pipeline)"; exit 1; }

  # Additional build arguments required for enclave builds.
  [[ "${CONTEXT_ID}" ]] && ADDITIONAL_BUILD_ARGS="${ADDITIONAL_BUILD_ARGS} --build-arg CONTEXT_ID=${CONTEXT_ID}"
  ADDITIONAL_BUILD_ARGS="${ADDITIONAL_BUILD_ARGS} --build-arg PROCESS_NAME=${PROCESS_NAME}"
  ADDITIONAL_BUILD_ARGS="${ADDITIONAL_BUILD_ARGS} --build-arg VAULT_APPROLE_ID=${VAULT_APPROLE_ID}"
  ADDITIONAL_BUILD_ARGS="${ADDITIONAL_BUILD_ARGS} --build-arg VAULT_SECRET_ID=${VAULT_SECRET_ID}"
  ADDITIONAL_BUILD_ARGS="${ADDITIONAL_BUILD_ARGS} --build-arg VAULT_WALLET_NAME=${VAULT_WALLET_NAME}"
fi

registry_login() {
  if [[ "${CI_SERVER_NAME}" == "GitLab" ]]; then
    ${CONTAINER_ENGINE} login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  else
    export AWS_ACCESS_KEY_ID=${AWS_ECR_ACCESS_KEY_ID}
    export AWS_SECRET_ACCESS_KEY=${AWS_ECR_SECRET_ACCESS_KEY}
    aws ecr get-login-password --region us-west-2 | ${CONTAINER_ENGINE} login --username AWS --password-stdin ${REGISTRY}
  fi
}


build_container() {
  ${CONTAINER_ENGINE} build ${ADDITIONAL_BUILD_ARGS} ${NO_CACHE} -t ${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHASUM}${DIRTY_TAG} -f ${DOCKERFILE} .
  ${CONTAINER_ENGINE} tag ${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHASUM}${DIRTY_TAG} ${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHORTSHA}${DIRTY_TAG}
}


publish_container_artifact() {
  ${CONTAINER_ENGINE} push ${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHASUM}${DIRTY_TAG}
  ${CONTAINER_ENGINE} push ${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHORTSHA}${DIRTY_TAG}
}


build_enclave() {
  # Create an OCI compatible cache for linuxkit from the docker images.
  # This is required because docker is a steaming pile of noncompliance.
  _DOCKER_HOST=${DOCKER_HOST//tcp:\/\//http:\/\/}
  mkdir -p ${HOME}/.linuxkit/cache
  skopeo copy --src-tls-verify=false --src-daemon-host=$_DOCKER_HOST docker-daemon:${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHASUM}${DIRTY_TAG} oci:${HOME}/.linuxkit/cache

  # We also have to modify the cache index to add the upstream image name.
  # WE ALSO have to prefix the cached image name with docker.io/ otherwise linuxkit gets confused and tries to download
  # it. What an absolute shit show.
  INDEX=$(jq ".manifests[0].annotations += {\"org.opencontainers.image.ref.name\": \"docker.io/${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHASUM}${DIRTY_TAG}\"}" ~/.linuxkit/cache/index.json)
  echo $INDEX > ~/.linuxkit/cache/index.json

  # TODO: Uncomment this when we are enabling release signing.
  #nitro-cli build-enclave --docker-uri ${CONTAINER_URI} --output-file ${CONTAINER_NAME}.eif --private-key ${KEY_PATH} --signing-certificate ${CERT_PATH}
  nitro-cli build-enclave --docker-uri ${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHASUM}${DIRTY_TAG} --output-file ${CONTAINER_NAME}.eif
  RC=$?

  if [ $RC != 0 ]; then
    cat /var/log/nitro_enclaves/err*.log
    cat /tmp/fd1.log
    exit $RC
  fi

  #base64 ${CONTAINER_NAME}.eif > ${CONTAINER_NAME}.base64
  # Fix incorrect shell usage, remove explicit exit on execute.
  shar -C bzip2 -g 5 -B -x ${CONTAINER_NAME}.eif | sed \
    -e 's/^#\!\/bin\/sh/#!\/bin\/bash/' \
    -e '/^exit/d' \
    -e 's/^lock_dir=.*/lock_dir=$(basename $0)-$(date +%s)/' \
    -e '/^begin 600.*/d' \
    -e 's/| uudecode &&/| cat <(echo "begin 600 ${lock_dir}\/bzi") - | uudecode \&\&/' > ${CONTAINER_NAME}
  cat ${ROOTDIR}/AuStartEnclave.sh >> ${CONTAINER_NAME}
}


publish_enclave_artifact() {
  echo uploading enclave image
  export AWS_ACCESS_KEY_ID=${AWS_PUBLISH_ACCESS_KEY_ID}
  export AWS_SECRET_ACCESS_KEY=${AWS_PUBLISH_SECRET_ACCESS_KEY}
  aws s3 cp --only-show-errors ${CONTAINER_NAME} s3://kenetic-build/app/${CONTAINER_NAME}/${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHORTSHA}${DIRTY_TAG}
}


[[ "${SKIP_REGISTRY_LOGIN}" != 1 ]] && registry_login
build_container
[[ "${SKIP_IMAGE_PUSH}" != 1 ]] && publish_container_artifact

if [[ "${WITH_ENCLAVE}" ]]; then
  build_enclave
  [[ "${SKIP_IMAGE_PUSH}" != 1 ]] && publish_enclave_artifact
fi


echo
echo

echo Build finished
echo
echo Container image URI:
echo ${CONTAINER_URI}:${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHASUM}${DIRTY_TAG}

if [[ "${WITH_ENCLAVE}" ]]; then
  echo
  echo Enclave image URI:
  echo s3://kenetic-build/app/${CONTAINER_NAME}/${CONTAINER_ADDITIONAL_TAG}${COMMIT_SHORTSHA}${DIRTY_TAG}
fi
