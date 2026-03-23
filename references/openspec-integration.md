# OpenSpec Integration Notes

This note captures the OpenSpec concepts to blend into Context + Harness Engineering.

## Philosophy (keep these as operating principles)
- fluid not rigid
- iterative not waterfall
- easy not complex
- brownfield-first

## Core Structure
- `openspec/specs/` is the **source of truth** for current behavior.
- `openspec/changes/<change-name>/` contains proposed modifications:
  - `proposal.md` (why / scope)
  - `specs/` (delta specs)
  - `design.md` (technical approach)
  - `tasks.md` (implementation checklist)

## Recommended Workflow Mapping

### Quick path (default profile)
1. `/opsx:propose <change>`
2. `/opsx:apply`
3. `/opsx:archive`

### Expanded path (full profile)
1. `/opsx:new <change>`
2. `/opsx:continue` or `/opsx:ff`
3. `/opsx:apply`
4. `/opsx:verify`
5. `/opsx:archive`

## How to Merge with This Skill
1. Use context-engineering scripts to build/refresh team context under `~/clawDir/team`.
2. Use harness workflow to harden repo-local docs/checks/CI.
3. Use OpenSpec change folders to manage requirement deltas and implementation sequencing.
4. Keep repo-local docs and OpenSpec artifacts aligned:
   - Context docs explain architecture and module boundaries.
   - OpenSpec `specs/` and `changes/` express behavior contracts and deltas.

## Practical Guardrails
- Prefer incremental updates over rewrites.
- Keep specs behavior-first (what), not implementation-first (how).
- Require executable validation before archive.
- Archive only when tasks are done and spec deltas are synced.
