# Delivery Checklist

Use this reference before finalizing a generated or synced project context.

## Quality Checklist

- L1 filled with accurate architecture and run/build info
- Each module has README + `<module>.md`
- Stable business slices are documented as `<feature>.md` files under the relevant technical module when they can be inferred safely
- References contain concrete file paths
- Requirement trace map is generated when PRD docs are provided under `references/prd.md` or `references/prd/*.md`
- Loading paths cover UI/UX, core logic, QA, release scenarios
- Agent folders exist with clear responsibilities
- Mandatory review completed after generation/sync
- No unresolved placeholder `TODO` content in delivered context unless explicitly marked as pending
- Runtime entrypoints are separated from build/config/release files
- Major functional modules in the codebase are represented in context, either as top-level modules or documented submodules
- `project_status.md` and other summary files do not obviously contradict the current project state

## Files Created

- `<target_root>/readme.md` (if missing)
- `<target_root>/sources/<project_name>/` (when `git_url` is used)
- `<target_root>/projects/projects.md` (index with new project entry)
- `<target_root>/projects/<project_name>/readme.md`
- `<target_root>/projects/<project_name>/goals.md`
- `<target_root>/projects/<project_name>/skill.md`
- `<target_root>/projects/<project_name>/project_status.md`
- `<target_root>/projects/<project_name>/decisions.md`
- `<target_root>/projects/<project_name>/agents/agents.md`
- `<target_root>/projects/<project_name>/modules/README.md`
- `<target_root>/projects/<project_name>/modules/<module>/README.md` (modules inferred from code)
- `<target_root>/projects/<project_name>/modules/<module>/<module>.md`
- `<target_root>/projects/<project_name>/modules/<module>/<feature>.md` (when stable business slices are inferred)
- `<target_root>/projects/<project_name>/references/entrypoints.md`
- `<target_root>/projects/<project_name>/references/feature-map.md`
- `<target_root>/projects/<project_name>/references/requirements-map.md` (when PRD docs exist)
- `<target_root>/projects/<project_name>/.context-sync/state.json`
