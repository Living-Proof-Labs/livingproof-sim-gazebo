<!-- SPDX-License-Identifier: Apache-2.0 -->

# Recorded OSRF lock metadata

`osrf-locked-packages.json` contains the package, version, architecture,
dependencies and digest fields from the OSRF Noble amd64 index fetched on
2026-11-19:

https://packages.osrfoundation.org/gazebo/ubuntu-stable/dists/noble/main/binary-amd64/Packages.gz

The compressed source SHA256 was
`001aaad5adf89261230dbd54202fa85ec3a501bd387369e6d61fa3d92bd80daa`.
The selection contains all 124 OSRF package names recorded in main's lock at
`64435ebe0e6667c99223730c6f2a2f78ec66c52d`. Of those, 123 match the locked version.
The index no longer contains `libgz-cmake3-dev=3.6.0-1~noble`; its actual current
3.7.0 stanza is retained. The offline check intentionally reports that missing
version instead of inventing old metadata or silently omitting the package.
The old package's pool URL also returned HTTP 404. Repair of that pin needs a
separate reviewed lock update before the real-lock dependency test can pass.

The fixture is independent of the lock under test: do not regenerate it from
lock versions or hashes. To refresh after a reviewed pin change, fetch the URL,
record its compressed SHA256 and date, parse the Debian control stanzas, select
all locked OSRF package names and their exact versions, and retain only
`Package`, `Version`, `Architecture`, `Depends`, `Pre-Depends`, and `SHA256`.
Sort by `Package` and serialize as indented JSON. Explicitly investigate any
missing version. The fixture guard also fails if a digest-bearing lock package
has no recorded metadata. New OSRF packages without digests are discovered by
the live monitor; refresh the fixture when adding them.

Offline digest coverage conservatively requires a hash for every recorded OSRF
package name, including a stale version. The live monitor exempts a version
available in Ubuntu and discovers newly added OSRF packages without relying on
recorded hashes. The offline fixture is not a claim about current availability.

Mutation tests use a scratch lock consistent with this recorded index so an
existing unrelated pin defect cannot mask the mutation. Separate tests run the
same guards against the actual committed lock. Exact `Depends` and `Pre-Depends`
are checked, including missing dependencies and continuation lines. This is not
an apt solver: unsupported exact-version alternatives fail explicitly; none
occur in this captured set. Non-exact constraints remain apt's responsibility.
