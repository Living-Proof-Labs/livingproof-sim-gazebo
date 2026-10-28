#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
if [[ ${LIVINGPROOF_TOOLING:-} == 1 ]]; then
  exec task -t Taskfile.runtime.yml "$@"
fi
if ! command -v docker >/dev/null; then
  echo 'Host tasks require Docker. Use a prepared development container for task setup.' >&2
  exit 1
fi
args=(compose run --rm)
[[ $1 != setup ]] || args+=(--build)
exec docker "${args[@]}" tooling task -t Taskfile.runtime.yml "$@"
