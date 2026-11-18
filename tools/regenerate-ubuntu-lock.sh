#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Resolve tools/ubuntu-packages.lock against one dated snapshot.ubuntu.com
# snapshot, hash-check the pinned ubuntu:24.04 amd64 layer, and optionally
# write the lock (with OSRF sha256 values) and the snapshot ID back to the repo.
#
#   tools/regenerate-ubuntu-lock.sh SNAPSHOT_ID [WORKDIR] [--download] [--write] [--refresh]
#
# Needs: bash, curl, tar, python3, sha256sum, apt-get with an https method.
# No root and no Docker: it fetches the ubuntu:24.04 layer named in
# tools/ubuntu-snapshot.pin from Docker Hub (anonymous pull).
#
# SNAPSHOT_ID must be in the past and not older than the base image. A future
# ID is served as the moving latest archive. OSRF is added as Trusted: yes
# ONLY so the host apt 3.0.4/sqv simulation can resolve OSRF pins; the image
# itself verifies gazebo.gpg and is not weakened. The locked install is
# simulated with --no-install-recommends.
set -euo pipefail
SNAP=${1:?usage: regenerate-ubuntu-lock.sh SNAPSHOT_ID [WORKDIR] [--download] [--write] [--refresh]}
shift
WORK=
DOWNLOAD=
WRITE=
REFRESH=
for arg in "$@"; do
  case $arg in
    --download) DOWNLOAD=1 ;;
    --write) WRITE=1 ;;
    --refresh) REFRESH=1 ;;
    --*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *) WORK=$arg ;;
  esac
done

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PIN=$ROOT/tools/ubuntu-snapshot.pin
[[ $SNAP =~ ^20[0-9]{6}T[0-9]{6}Z$ ]] || { echo "bad snapshot id: $SNAP" >&2; exit 2; }
created=$(sed -n 's/^UBUNTU_IMAGE_CREATED=//p' "$PIN")
bash "$ROOT/tools/check-snapshot-id.sh" "$SNAP" "$created"

image_digest=$(sed -n 's/^UBUNTU_IMAGE_DIGEST=//p' "$PIN")
amd64_manifest=$(sed -n 's/^UBUNTU_AMD64_MANIFEST=//p' "$PIN")
amd64_layer=$(sed -n 's/^UBUNTU_AMD64_LAYER=//p' "$PIN")
[[ $image_digest =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "bad image digest in pin file" >&2; exit 2; }

df_digest=$(sed -n 's/^FROM ubuntu:24.04@\(sha256:[0-9a-f]\{64\}\).*/\1/p' "$ROOT/Dockerfile" | head -1)
if [[ $df_digest != "$image_digest" ]]; then
  echo "Dockerfile ubuntu:24.04 digest $df_digest does not match pin file $image_digest" >&2
  exit 2
fi

WORK=$(realpath -m "${WORK:-/tmp/apt-snapshot-regen}")
mkdir -p "$WORK/img" "$WORK/apt/state/lists/partial" "$WORK/apt/cache/archives/partial"

if [[ ! -s $WORK/img/layer.tgz ]]; then
  api=https://registry-1.docker.io/v2/library/ubuntu
  tok=$(curl -fsS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/ubuntu:pull" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
  auth=(-H "Authorization: Bearer $tok")
  idx='application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json'
  got_manifest=$(curl -fsS "${auth[@]}" -H "Accept: $idx" "$api/manifests/$image_digest" | python3 -c '
import json, sys
for m in json.load(sys.stdin)["manifests"]:
    p = m["platform"]
    if p["os"] == "linux" and p["architecture"] == "amd64":
        print(m["digest"])')
  if [[ $got_manifest != "$amd64_manifest" ]]; then
    echo "amd64 manifest $got_manifest does not match pin file $amd64_manifest" >&2
    exit 1
  fi
  got_layer=$(curl -fsS "${auth[@]}" -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
    "$api/manifests/$amd64_manifest" | python3 -c 'import json,sys; print(json.load(sys.stdin)["layers"][0]["digest"])')
  if [[ $got_layer != "$amd64_layer" ]]; then
    echo "amd64 layer $got_layer does not match pin file $amd64_layer" >&2
    exit 1
  fi
  curl -fsSL "${auth[@]}" "$api/blobs/$amd64_layer" -o "$WORK/img/layer.tgz"
fi
expected=${amd64_layer#sha256:}
got=$(sha256sum "$WORK/img/layer.tgz" | awk '{print $1}')
if [[ $got != "$expected" ]]; then
  echo "ubuntu amd64 layer hash $got does not match $amd64_layer" >&2
  exit 1
fi
if [[ ! -s $WORK/img/rootfs/var/lib/dpkg/status ]]; then
  mkdir -p "$WORK/img/rootfs"
  tar -xzf "$WORK/img/layer.tgz" -C "$WORK/img/rootfs" --exclude='dev/*'
fi
IMG=$WORK/img/rootfs
KEYRING=$IMG/usr/share/keyrings/ubuntu-archive-keyring.gpg

mkdir -p "$WORK/apt/sources.list.d" "$WORK/apt/conf.d" "$WORK/apt/prefs.d"
cp "$IMG/var/lib/dpkg/status" "$WORK/apt/status"
snap=https://snapshot.ubuntu.com/ubuntu/$SNAP/
cat > "$WORK/apt/sources.list.d/ubuntu.sources" <<SRC
Types: deb
URIs: $snap
Suites: noble noble-updates noble-backports noble-security
Components: main universe restricted multiverse
Architectures: amd64
Signed-By: $KEYRING
SRC
# Host apt 3.0.4 with sqv rejects the OSRF key; Trusted: yes is only for this
# simulation. The image verifies packages.osrfoundation.org with gazebo.gpg.
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

echo "base image: ubuntu:24.04@$image_digest"
echo "layer:      $amd64_layer (hash checked)"
echo "snapshot:   $snap"
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

mapfile -t pins < <(python3 - "$ROOT" "$REFRESH" <<'PY'
import os, re, sys
from pathlib import Path
root = Path(sys.argv[1])
refresh = sys.argv[2] == "1"
extras = {
    "less", "libcbor0.10", "libfido2-1", "libxmuu1",
    "openssh-client", "patch", "xauth",
}
seen = {}
for line in (root / "tools/ubuntu-packages.lock").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        name, rest = line.split("=", 1)
        version = rest.split()[0]
        base = name.split(":", 1)[0]
        if base in extras:
            continue
        seen[name] = name if refresh else f"{name}={version}"
# curl is needed after the snapshot switch to fetch Task; it was a Dockerfile
# bootstrap pin and must live in the lock so it comes from the snapshot.
if "curl" not in seen and "curl:amd64" not in seen:
    text = (root / "Dockerfile").read_text()
    found = re.search(r"\bcurl=(\S+?)(?:;|\s|$)", text)
    seen["curl"] = "curl" if refresh else f"curl={found.group(1) if found else '8.5.0-2ubuntu10.16'}"
print("\n".join(seen.values()))
PY
)
echo "pins:       ${#pins[@]} (lock plus curl, minus unused Recommends extras)"
set +e
apt-get -s install -y --no-install-recommends "${pins[@]}" > "$WORK/simulate.out" 2> "$WORK/simulate.err"
status=$?
set -e
if [[ $status -ne 0 ]]; then
  echo "RESULT: lock does NOT resolve at $SNAP"
  cut -c1-200 "$WORK/simulate.err" | head -30
  exit 1
fi
python3 - "$WORK/simulate.out" "$WORK/apt/status" "$WORK/resolved.txt" "${pins[@]}" <<'PY'
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
requested = sys.argv[4:]
bad = []
resolved = []
for pin in requested:
    name, _, version = pin.partition("=")
    short = name.split(":")[0]
    have = chosen.get(name) or chosen.get(short)
    if have is None:
        bad.append(pin)
        continue
    if version and have != version:
        bad.append(pin)
        continue
    resolved.append(f"{name}={have}")
print(
    f"RESULT: lock resolves; {len(chosen) - already} packages would be installed "
    f"({already} base-image packages kept), {len(bad)} pin mismatches, "
    f"{len(resolved)} lock pins"
)
for pin in bad[:20]:
    print("  mismatch:", pin)
if bad:
    sys.exit(1)
with open(sys.argv[3], "w") as fh:
    fh.write("\n".join(resolved) + "\n")
PY
grep -E '^[0-9]+ upgraded' "$WORK/simulate.out" || true

# Collect OSRF sha256 values from the live index (not the Ubuntu snapshot).
python3 - "$WORK" "$ROOT/tools/ubuntu-packages.lock" "$WORK/resolved.txt" "$WORK/osrf-sha256.txt" <<'PY'
import gzip, os, sys
from pathlib import Path
from collections import defaultdict

work, old_lock, resolved, dest = sys.argv[1:]
# Find the OSRF Packages file apt just fetched.
candidates = list(Path(work).joinpath("apt/state/lists").glob("*osrfoundation*Packages*"))
if not candidates:
    # Fall back to a direct fetch if the list name differs.
    import urllib.request
    url = (
        "https://packages.osrfoundation.org/gazebo/ubuntu-stable/"
        "dists/noble/main/binary-amd64/Packages.gz"
    )
    payload = gzip.decompress(urllib.request.urlopen(url, timeout=60).read()).decode()
else:
    data = candidates[0].read_bytes()
    payload = gzip.decompress(data).decode() if data[:2] == b"\x1f\x8b" else data.decode()

index = {}  # (name, version) -> sha256, also name:arch
name = version = arch = sha = None
def commit():
    if name and version and sha:
        index[(name, version)] = sha
        if arch:
            index[(f"{name}:{arch}", version)] = sha
for line in payload.splitlines():
    if line.startswith("Package:"):
        commit()
        name, version, arch, sha = line.split(":", 1)[1].strip(), None, None, None
    elif line.startswith("Version:"):
        version = line.split(":", 1)[1].strip()
    elif line.startswith("Architecture:"):
        arch = line.split(":", 1)[1].strip()
    elif line.startswith("SHA256:"):
        sha = line.split(":", 1)[1].strip()
    elif line == "":
        commit()
        name = version = arch = sha = None
commit()

pins = {}
for path in (old_lock, resolved):
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg, rest = line.split("=", 1)
        pins[pkg] = rest.split()[0]

found = {}
missing = []
for pkg, ver in pins.items():
    sha = index.get((pkg, ver)) or index.get((pkg.split(":")[0], ver))
    # Only record digests for packages that are in the OSRF index.
    key_hit = (pkg, ver) in index or (pkg.split(":")[0], ver) in index
    if key_hit:
        if not sha:
            missing.append(f"{pkg}={ver}")
        else:
            found[pkg] = sha
if missing:
    print("missing OSRF sha256 for:", ", ".join(missing[:20]), file=sys.stderr)
    raise SystemExit(1)
print(f"OSRF pins with sha256: {len(found)}")
Path(dest).write_text("".join(f"{n} {s}\n" for n, s in sorted(found.items())))
PY

if [[ -n ${DOWNLOAD:-} ]]; then
  apt-get -d -y --no-install-recommends install "${pins[@]}" 2>&1 | grep -E '^(E:|Err|Fetched)' || true
  echo "downloaded $(find "$WORK/apt/cache/archives" -name '*.deb' | wc -l) .deb files; apt checked each against the signed index"
fi

if [[ -n ${WRITE:-} ]]; then
  python3 - "$ROOT" "$SNAP" "$image_digest" "$amd64_layer" "$created" "$WORK/resolved.txt" "$WORK/osrf-sha256.txt" <<'PY'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
snap, image, layer, created, resolved, osrf_path = sys.argv[2:]
osrf = {}
for line in pathlib.Path(osrf_path).read_text().splitlines():
    name, sha = line.split()
    osrf[name] = sha
# Prefer arch-qualified names from the previous lock when both exist? The
# resolved file uses apt's short names. Keep previous lock names when the
# version is unchanged so the diff stays small.
previous = {}
for line in (root / "tools/ubuntu-packages.lock").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        name, rest = line.split("=", 1)
        previous[name] = rest.split()[0]
chosen = {}
for line in pathlib.Path(resolved).read_text().splitlines():
    name, version = line.split("=", 1)
    chosen[name] = version
# Rebuild using previous names when possible.
lines = {}
for name, version in chosen.items():
    # If the old lock used name:amd64 and apt printed name, keep name:amd64
    # when versions match.
    lines[name] = version
for old_name, old_ver in previous.items():
    base = old_name.split(":")[0]
    if old_name in lines:
        continue
    if base in lines and lines[base] == old_ver:
        lines[old_name] = lines.pop(base)
    elif base in lines:
        lines[old_name] = lines.pop(base)
# Ensure curl is present under the short name.
if "curl:amd64" in lines and "curl" not in lines:
    lines["curl"] = lines.pop("curl:amd64")
elif "curl" not in lines and "curl:amd64" not in lines:
    raise SystemExit("curl missing from resolved lock")
# Drop unused Recommends extras if they slipped in.
for extra in (
    "less", "libcbor0.10", "libfido2-1", "libxmuu1",
    "openssh-client", "patch", "xauth",
):
    lines.pop(extra, None)
    lines.pop(f"{extra}:amd64", None)

header = (
    "# SPDX-License-Identifier: Apache-2.0\n"
    f"# Ubuntu snapshot: {snap}\n"
    f"# Base image: ubuntu:24.04@{image}\n"
    f"# amd64 layer: {layer}\n"
    f"# Image created: {created}\n"
)
body = []
for name in sorted(lines, key=str.lower):
    version = lines[name]
    sha = osrf.get(name) or osrf.get(name.split(":")[0])
    if sha:
        body.append(f"{name}={version} sha256:{sha}\n")
    else:
        body.append(f"{name}={version}\n")
(root / "tools/ubuntu-packages.lock").write_text(header + "".join(body))
print(f"wrote {len(body)} pins to tools/ubuntu-packages.lock ({sum(1 for n in lines if osrf.get(n) or osrf.get(n.split(':')[0]))} with OSRF sha256)")

# Keep the pin file and Dockerfile ARG in agreement with the lock header.
pin = (root / "tools/ubuntu-snapshot.pin").read_text()
pin = re.sub(r"^UBUNTU_SNAPSHOT=.*$", f"UBUNTU_SNAPSHOT={snap}", pin, flags=re.M)
(root / "tools/ubuntu-snapshot.pin").write_text(pin)
df = (root / "Dockerfile").read_text()
df, n = re.subn(r"^ARG UBUNTU_SNAPSHOT=.*$", f"ARG UBUNTU_SNAPSHOT={snap}", df, flags=re.M)
if n != 1:
    raise SystemExit(f"expected one ARG UBUNTU_SNAPSHOT in the Dockerfile, found {n}")
(root / "Dockerfile").write_text(df)
PY
fi
