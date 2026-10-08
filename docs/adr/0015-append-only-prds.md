# ADR-0015: PRDs are an append-only sequence

Status: Accepted. Date: 2026-10-07.

## Context

PRD-01 was written, and partly built, when the list viewer was rejected. The concept map contradicts a non-goal and the list-view requirements in that PRD. Rewriting PRD-01 would erase what the first increment had promised. The interview had also assigned PRD numbers before the later increments existed. Change review was PRD-02. The concept map took that number. A data map was then called PRD-03 and change review moved to PRD-04. The desktop app was inserted after that.

## Decision

PRDs are an append-only sequence. A new concern becomes the next PRD. The earlier document stays as it was written. The new PRD names each requirement it replaces.

The sequence is:

1. PRD-01, orientation map.
2. PRD-02, concept map. It amends PRD-01. It replaces the list viewer (R19 to R21) and the non-goal that banned regrouping files across folders. See ADR-0011.
3. PRD-03, desktop app.
4. PRD-04, change review.
5. PRD-05, data map. Not written yet: schema rebuilt from SQL migrations, queries parsed into table reads and writes, an ERD with the tables a concept or function touches. sample-desktop has no database, so the targets are sample-apps and sample-saas.

The quiz, and live rendering of real UI components, stay in the vision with no PRD number yet.

This replaces the increment numbering in ADR-0001. The orientation map remains the first increment.

## Alternatives considered

- Rewrite PRD-01 so the concept map is the original viewer.
- Keep change review as PRD-02, which is what the interview decided first.
- Number the data map as PRD-03 and change review as PRD-04, which was the order before the desktop app was added.
- Fold the data map into the concept map. It is its own increment because the first target repository cannot exercise it.

## Consequences

A reader of PRD-01 still sees the list viewer. PRD-02 is where that viewer is replaced. Architecture cites both. A later concern adds a new PRD number. Written PRDs keep their file names. The numbers that moved were for PRDs that had not been written yet.
