#!/usr/bin/env python3
"""Initialize a team-style project context directory.

Usage:
  python scripts/init_context_project.py \
    --project my-project \
    --code-dir /absolute/path/to/my-project \
    # or
    --git-url https://github.com/example/my-project.git \
    --target-root /absolute/path/to/team
"""

import argparse
from datetime import datetime
from pathlib import Path
import json

import context_layout as layout
from source_resolver import SourceResolutionError, resolve_code_source

MULTI_SOURCE_FILENAMES = ("context-sources.json", ".context-sources.json")


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def write_if_missing(path: Path, content: str):
    if path.exists():
        return False
    ensure_parent(path)
    path.write_text(content, encoding="utf-8")
    return True


def load_multi_sources(code_dir: Path) -> list[dict] | None:
    for filename in MULTI_SOURCE_FILENAMES:
        candidate = code_dir / filename
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            sources = payload.get("sources")
            if not isinstance(sources, list) or not sources:
                raise SystemExit(f"Multi-source config at {candidate} must include a non-empty 'sources' list.")
            normalized = []
            for item in sources:
                name = str(item.get("name", "")).strip()
                path_raw = str(item.get("path", "")).strip()
                if not name or not path_raw:
                    raise SystemExit("Each source entry must include 'name' and 'path'.")
                source_path = Path(path_raw).expanduser().resolve()
                if not source_path.exists():
                    raise SystemExit(f"Source path does not exist for '{name}': {source_path}")
                modules = item.get("modules")
                if modules is not None:
                    if not isinstance(modules, list) or not modules:
                        raise SystemExit(f"Source '{name}' modules must be a non-empty list when provided.")
                    modules = [str(module).strip() for module in modules if str(module).strip()]
                normalized.append({"name": name, "path": source_path, "modules": modules})
            return normalized
    return None


def append_project_index(projects_index: Path, project_name: str):
    ensure_parent(projects_index)
    if not projects_index.exists():
        projects_index.write_text(
            "# Projects\n\n- All project contexts live under this folder.\n\n## Index\n",
            encoding="utf-8",
        )
    text = projects_index.read_text(encoding="utf-8")
    entry = layout.project_index_entry(project_name)
    if entry in text:
        return False
    new_text = text.rstrip() + "\n" + entry + "\n"
    projects_index.write_text(new_text, encoding="utf-8")
    return True


TEMPLATE_README = """# {project}

- Code directory: {code_dir}
- Source type: {source_type}
{source_note}- Managed source checkout: {managed_source}
- Context root: {project_root}

## Scope
- Describe what this project is about.
- Record any constraints or boundaries.
"""

TEMPLATE_GOALS = """# Goals

- [ ] Define current goals and priorities.
"""

TEMPLATE_SKILL = """# Project Skill Notes

- If this project needs a dedicated skill, document triggers and workflows here.
"""

TEMPLATE_STATUS = """# Project Status

- Status: not started
- Last updated: {date}
"""

TEMPLATE_DECISIONS = """# Decisions

- {date}: Initialize project context.
"""

TEMPLATE_AGENTS = """# Agents

- Agent routing notes for this project live here.
- Run `scripts/sync_context_project.py` to populate managed AUTO blocks for the active agents.
"""

TEMPLATE_MODULES_README = """# Modules

- Place analysis outputs here.
- Suggested structure depends on tech stack.
- Common buckets: {modules_dir}/backend/, {modules_dir}/frontend/, {modules_dir}/qa/, {modules_dir}/reviewer/
- Each technical module folder can contain function-level docs such as `{modules_dir}/frontend/new-sign.md`.
"""


def infer_modules(code_dir: Path):
    candidates = set()
    lower_names = {p.name.lower() for p in code_dir.iterdir() if p.is_dir()}

    # Heuristics by common folder names
    if {"frontend", "web", "client", "app", "ui"} & lower_names:
        candidates.add("frontend")
    if {"backend", "server", "api", "services"} & lower_names:
        candidates.add("backend")
    if {"test", "tests", "qa"} & lower_names:
        candidates.add("qa")
    if {"mobile", "ios", "android"} & lower_names:
        candidates.add("mobile")
    if {"data", "analytics", "ml", "model"} & lower_names:
        candidates.add("data")
    if {"ops", "infra", "devops", "deploy", "helm", "k8s"} & lower_names:
        candidates.add("ops")

    # Heuristics by key files
    files = {p.name for p in code_dir.iterdir() if p.is_file()}
    if "package.json" in files:
        candidates.add("frontend")
    if "pom.xml" in files or "build.gradle" in files or "build.gradle.kts" in files:
        candidates.add("backend")
    if "go.mod" in files or "requirements.txt" in files or "pyproject.toml" in files:
        candidates.add("backend")
    if "Dockerfile" in files or "docker-compose.yml" in files:
        candidates.add("ops")

    if not candidates:
        candidates.update({"backend", "frontend", "qa", "reviewer"})

    # Always include reviewer bucket
    candidates.add("reviewer")
    return sorted(candidates)


def main():
    parser = argparse.ArgumentParser(description="Initialize a team-style project context directory.")
    parser.add_argument("--project", required=True, help="Project name (folder name).")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--code-dir", help="Absolute path to the local code directory.")
    source_group.add_argument("--git-url", help="Git repository URL or local Git path to clone for analysis.")
    parser.add_argument(
        "--target-root",
        default=str(layout.DEFAULT_TARGET_ROOT),
        help=f"Target root for team context (default: {layout.DEFAULT_TARGET_ROOT_DISPLAY}).",
    )
    args = parser.parse_args()

    target_root = Path(args.target_root).expanduser().resolve()
    try:
        source = resolve_code_source(
            args.project,
            target_root,
            code_dir=args.code_dir,
            git_url=args.git_url,
        )
    except SourceResolutionError as exc:
        raise SystemExit(str(exc))

    code_dir = source.code_dir
    project_root = layout.project_root(target_root, args.project)
    date = datetime.now().strftime("%Y-%m-%d")

    created = []
    created.append(write_if_missing(layout.team_readme_path(target_root), "# Team Directory Guide\n\n- Keep navigation here.\n"))
    append_project_index(layout.projects_index_path(target_root), args.project)

    source_note = f"- Source git: {source.git_url}\n" if source.git_url else ""
    managed_source = "yes" if source.managed else "no"
    write_if_missing(
        layout.project_readme_path(project_root),
        TEMPLATE_README.format(
            project=args.project,
            code_dir=code_dir,
            project_root=project_root,
            source_type=source.source_type,
            source_note=source_note,
            managed_source=managed_source,
        ),
    )
    write_if_missing(layout.goals_path(project_root), TEMPLATE_GOALS)
    write_if_missing(layout.skill_path(project_root), TEMPLATE_SKILL)
    write_if_missing(layout.project_status_path(project_root), TEMPLATE_STATUS.format(date=date))
    write_if_missing(layout.decisions_path(project_root), TEMPLATE_DECISIONS.format(date=date))
    write_if_missing(layout.agents_index_path(project_root), TEMPLATE_AGENTS)
    write_if_missing(layout.modules_index_path(project_root), TEMPLATE_MODULES_README.format(modules_dir=layout.MODULES_DIRNAME))
    write_if_missing(layout.entrypoints_path(project_root), "# Entrypoints\n\n- TODO: record key entrypoints and indices.\n")
    write_if_missing(layout.feature_map_path(project_root), "# Feature Map\n\n- TODO: map shared business features across technical modules.\n")

    multi_sources = load_multi_sources(code_dir)
    if multi_sources:
        modules = set()
        for source in multi_sources:
            source_modules = source.get("modules") or infer_modules(source["path"])
            modules.update(source_modules)
        modules.add("reviewer")
        modules = sorted(modules)
    else:
        modules = infer_modules(code_dir)
    for module in modules:
        write_if_missing(layout.module_overview_path(project_root, module), f"# {module}\n")
        write_if_missing(
            layout.module_detail_path(project_root, module),
            (
                f"# {module} Module\n\n"
                "## Scope\n- TODO: define boundaries and ownership.\n\n"
                "## Functional Subdomains\n- TODO: list feature-level docs such as `new-sign.md`, `renewal.md`, or `amendment.md` when they exist.\n\n"
                "## Key Responsibilities\n- TODO: list core responsibilities.\n\n"
                "## Important Notes\n- TODO: add critical constraints, gotchas, or decisions.\n\n"
                "## Interfaces & Dependencies\n- TODO: list internal/external dependencies and key interfaces.\n"
            ),
        )

    # Create agent folders based on inferred modules + reviewer
    agent_names = sorted(set(modules + ["reviewer"]))
    for agent in agent_names:
        write_if_missing(
            layout.agent_readme_path(project_root, agent),
            (
                f"# {agent.title()} — {agent.title()} Agent\n\n"
                "Keep durable manual notes outside the managed AUTO block.\n"
                "Run `scripts/sync_context_project.py` to generate the initial agent profile.\n"
            ),
        )
        write_if_missing(
            layout.agent_tools_path(project_root, agent),
            "# Tools\n\n- Managed AUTO content is populated by sync.\n- Add durable manual tool notes outside the AUTO block.\n",
        )
        write_if_missing(
            layout.agent_memory_path(project_root, agent),
            "# Memory\n\n- Managed AUTO content is populated by sync.\n- Add durable manual memory notes outside the AUTO block.\n",
        )
        write_if_missing(layout.agent_decisions_path(project_root, agent), "")
        write_if_missing(layout.agent_fails_path(project_root, agent), "")

    print(f"Initialized context for {args.project} at {project_root}")


if __name__ == "__main__":
    main()
