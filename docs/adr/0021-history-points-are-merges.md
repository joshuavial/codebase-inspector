# ADR-0021: History points are merges to main

Status: Accepted. Date: 2026-10-08.

## Context

The architecture changelog needs points in time to compare. Every commit is too noisy; time buckets lose which change did what. Work lands as pull requests merged to the default branch.

## Decision

A history point is a merge to the default branch (a merge commit, or the commit a squash-merged PR produced), falling back to every first-parent commit on the default branch when the repo has no merges. Each entry is the structural diff between consecutive points; points with no architectural change are skipped.

## Alternatives considered

- Every commit: finest grain, but buries real shifts under small commits and costs the most.
- Time buckets (daily or weekly): compact, but loses which PR made which change.

## Consequences

Entries line up with PRs, so the changelog reads like a list of landed work. Repos that commit directly to main still work through the fallback.
