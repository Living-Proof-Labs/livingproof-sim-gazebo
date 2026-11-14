# Contribute

Use a focused [pull request](https://github.com/Living-Proof-Labs/livingproof-sim-gazebo/pulls)
and report non-sensitive problems through [issues](https://github.com/Living-Proof-Labs/livingproof-sim-gazebo/issues).
The repository adopts [collaboration-guidelines v6.0.0](https://github.com/Living-Proof-Labs/collaboration-guidelines/tree/v6.0.0), with the local additions in
[AGENTS.md](https://github.com/Living-Proof-Labs/livingproof-sim-gazebo/blob/main/AGENTS.md).
Original code and documentation are [Apache-2.0](https://github.com/Living-Proof-Labs/livingproof-sim-gazebo/blob/main/LICENSE).
The downloaded shared brand retains its upstream license and attribution.
No dedicated security reporting route is established here; do not post secrets in public issues.

This documentation change selectively adopts the
[documentation recipe at v7.9.1](https://github.com/Living-Proof-Labs/collaboration-guidelines/blob/v7.9.1/docs/documentation-recipe.md)
(resolved commit `26c453379c664eb382775e5b5c070cb76b424590`) and its shared brand.
It does not upgrade the v6.0.0 engineering baseline or runtime dependencies.
Current documentation-home, sibling-manual and source-directory links are the recipe's
bounded navigation exception to dependency pinning.

## Build

Run `task setup`, then `task docs` on a Docker host or in the prepared development
container. `task docs:reference` refreshes the actual command and Task references;
`task check` checks their freshness. The manual build stages existing Markdown,
checks the pinned brand digest, records the checked-out Git revision, builds with
Zensical, and checks rendered local links, fragments and brand inclusion.
Review output in `artifacts/manual/`; serve that directory with a static HTTP server.

## Publication

The existing Gazebo verification workflow uploads only `artifacts/manual/` for
Pages after all verification, packaging and smoke steps succeed on `main`.
A separate deployment job uses the `github-pages` environment with Pages and
identity-token write permissions; pull requests never deploy. Immediately before
deployment, the job reads the current main ref through the GitHub API and refuses
a stale workflow revision. API failures also stop deployment. The workflow-wide
main concurrency group stays held through this check and deployment, so an old
rerun cannot overwrite a newer deployment.

Prerequisites: enable GitHub Pages with GitHub Actions as its source, allow the
pinned Pages actions, and restrict the `github-pages` deployment environment to
`main`. These settings require separately authorized setup; this PR changes none.
The organization domain must route the repository Pages path. The workflow's
reported `page_url` is authoritative; the configured URL alone proves nothing.
After merge and deployment, verify source identity, README navigation, deep links,
search, sibling links, and desktop/mobile/keyboard use before marking the manual live.
Review artifacts last 14 days; the Pages transfer artifact lasts one day.

## Adoption limits

Existing authored pages, headings, command and Task generators are preserved.
There is no separately supported public library API documented here.
Hallway contract and scenario semantics remain in the existing hallway guide;
this change does not introduce a parallel scenario inventory or claim current results.
Measured line coverage and browsable scenario-result integration are not available.
Independent review and live deployment verification remain required adoption evidence.
