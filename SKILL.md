---
name: context-harness-engineering
description: Intent-driven end-to-end skill for existing repositories. Use when the user says natural-language goals like “我想完成XX功能” / “implement feature X”. The skill must automatically run three stages in order: (1) Context Engineering to build/sync project context, (2) OpenSpec to define change scope and acceptance, (3) Harness Engineering to implement and harden with executable checks and CI gates. Do not require users to run `/opsx:*` commands manually.
---

# Context Harness Engineering

## Single User Entry (Only)
Accept one input style from users:
- Natural-language intent, e.g. `我想完成xx功能`.

Do not ask users to run OpenSpec command sequences manually.

### Trigger Guardrails
Trigger this skill only when the user intent implies software feature delivery or codebase change.
Do NOT trigger for pure Q&A, non-technical chat, or tasks without repository impact.
If intent is ambiguous, ask one clarification question before starting the pipeline.

## Internal Pipeline (Always this order)

### Stage 1 — Context Engineering (Foundation First)
1. Build/sync project context workspace.
2. Identify modules, entrypoints, agent routing, and current constraints.
3. Produce a reliable execution context before any spec planning.

Use:
```bash
python3 scripts/init_context_project.py --project <project> --code-dir <repo> [--target-root <root>]
python3 scripts/sync_context_project.py --project <project> --code-dir <repo> [--target-root <root>]
```

### Stage 2 — OpenSpec (Scope Definition)
1. Convert user intent into behavior-first change scope.
2. Define proposal/spec/design/tasks under OpenSpec artifact model.
3. Set explicit acceptance boundaries (in-scope / out-of-scope).

Rules:
- `openspec/specs/` = current behavior source of truth.
- `openspec/changes/<change>/` = proposed delta.
- Keep specs behavior-first, not implementation-first.

### Stage 2.5 — Scope Gate
Before implementation, classify scope risk:

- Low-risk: proceed automatically.
- Medium/High-risk (schema changes, data migration, auth/payment, destructive ops): require explicit user confirmation of scope.

Never auto-implement high-risk scope without confirmation.

### Stage 3 — Harness Engineering (Implementation + Governance)
1. Implement code changes according to approved scope.
2. Add/update repo-local governance artifacts as needed.
3. Enforce executable checks and CI gates.
4. Validate and report pass/fail/risk.

Minimum governance outcomes:
- No policy-only claims without executable enforcement.
- Run at least: lint, tests, type/build checks (or project equivalents).
- CI gate must cover the same required checks on push/PR.
- Critical references/contracts are not stale.
- Record command results in the final verification summary.

## Output Contract (User-visible)
After pipeline execution, always return:
1. Scope summary (in-scope / out-of-scope).
2. Implementation evidence (touched files/modules + key intent per change cluster).
3. Verification evidence (commands run + pass/fail + CI status).
4. Risks, blockers, and smallest next retry scope.

## Execution Example (Intent-driven)
### User input
`我想完成“用户可切换深色模式”功能。`

### Internal execution (automatic)
1. Context stage: build/sync context, identify affected modules (e.g., frontend theme system, settings, persistence).
2. OpenSpec stage: define change boundary, acceptance criteria, and task breakdown.
3. Harness stage: implement code + update repo-local docs/checks + run validation/CI checks.

### Expected output to user
- **Scope**: add dark-mode toggle, persist preference, update UI tokens; out of scope: redesign whole design system.
- **Implementation**: list touched files/modules and key logic changes.
- **Verification**: lint/test/check status, CI gate result.
- **Risks**: edge-case list (e.g., SSR hydration mismatch) and next actions.

## Failure Scenario Example (Mandatory transparency)
### Example failure
- Context and OpenSpec succeeded.
- Harness implementation completed.
- Verification failed: one required test suite failed and CI gate is red.

### Required user-facing response format
- **Status**: failed (not ready to merge)
- **What passed**: context build + scope definition + code implementation
- **What failed**: exact failing checks/tests and impacted modules
- **Risk**: what could break if force-merged
- **Next action**: concrete fix plan and estimated smallest retry scope

### Rule
Do not claim completion when verification fails. Always return actionable failure details.

### Failure State Management
- Keep work in an isolated branch/worktree until verification passes.
- On failure, do not merge; provide a minimal retry plan.
- Preserve reproducibility: include failing command, error signature, and impacted files.

## Non-Negotiable Constraints
- Use brownfield-first strategy: preserve existing runtime/product structure.
- Prefer incremental hardening over broad rewrites.
- If context docs and OpenSpec artifacts conflict, resolve before implementation.
- Do not hide failures: surface blockers explicitly.

## Loading Model for Context Workspaces (L1/L2/L3)
- **L1**: `projects/<project>/skill.md` — overview, routing, load order.
- **L2**: `agents/` and `modules/<module>/README.md` — pick agent, then module overview.
- **L3**: `modules/<module>/<module>.md`, `modules/<module>/<feature>.md`, `references/*` — deep evidence.

## Resources

### scripts/
- `init_context_project.py` — scaffold generator.
- `sync_context_project.py` — sync generator (Git incremental / non-Git full refresh).
- `validate_harness_contract.py` — harness-contract validator for generated agent docs.

### references/
- `extraction-rules.md` — code extraction guidance.
- `structure-rules.md` — module/agent structure rules.
- `output-templates.md` — output templates.
- `delivery-checklist.md` — delivery checklist.
- `openspec-integration.md` — OpenSpec integration notes.
