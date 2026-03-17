# Output Templates

Use this reference when filling generated L1/L2/L3 context documents.

## L1 (`skill.md`)

- Project summary (what it is + target users)
- Architecture & boundaries
- Agent routing and loading order
- Entrypoints + build/run
- Module navigation
- Progressive loading model (L1/L2/L3)
- Spec-driven development:
  - Spec-first rule (no implementation without a spec)
  - Spec template (scope, interfaces, edge cases/errors, acceptance criteria, tests)
  - Change control (spec updates recorded in decisions)
  - Traceability (code/tests map back to spec items)
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L2 (`modules/<module>/README.md`)

- Responsibilities
- Code-derived module summary (implementation structure, dominant areas, major responsibilities)
- Representative files with file + symbol evidence (line hint when available)
- Typical tasks
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L2 (`modules/<module>/<module>.md`)

- Scope
- Functional Subdomains
- Key Responsibilities
- Important Notes (constraints, risks, decisions)
- Interfaces & Dependencies
- Code-derived implementation summary before detailed evidence lists
- Key flows with file + symbol evidence (line hint when available) when applicable
- Testing/QA hooks with file + symbol evidence (line hint when available) when applicable
- If an AUTO block is present, it should read like a usable module summary generated from code, with representative evidence attached where helpful.
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L3 (`modules/<module>/<feature>.md`)

- Feature scope inside the parent technical module
- Code-derived feature summary (implementation structure, dominant responsibilities, key areas)
- Responsibilities for that specific business slice
- Representative files with file + symbol evidence (line hint when available)
- Entrypoints with file + symbol evidence (line hint when available)
- Testing hooks with file + symbol evidence (line hint when available)
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L2 (`agents/<agent>/README.md`)

- Role
- Harness contract (mission, scope boundary, explicit non-goals)
- Principles
- Operating invariants (rules enforced mechanically, not by ad-hoc preference)
- Responsibilities
- Deliverables
- Task loop for execution (`observe -> plan -> act -> verify -> record`)
- Escalation and stop conditions (when to widen scope or hand off to human judgment)
- Working Style
- Notes
- Module-loading responsibility for this agent
- Description of other files in the agent directory
- Generated content must be usable as real sub-agent initialization context, not left as placeholders or TODO-only text.
- Generated `AUTO` blocks are schema-gated by sync; missing required harness sections should fail generation.

## L2 (`agents/<agent>/tools.md`)

- Command surface the agent can run directly (no copy-paste handoff)
- Verification commands grouped by runtime, tests, and architecture guardrails
- Entrypoint and manifest evidence refs
- Feedback-loop hooks (what to rerun after each fix)
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.
- Generated `AUTO` blocks are schema-gated by sync; missing required harness markers should fail generation.

## L2 (`agents/<agent>/memory.md`)

- Stable scope roots and adjacent-module boundaries
- System-of-record pointers in-repo (where truth lives for this scope)
- Re-entry evidence refs for fast context reload
- Drift watchlist and recurring failure patterns
- Escalation triggers and judgment-only handoff criteria
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.
- Generated `AUTO` blocks are schema-gated by sync; missing required harness markers should fail generation.

## L3 (`references/entrypoints.md`)

- Entry file index with file + symbol evidence (line hint when available)
- Core logic/index files
- Data/storage index
- i18n index
- Build/release/ops entrypoints
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L3 (`references/feature-map.md`)

- Shared business features across technical modules
- Links such as `frontend/new-sign.md` and `backend/new-sign.md`
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L3 (`references/requirements-map.md`)

- PRD requirement candidates and trace rows (`req_id`, `prd_ref`, `feature_keys`, `modules`)
- Mapped code/test references for each requirement row
- Confidence and status (`mapped`, `partial`, `unresolved`) for delivery gating
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.

## L3 (`references/domain-model.md`)

- Inferred domain rows keyed by module + feature (`entity`, `feature_key`, `module`)
- Linked requirement IDs (`linked_requirements`) when PRD matching exists
- Candidate states and business rules inferred from code-level evidence
- Confidence and status (`mapped`, `partial`, `unresolved`) for review prioritization
- Keep generated content inside a managed `AUTO` block so manual notes can live around it.
