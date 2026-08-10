#!/usr/bin/env bash

set -euo pipefail

usage() {
  printf 'Usage: %s EMPTY_OUTPUT_DIRECTORY\n' "$(basename -- "$0")" >&2
}

fail() {
  printf 'Wheel build failed: %s\n' "$1" >&2
  exit 1
}

if [[ $# -ne 1 || -z "$1" ]]; then
  usage
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
OUTPUT_ARGUMENT="$1"

if [[ -e "$OUTPUT_ARGUMENT" && ! -d "$OUTPUT_ARGUMENT" ]]; then
  fail "output path exists and is not a directory"
fi
mkdir -p -- "$OUTPUT_ARGUMENT"
OUTPUT_DIR="$(cd -- "$OUTPUT_ARGUMENT" && pwd -P)"

shopt -s nullglob dotglob
existing_output=("${OUTPUT_DIR}"/*)
shopt -u nullglob dotglob
if [[ ${#existing_output[@]} -ne 0 ]]; then
  fail "output directory must be empty: ${OUTPUT_DIR}"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "${PYTHON_BIN} is required"

for required in pyproject.toml README.md src/weekly_cs_report; do
  [[ -e "${PROJECT_ROOT}/${required}" ]] || fail "missing source: ${required}"
done

"$PYTHON_BIN" "${SCRIPT_DIR}/verify_wheel_assets.py" \
  --source-static "${PROJECT_ROOT}/src/weekly_cs_report/static"

command -v uv >/dev/null 2>&1 || fail "uv is required"

TEMP_BASE="$(cd -- "${TMPDIR:-/tmp}" && pwd -P)"
STAGING_ROOT="$(mktemp -d "${TEMP_BASE}/weekly-cs-wheel.XXXXXX")"

cleanup() {
  if [[ -z "${STAGING_ROOT:-}" || ! -e "$STAGING_ROOT" ]]; then
    return
  fi
  if [[ "$STAGING_ROOT" != "${TEMP_BASE}"/weekly-cs-wheel.* ]]; then
    printf 'Refusing to clean unexpected staging path: %s\n' "$STAGING_ROOT" >&2
    return 1
  fi
  rm -rf -- "$STAGING_ROOT"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

SOURCE_ROOT="${STAGING_ROOT}/source"
mkdir -p -- "${SOURCE_ROOT}/src"
cp -p -- "${PROJECT_ROOT}/pyproject.toml" "${PROJECT_ROOT}/README.md" \
  "${SOURCE_ROOT}/"
cp -Rp -- "${PROJECT_ROOT}/src/weekly_cs_report" "${SOURCE_ROOT}/src/"

# A fixed archive timestamp and locale make repeated builds from the same source
# byte-reproducible while the fresh staging tree prevents setuptools from
# discovering workspace-local build/ or egg-info output.
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-946684800}"
export PYTHONHASHSEED=0
export LC_ALL=C
export TZ=UTC
export COPYFILE_DISABLE=1

(
  cd -- "$SOURCE_ROOT"
  uv build --wheel --out-dir "$OUTPUT_DIR" --no-create-gitignore .
)

shopt -s nullglob dotglob
build_outputs=("${OUTPUT_DIR}"/*)
shopt -u nullglob dotglob
if [[ ${#build_outputs[@]} -ne 1 || ! -f "${build_outputs[0]}" \
  || "${build_outputs[0]}" != *.whl ]]; then
  fail "expected exactly one wheel and no other output in ${OUTPUT_DIR}"
fi
WHEEL_PATH="${build_outputs[0]}"

"$PYTHON_BIN" "${SCRIPT_DIR}/verify_wheel_assets.py" \
  --wheel "$WHEEL_PATH" \
  --source-static "${PROJECT_ROOT}/src/weekly_cs_report/static"

printf 'Wheel ready: %s\n' "$WHEEL_PATH"
