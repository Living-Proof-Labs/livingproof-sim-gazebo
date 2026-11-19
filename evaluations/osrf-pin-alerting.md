<!-- SPDX-License-Identifier: Apache-2.0 -->

# Scheduled OSRF pin alerts: deferred pending permission review

Decision for issue #53: retain the existing read-only daily check and GitHub
failed-run notifications. Do not activate issue-writing alerts in this change.
Rivet must sign off on any new permission before implementation or activation.
The verification automation App remains paused; no App or repository setting
change is part of this proposal.

A follow-up could add a separate alert job for failed **scheduled runs on main**,
with job-scoped `issues: write` and only `contents: read` where needed. The test
job should retain `contents: read`; do not grant write access to test execution.
No pull-request trigger, personal token, new secret, or App permission is needed
for the proposed workflow token design. Rivet still needs to approve it.

Use one stable marker in an alert issue's body, scoped to this repository and
workflow, and search both open and closed issues before creating anything.
Serialize alert updates with one concurrency group, then re-read the matching
issue inside the job to avoid concurrent duplicates. Update that same issue
with the latest run URL, head commit, failure summary and first/last failure
rather than creating a new issue or comment every day. Treat the run ID and
attempt as an idempotency key. On a successful scheduled run, record recovery
and close the matching alert; reopen the same issue on recurrence. Do not
interpret cancellation or missing test reports as recovery. Keep test failure
and alert-delivery failure visible separately; alert publication must never
turn a failed check green.

Before enabling this, test first failure, repeated failure, rerun, recovery,
recurrence, concurrent updates, missing reports and denied issue writes against
controlled fixtures. Review the exact workflow diff and minimal permissions
with Rivet. This document grants no permission and introduces no active alert.

The duplicated live hash comparison from #47 has been removed. The existing
architecture-aware `_check_osrf_sha256s` from #45 remains in the daily monitor,
with its controlled-index regression tests. Digest coverage now runs before
that comparison, so an OSRF-only pin cannot evade monitoring by dropping its
recorded digest. Offline recorded metadata and mutation tests protect local
changes without fetching indexes; the daily live check detects upstream drift.
