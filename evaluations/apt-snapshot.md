<!-- SPDX-License-Identifier: Apache-2.0 -->

# Evaluation: a dated, signed apt snapshot for the Gazebo development image

Answers [#26](https://github.com/Living-Proof-Labs/livingproof-sim-gazebo/issues/26).
Evaluation only: this change edits no Dockerfile, lock or workflow. It is build
environment analysis, not a robot capability result: nothing here says anything
about hallway results, simulator behaviour or any robot.

**Recommendation:** adopt with a defined OSRF plan

In short: pin `snapshot.ubuntu.com` to one past snapshot ID for the Ubuntu pockets,
regenerate the exact lock together with that ID, and bump both in one reviewed
weekly PR. That removes the failure mode behind 2 of the 3 breaks in 18 days
(29 of 43 repaired pins). The 124 OSRF pins stay exposed in phase 1, covered by the
existing daily drift check plus recorded checksums, with a mirror held back until
OSRF breaks again (it did once, on 2026-11-01). Three points need a human decision
before implementation; they are listed under "Decisions needed".

## Method and what was and was not tested

The authoring box has no Docker, Podman or root, so no `docker build` was run
(the same limit as PR #24). Everything below was run with `apt-get` 3.0.4 in a private
directory tree, against the **real** `ubuntu:24.04@sha256:73b99939…` amd64 layer (pulled
anonymously from Docker Hub): its archive keyring, `ubuntu.sources` and `dpkg` status
(92 packages, image created 2026-11-10). [`evaluations/apt-snapshot/resolve-lock.sh`](apt-snapshot/resolve-lock.sh)
reproduces the lock test end to end:

```text
evaluations/apt-snapshot/resolve-lock.sh 20261118T000000Z /tmp/apt-snapshot-eval [--download]
```

All tests ran on 2026-11-18 against `main` at `4dd4817` (lock of 929 lines; 933 unique
pins once the Dockerfile's `curl`, `git`, `git-man` and `liberror-perl` bootstrap pins are
added; the issue's 934 counts `ca-certificates` twice).

Not tested, and so not claimed: a real image build; a TLS-inspecting proxy with a
private CA (only the apt `CaInfo` mechanism was exercised); apt's own `--snapshot`
option (the live `InRelease` files I fetched for `noble` and `noble-security` carry no
`Snapshots:` field, so I used explicit dated URIs, which is also what I recommend);
arm64; behaviour during a snapshot outage; retention beyond today.

## Q1 Retention and availability

Canonical documents snapshots for any date after 1 March 2023 and says it *intends* to
keep at least two years, possibly more if there is demand. That is an intention, not a
guarantee. Canonical staff have said on the Ubuntu Discourse that there are no rate
limits (obvious abuse is handled), that the service is centralised and so less
available than the mirrors, and that a status-page entry was "something we will look
into" (April 2025; I did not confirm one exists).

What I observed:

- Release files resolved (HTTP 200) for 20240425T000000Z, 20241101T000000Z and every
  tested ID from 20261101 to 20261118. `noble-updates` for 20230301T000000Z and
  20230228T000000Z returned 404 (before noble existed), as documented.
- **A snapshot ID after today is not an error: it silently serves today's latest
  archive** (I tried IDs one day and two weeks ahead and the `Date:` of the Release was
  today's). A future or mistyped ID therefore gives a moving pin. The ID must be in the
  past; the implementation needs a test for that.
- `http://snapshot.ubuntu.com` returns 500; only https works (see Q2 for why that matters).
- Plain `curl` downloads work (`HEAD` of `.deb` files with and without an apt user agent), so
  an earlier forum report that only apt can download did not reproduce here.
- Throughput is comparable: the same 21 MB `.deb` took 2.7 s from the snapshot and 2.4 s
  from `archive.ubuntu.com`. A full `apt-get -d install` of the lock set (851 packages,
  519 MB) took 4 min 16 s with no hash or fetch error; apt checked each file against
  the signed index.
- Release files carry `Acquire-By-Hash: yes` and no `Valid-Until`, so an old snapshot does
  not expire under apt's validity check.

Failure mode when the service is down: `apt-get update` fails and the build fails
closed, exactly as for an archive outage. There must be **no silent fallback** to the live
archive (that would defeat the pin). Retry with backoff is reasonable; a build cache or an
internal mirror is the real mitigation. A new dependency on one Canonical host is the
cost, set against 3 breaks in 18 days today.

## Q2 Signature verification and the CA-secret path

Signature verification works with the keyring the image already has.

- apt (with its `sqv` verifier) accepted `InRelease` for `noble`, `noble-updates`,
  `noble-backports` and `noble-security` at 20261118T000000Z using only
  `/usr/share/keyrings/ubuntu-archive-keyring.gpg` from the pinned base image. It holds
  `790B…1F32` (2012), `8439…1092` (2012 CD image) and `F6EC…C93C` (2018); the snapshot
  `InRelease` is signed by the 2018 archive key `F6ECB3762474EDA9D21B7022871920D1991BC93C`.
- Negative tests: an `InRelease` with one changed header line fails ("Message has been
  manipulated", repository "not signed"), and a genuine one fails against the wrong keyring
  ("Missing key F6EC…").

The CA-secret path works unchanged for a new hostname.

- `snapshot.ubuntu.com` presents a Let's Encrypt chain: `YR1`, `ISRG Root YR`, `ISRG Root X1`.
- With `Acquire::https::CaInfo` set to an unrelated root (DigiCert Global Root G2) every
  snapshot suite fails; with `ISRG_Root_X1.crt` alone, or the system bundle, `apt-get
  update` succeeds. So `CaInfo` is honoured for this host and certificate verification
  is not weakened. A private proxy CA delivered through the existing `ca` build secret
  should behave the same way but was not exercised.

**Bootstrap problem.** The base image has no `ca-certificates` (no `/etc/ssl/certs`), and the
snapshot is https only. Today's Dockerfile installs `ca-certificates` and `curl` over plain
http from the live archive first (apt still verifies signatures), and rewrites to https
only when the `ca` secret exists. With a snapshot, the first apt call after the switch
needs a CA bundle. Options:

1. Keep the http bootstrap for the CA bundle only, then switch sources to the snapshot
   and install the full pinned set, including the pinned `ca-certificates`. The bootstrap
   `ca-certificates` can no longer be an exact live-archive pin (that is the failure mode
   being removed), so it must be unpinned or resolved by apt policy for that one step.
2. Vendor a public root (ISRG Root X1, valid to 2035) and pass it as `CaInfo` for the
   snapshot host until the real bundle exists. Pins no package, but it is a vendored trust
   anchor in a security-relevant path, and Let's Encrypt can change its hierarchy.
3. Require the `ca` secret for every build (rejected: breaks the plain build).

Recommended: option 1. This is Decision 1.

Side observation, not caused by snapshots: host apt 3.0.4 with `sqv` rejects the **OSRF**
key (`D2486D2D…9743`, SHA-1 binding signatures, "not considered secure since
2026-02-01"). The image's apt 2.8.4 is expected to verify with gpgv and is not affected
today, but if a future apt or Ubuntu release verifies with `sqv`, `gazebo.gpg` will need
a refreshed key from OSRF. The evaluation script therefore marks the OSRF source
`Trusted: yes` for the simulation only.

## Q3 Security and updates pockets, and the current lock at a snapshot

Both pockets (and `noble` and `noble-backports`) are snapshotted, each resolved
independently to its latest state at or before the ID. At 20261118T000000Z the Release
dates were `noble-updates` 2026-11-17 23:37:10 UTC and `noble-security` 2026-11-17
21:40:30 UTC; at 20261117T000000Z they were 2026-11-16 17:31:46 and 2026-11-16 22:15:33.

Chosen snapshot for the test: **20261118T000000Z**, after the lock's last refresh (PR #24
and the libsqlite3 bump) and after the base image's creation date.

| Test | Result |
|---|---|
| Exact lock plus Dockerfile pins, empty dpkg status, 20261118T000000Z | 0 unavailable. 933 pins resolve to exactly 933 installed packages, 0 version mismatches, 0 extra dependencies: the lock is a closed set. |
| Same, with the real base image's dpkg status (as the Docker build would see it) | Resolves: 848 new, 3 upgraded, 0 removed, no downgrade. 89 pins already satisfied by the image. |
| `apt-get -d install` of that set | 851 `.deb` files, 519 MB, 0 errors; all checked against the signed index. |
| Same lock at 20261117T000000Z | **9 unavailable**: `alsa-ucm-conf 1.2.10-1ubuntu5.16` and the eight Mesa `25.2.8-0ubuntu0.24.04.5` pins, exactly the set PR #24 had to refresh. |
| Unpinned lock names at 20261101T000000Z, image from 2026-11-10 | Fails: `libpcre2-8-0` would have to be **downgraded** from the image's version. |
| Unpinned lock names at 20261111T000000Z vs the current lock | 14 of the 838 pins apt had to install would resolve to different versions: about 1.7% moved in 7 days. |

Consequences: (a) the lock must be regenerated whenever the ID moves (the ID alone does
not replace it), (b) the snapshot ID must not be older than the base image's build, and
Renovate's weekly `ubuntu:24.04` digest bump can break that ordering, so a test must
compare them, and (c) a snapshot dated at the last good lock would have prevented the
#23 break, as the PR #24 author reported; the 20261117 result confirms it.

## Q4 OSRF

124 of the 933 pins (13%, 32.5 MB) come from `packages.osrfoundation.org/gazebo/ubuntu-stable`
(gz-sensors 41, gz-common 17, gz-physics 14, gz-transport 8, gz-rendering 7, and others).

- There is no snapshot service. The index lists **one version per package** (0 of 579
  packages have more than one), and superseded files leave the pool: the 7.8.0 `.deb` of
  `libgz-physics7-tpelib-dev` returns 404 while 7.9.0 returns 200. That is the 2026-11-01
  break (`a9e0b87`, 14 pins). The 124 currently pinned files all return 200.
- So these pins keep today's failure mode, a snapshot or not.

Options considered:

| Option | Cost | Verdict |
|---|---|---|
| Accept the residual risk, keep the daily drift check, record each OSRF `.deb` sha256 next to its pin | Nearly free; breaks still need a manual refresh | Phase 1 |
| Mirror the 124 `.deb` files (32.5 MB) as release assets or a small apt repo, verified by sha256 | A new artifact to publish and secure; a second signing story | Only if OSRF breaks again after phase 1 |
| Commit the `.deb` files to git | 32 MB of binaries that change on every OSRF release | Rejected |

This is the defined OSRF plan: accept and monitor in phase 1, record the checksums, and
decide on the mirror after the first post-snapshot OSRF break. OSRF caused 1 of 3 breaks
so far. A mirror now would be work for a risk that has not repeated.

## Q5 Is a monitoring-only alternative sufficient?

No. The daily check (`check-apt-pins.yml`, #31/#34) is in place: one manual run passed on
2026-11-18, and its first scheduled run is 06:17 UTC on 2026-11-19 (17:17 Sydney time).
It detects a pin that has gone missing from the live index, within a day. It cannot
prevent the break: Ubuntu removes a version at publication time, and every build and
PR between then and the manual refresh fails. It also does not open an issue or a PR; it
fails a scheduled workflow. Three breaks in 18 days (2026-11-01, 2026-11-13/14, 2026-11-18)
each blocked `main` until a person refreshed the lock by hand.

A scheduled lock-refresh PR (regenerate pins from the live index) is an in-between option.
It cuts the toil but not the reproducibility problem: the lock still moves under a
running PR, and the refresh itself can land while the archive is changing. With a
snapshot, the ID and the lock change together in one reviewed PR, so nothing moves
between bumps. Keep the daily check, pointed at the **live** archive, as an early
warning of how far behind the snapshot is (and, unchanged, for OSRF).

## Q6 Bump cadence and ownership

Proposal:

- **Cadence:** weekly, matching Renovate's Monday-before-06:00-UTC window. The pinned ID
  is the latest `00:00:00Z` that is at least 24 hours old, so it is a past, settled ID.
  Observed cost: about 14 pins changed in 7 days, so a typical bump is a small diff.
- **Out of cycle:** bump at once when an Ubuntu Security Notice covers a package in the lock
  and the weekly bump is more than two days away. Security fixes arrive at most one
  cadence late, which is the price of the pin.
- **Mechanism:** a repo-local scheduled workflow computes the ID, regenerates the lock from
  the snapshot (`apt-get -s install` closure, as in the script) and opens a draft PR on a
  `apt-snapshot/` branch. CI then runs the full `task setup` build. Renovate has no
  datasource for snapshot IDs, so it cannot do this itself.
- **Ownership:** the repo's maintainers review and merge, like any dependency PR; the
  workflow only proposes. It never writes to `main`.
- **Consistency checks (tests):** the ID is in the past; the ID is not older than the base
  image's build date; the lock resolves at the ID with 0 unavailable; the Dockerfile and
  lock name the same ID; the drift check still runs against the live archive.

## Q7 Conflict with collaboration-guidelines

I read `collaboration-guidelines` v9.6.11 (`AGENTS.md`, `docs/developer-interface.md`,
`docs/dependency-updates.md`, the Renovate preset). Nothing there mentions apt, snapshots or
distribution archives. The convention asks for reproducible Docker setup with pinned base
images, tool versions and dependency locks; a dated snapshot with a regenerated exact lock
fits it, and the `ca` secret and https behaviour are repo-local Dockerfile concerns.

One point to confirm rather than decide locally (Decision 2): `dependency-updates.md`
describes Mend-hosted Renovate as the updater, with a narrowly scoped second writer only for
the docs brand lock. A snapshot bump needs its own writer. If a second writer for apt is
acceptable, no guideline change is needed. If it is not, the shared document needs
a change first, and this repo should not diverge. The current guideline version is
the one the repo's Renovate preset already pins; `AGENTS.md` in this repo still names
v6.0.0, which is a pre-existing mismatch I did not touch.

## Decisions needed

1. **CA bootstrap (Q2):** is one live-archive, unpinned `ca-certificates` install, before
   switching to the snapshot, acceptable? The alternative is a vendored ISRG root.
2. **Second writer (Q7):** may this repo add a scheduled apt-snapshot bump workflow
   alongside Mend-hosted Renovate?
3. **OSRF (Q4):** is "accept and monitor in phase 1, mirror only after a repeat break"
   acceptable, or should the mirror be built now?

## Draft implementation issue

Not filed: filing is a decision for Rivet. Proposed text:

> **Title:** Build the Gazebo development image from a dated Ubuntu snapshot
>
> Implements the recommendation in `evaluations/apt-snapshot.md` (#26). Scope: replace the
> Ubuntu archive and security sources with one dated `snapshot.ubuntu.com` snapshot, keep
> the exact lock, regenerate it per snapshot, and add the weekly bump workflow. OSRF
> pins stay on the live OSRF index in this issue.
>
> **Acceptance**
> - `Dockerfile` names one past snapshot ID; `noble`, `noble-updates`, `noble-backports`
>   and `noble-security` come from it with `Signed-By` the Ubuntu archive keyring; no
>   certificate or signature verification is weakened.
> - The CA bootstrap follows the decision in #26 and works with and without the `ca`
>   secret, with a test of the secret path.
> - `tools/ubuntu-packages.lock` is regenerated at that ID: 0 unavailable, 0 mismatches,
>   resolves against the pinned base image's dpkg status with no downgrade.
> - Tests: the ID is in the past; it is not older than the base image build date; the
>   Dockerfile and lock agree; the drift check still checks OSRF and the live archive.
> - A scheduled workflow proposes the weekly bump as a draft PR; it never writes to `main`.
> - A clean `task setup` build passes in CI on the exact head.
> - OSRF `.deb` sha256 values are recorded next to the OSRF pins.
> - Not described as a robot capability result.
