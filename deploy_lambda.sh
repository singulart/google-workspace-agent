#!/usr/bin/env bash
# Package and upload Vincent Lambdas to S3 for Terraform deployment.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUCKET="${LAMBDA_S3_BUCKET:-argorand-lambdas-repository}"
BUILD_DIR="${ROOT}/.lambda-build"
PYTHON="${PYTHON:-python3}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [all|vincent-authorizer|vincent-agentcore]

Environment:
  LAMBDA_S3_BUCKET  S3 bucket (default: argorand-lambdas-repository)
  PYTHON            Python interpreter for pip fallback (default: python3)

Authorizer builds use Docker (public.ecr.aws/lambda/python:3.14-arm64) when available
so native deps (cryptography, etc.) are Linux arm64, not macOS.

Upload keys:
  s3://\$BUCKET/vincent-authorizer/deployment.zip
  s3://\$BUCKET/vincent-agentcore/deployment.zip
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

verify_linux_arm64_binaries() {
  local pkg_dir="$1"
  local bad=""

  while IFS= read -r -d '' so; do
    if ! file "${so}" | grep -q 'ELF 64-bit.*ARM aarch64'; then
      bad="${bad}\n  ${so}: $(file -b "${so}")"
    fi
  done < <(find "${pkg_dir}" -name '*.so' -print0 2>/dev/null)

  if [[ -n "${bad}" ]]; then
    echo "ERROR: Found non-Linux-arm64 shared libraries in the Lambda package:${bad}" >&2
    echo "Rebuild with Docker (recommended) or fix pip --platform flags; do not use macOS-native wheels." >&2
    exit 1
  fi
}

install_authorizer_deps_docker() {
  local src="$1"
  local pkg_dir="$2"
  local image="public.ecr.aws/lambda/python:3.14-arm64"

  # Lambda base images use a runtime entrypoint (handler name); override for pip install.
  docker run --rm --platform linux/arm64 \
    --entrypoint /bin/bash \
    -v "${src}/requirements.txt:/tmp/requirements.txt:ro" \
    -v "${pkg_dir}:/out" \
    "${image}" \
    -lc "python -m pip install -r /tmp/requirements.txt -t /out --quiet && chmod -R a+rX /out"
}

install_authorizer_deps_pip() {
  local src="$1"
  local pkg_dir="$2"

  # No macOS fallback: a failed cross-install must not silently bundle Darwin .so files.
  "${PYTHON}" -m pip install -r "${src}/requirements.txt" -t "${pkg_dir}" --quiet \
    --platform manylinux2014_aarch64 \
    --implementation cp \
    --python-version 3.14
}

build_authorizer() {
  local name="vincent-authorizer"
  local src="${ROOT}/lambda/${name}"
  local work="${BUILD_DIR}/${name}"
  local zip="${work}/deployment.zip"

  rm -rf "${work}"
  mkdir -p "${work}/package"

  if command -v docker >/dev/null 2>&1; then
    echo "Building ${name} dependencies in Lambda Python 3.14 arm64 Docker image..."
    install_authorizer_deps_docker "${src}" "${work}/package"
  else
    echo "Docker not found; using pip cross-install for manylinux2014_aarch64..."
    install_authorizer_deps_pip "${src}" "${work}/package"
  fi

  verify_linux_arm64_binaries "${work}/package"

  cp "${src}/handler.py" "${work}/package/"
  (cd "${work}/package" && zip -qr "${zip}" .)
  echo "Zip sanity check:"
  unzip -l "${zip}" | grep -E 'handler.py|requests/|cryptography/' || true
  # SHA256 checksum on upload so Terraform can read checksum_sha256 from the S3 object.
  aws s3 cp "${zip}" "s3://${BUCKET}/${name}/deployment.zip" --checksum-algorithm SHA256
  echo "Uploaded s3://${BUCKET}/${name}/deployment.zip"
}

build_agentcore() {
  local name="vincent-agentcore"
  local src="${ROOT}/lambda/${name}"
  local work="${BUILD_DIR}/${name}"
  local zip="${work}/deployment.zip"

  rm -rf "${work}"
  mkdir -p "${work}/package"
  cp "${src}/handler.py" "${work}/package/"
  cp "${ROOT}/agent/chat_payload.py" "${work}/package/"
  (cd "${work}/package" && zip -qr "${zip}" .)
  aws s3 cp "${zip}" "s3://${BUCKET}/${name}/deployment.zip" --checksum-algorithm SHA256
  echo "Uploaded s3://${BUCKET}/${name}/deployment.zip"
}

main() {
  require_cmd aws
  require_cmd zip
  require_cmd "${PYTHON}"

  local target="${1:-all}"
  case "${target}" in
    all)
      build_authorizer
      build_agentcore
      ;;
    vincent-authorizer)
      build_authorizer
      ;;
    vincent-agentcore)
      build_agentcore
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      echo "Unknown target: ${target}" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
