#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Fail closed if a snapshot ID is not in the past or is older than the
# ubuntu:24.04 image created date. snapshot.ubuntu.com silently serves the
# moving latest archive for a future ID.
set -euo pipefail
SNAP=${1:?usage: check-snapshot-id.sh SNAPSHOT_ID IMAGE_CREATED}
CREATED=${2:?usage: check-snapshot-id.sh SNAPSHOT_ID IMAGE_CREATED}
[[ $SNAP =~ ^20[0-9]{6}T[0-9]{6}Z$ ]] || { echo "bad snapshot id: $SNAP" >&2; exit 2; }
[[ $CREATED =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || {
  echo "bad image created date: $CREATED" >&2
  exit 2
}
snap_fmt="${SNAP:0:4}-${SNAP:4:2}-${SNAP:6:2} ${SNAP:9:2}:${SNAP:11:2}:${SNAP:13:2}"
snap_epoch=$(date -u -d "$snap_fmt" +%s)
now=$(date -u +%s)
if [ "$snap_epoch" -ge "$now" ]; then
  echo "snapshot id is not in the past: $SNAP" >&2
  exit 1
fi
created_epoch=$(date -u -d "$CREATED" +%s)
if [ "$snap_epoch" -lt "$created_epoch" ]; then
  echo "snapshot id $SNAP is older than the base image ($CREATED)" >&2
  exit 1
fi
