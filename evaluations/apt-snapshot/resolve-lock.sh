#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Reproduce the #26 evaluation: does the exact apt lock resolve against one dated
# snapshot.ubuntu.com snapshot, with signatures verified by apt?
#
#   evaluations/apt-snapshot/resolve-lock.sh SNAPSHOT_ID [WORKDIR] [--download]
#
# Needs: bash, curl, tar, python3, apt-get with an https method and sqv or gpgv.
# No root and no Docker: it fetches the ubuntu:24.04 layer named by the Dockerfile
# digest from Docker Hub (anonymous pull) to get the image's own archive keyring,
# ubuntu.sources and dpkg status, then runs apt in a private directory tree.
#
# SNAPSHOT_ID must be in the past: a future ID is served as the moving latest archive.
# The OSRF gazebo-stable index is added as `Trusted: yes` ONLY so the simulation can
# resolve OSRF pins; it is not snapshotted and its signature is not checked here.
set -euo pipefail
SNAP=${1:?usage: resolve-lock.sh SNAPSHOT_ID [WORKDIR] [--download]}
shift
WORK=/tmp/apt-snapshot-eval
DOWNLOAD=
for arg in "$@"; do
  if [[ $arg == --download ]]; then
    DOWNLOAD=--download
  else
    WORK=$arg
  fi
done
WORK=$(realpath -m "$WORK")
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
[[ $SNAP =~ ^20[0-9]{6}T[0-9]{6}Z$ ]] || { echo "bad snapshot id: $SNAP" >&2; exit 2; }
# A future ID is not a pin: snapshot.ubuntu.com silently serves the moving latest archive.
python3 -c '
import sys
from datetime import datetime, timezone
when = datetime.strptime(sys.argv[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
raise SystemExit(0 if when < datetime.now(timezone.utc) else 1)
' "$SNAP" || { echo "snapshot id is not in the past: $SNAP" >&2; exit 2; }

mkdir -p "$WORK/img" "$WORK/apt/state/lists/partial" "$WORK/apt/cache/archives/partial"
digest=$(sed -n 's/^FROM ubuntu:24.04@\(sha256:[0-9a-f]\{64\}\).*/\1/p' "$ROOT/Dockerfile" | head -1)
[[ -n $digest ]] || { echo "no ubuntu:24.04 digest in Dockerfile" >&2; exit 2; }

if [[ ! -s $WORK/img/rootfs/var/lib/dpkg/status ]]; then
  api=https://registry-1.docker.io/v2/library/ubuntu
  tok=$(curl -fsS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/ubuntu:pull" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
  auth=(-H "Authorization: Bearer $tok")
  idx='application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json'
  amd64=$(curl -fsS "${auth[@]}" -H "Accept: $idx" "$api/manifests/$digest" | python3 -c '
import json, sys
for m in json.load(sys.stdin)["manifests"]:
    p = m["platform"]
    if p["os"] == "linux" and p["architecture"] == "amd64":
        print(m["digest"])')
  layer=$(curl -fsS "${auth[@]}" -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
    "$api/manifests/$amd64" | python3 -c 'import json,sys; print(json.load(sys.stdin)["layers"][0]["digest"])')
  curl -fsSL "${auth[@]}" "$api/blobs/$layer" -o "$WORK/img/layer.tgz"
  mkdir -p "$WORK/img/rootfs"
  tar -xzf "$WORK/img/layer.tgz" -C "$WORK/img/rootfs" --exclude='dev/*'
fi
IMG=$WORK/img/rootfs
KEYRING=$IMG/usr/share/keyrings/ubuntu-archive-keyring.gpg

mkdir -p "$WORK/apt/sources.list.d" "$WORK/apt/conf.d" "$WORK/apt/prefs.d"
cp "$IMG/var/lib/dpkg/status" "$WORK/apt/status"
snap=https://snapshot.ubuntu.com/ubuntu/$SNAP/
# Same suites and components as the image's ubuntu.sources (it also lists backports).
cat > "$WORK/apt/sources.list.d/ubuntu.sources" <<SRC
Types: deb
URIs: $snap
Suites: noble noble-updates noble-backports noble-security
Components: main universe restricted multiverse
Architectures: amd64
Signed-By: $KEYRING
SRC
cat > "$WORK/apt/sources.list.d/gazebo.sources" <<SRC
Types: deb
URIs: https://packages.osrfoundation.org/gazebo/ubuntu-stable
Suites: noble
Components: main
Architectures: amd64
Trusted: yes
SRC
cat > "$WORK/apt.conf" <<CONF
Dir::Etc::main "/dev/null";
Dir::Etc::parts "$WORK/apt/conf.d";
Dir::Etc::sourcelist "/dev/null";
Dir::Etc::sourceparts "$WORK/apt/sources.list.d";
Dir::Etc::preferences "/dev/null";
Dir::Etc::preferencesparts "$WORK/apt/prefs.d";
Dir::State "$WORK/apt/state";
Dir::State::status "$WORK/apt/status";
Dir::Cache "$WORK/apt/cache";
APT::Architecture "amd64";
APT::Architectures "amd64";
APT::Sandbox::User "";
Debug::NoLocking "true";
Acquire::Languages "none";
CONF
export APT_CONFIG=$WORK/apt.conf

echo "base image: ubuntu:24.04@$digest"
echo "snapshot:   $snap"
# Fail closed on any non-zero apt-get update, including failures that print no Err/E: line.
update_out=$(apt-get update 2>&1) || {
  printf '%s\n' "$update_out"
  echo "apt-get update failed (signature or fetch)" >&2
  exit 1
}
printf '%s\n' "$update_out"
if printf '%s\n' "$update_out" | grep -E '^(Err|E:)'; then
  echo "apt-get update failed (signature or fetch)" >&2
  exit 1
fi

mapfile -t pins < <(python3 - "$ROOT" <<'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
seen = {}
for line in (root / "tools/ubuntu-packages.lock").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        seen[line.split("=", 1)[0]] = line
for name, version in re.findall(
    r"(ca-certificates|curl|git-man|git|liberror-perl)=(\S+?)(?:;|\s|$)",
    (root / "Dockerfile").read_text(),
):
    seen.setdefault(name, f"{name}={version}")
print("\n".join(seen.values()))
PY
)
echo "pins:       ${#pins[@]} (lock plus Dockerfile bootstrap pins)"
set +e
apt-get -s install -y "${pins[@]}" > "$WORK/simulate.out" 2> "$WORK/simulate.err"
status=$?
set -e
if [[ $status -ne 0 ]]; then
  echo "RESULT: lock does NOT resolve at $SNAP"
  cut -c1-200 "$WORK/simulate.err" | head -30
  exit 1
fi
python3 - "$WORK/simulate.out" "$WORK/apt/status" "${pins[@]}" <<'PY'
import re, sys
chosen = {}
for line in open(sys.argv[1]):
    m = re.match(r"Inst (\S+) (?:\[\S+\] )?\((\S+) ", line)
    if m:
        chosen[m.group(1)] = m.group(2)
already = 0
for block in open(sys.argv[2]).read().split("\n\n"):
    fields = dict(
        line.split(": ", 1) for line in block.splitlines() if ": " in line and line[0] != " "
    )
    if "install ok installed" in fields.get("Status", "") and fields["Package"] not in chosen:
        chosen[fields["Package"]] = fields["Version"]
        already += 1
bad = [
    p for p in sys.argv[3:]
    if chosen.get(p.split("=", 1)[0].split(":")[0]) != p.split("=", 1)[1]
]
print(
    f"RESULT: lock resolves; {len(chosen) - already} packages would be installed "
    f"({already} base-image packages kept), {len(bad)} pin mismatches"
)
for p in bad[:20]:
    print("  mismatch:", p)
sys.exit(1 if bad else 0)
PY
grep -E '^[0-9]+ upgraded' "$WORK/simulate.out" || true
if [[ $DOWNLOAD == --download ]]; then
  apt-get -d -y install "${pins[@]}" 2>&1 | grep -E '^(E:|Err|Fetched)' || true
  echo "downloaded $(find "$WORK/apt/cache/archives" -name '*.deb' | wc -l) .deb files; apt checked each against the signed index"
fi
