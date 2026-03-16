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
import os
from pathlib import Path
import json

import context_layout as layout
from source_resolver import SourceResolutionError, resolve_code_source

MULTI_SOURCE_FILENAMES = ("context-sources.json", ".context-sources.json")
CORE_TECH_MODULES = ("frontend", "backend")
OPTIONAL_TECH_MODULES = ("qa", "mobile", "data", "ops")
SOURCE_ALLOWED_MODULES = set(CORE_TECH_MODULES + OPTIONAL_TECH_MODULES)
PROJECT_ALLOWED_MODULES = set(CORE_TECH_MODULES + OPTIONAL_TECH_MODULES + ("reviewer",))
MODULE_ALIAS_MAP = {
    "frontend": "frontend",
    "front-end": "frontend",
    "front_end": "frontend",
    "fe": "frontend",
    "web": "frontend",
    "client": "frontend",
    "ui": "frontend",
    "backend": "backend",
    "back-end": "backend",
    "back_end": "backend",
    "be": "backend",
    "server": "backend",
    "api": "backend",
    "service": "backend",
    "services": "backend",
    "qa": "qa",
    "test": "qa",
    "tests": "qa",
    "e2e": "qa",
    "mobile": "mobile",
    "ios": "mobile",
    "android": "mobile",
    "data": "data",
    "analytics": "data",
    "ml": "data",
    "model": "data",
    "models": "data",
    "ops": "ops",
    "infra": "ops",
    "devops": "ops",
    "deploy": "ops",
    "reviewer": "reviewer",
    "review": "reviewer",
}
INFER_SCAN_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".turbo",
    ".next",
    ".nuxt",
    ".cache",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "vendor",
    "target",
}
INFER_SCAN_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".cs",
    ".swift",
    ".rb",
    ".php",
    ".dart",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".sql",
}
INFER_SCAN_FILENAMES = {"Dockerfile", "Makefile", "justfile"}
INFER_SCAN_MAX_FILES = 160
INFER_SCAN_MAX_BYTES = 256 * 1024
MODULE_CODE_SIGNAL_PATTERNS = {
    "frontend": (
        "react",
        "next",
        "nuxt",
        "vue",
        "svelte",
        "vite",
        "webpack",
        "browserrouter",
        "usestate(",
        "useeffect(",
        "<template",
    ),
    "backend": (
        "express(",
        "fastapi",
        "flask(",
        "django",
        "nestjs",
        "@restcontroller",
        "springboot",
        "koa(",
        "sqlalchemy",
        "typeorm",
        "prisma",
    ),
    "qa": (
        "pytest",
        "unittest",
        "jest",
        "vitest",
        "playwright",
        "cypress",
        "describe(",
        "test(",
    ),
    "mobile": (
        "react-native",
        "expo",
        "swiftui",
        "uikit",
        "androidx",
        "flutter",
        "dart:ui",
    ),
    "data": (
        "pandas",
        "numpy",
        "scikit",
        "tensorflow",
        "pytorch",
        "xgboost",
        "spark",
        "airflow",
        "dbt",
        "polars",
    ),
    "ops": (
        "terraform",
        "kubernetes",
        "helm",
        "ansible",
        "docker compose",
        "github/workflows",
        "gitlab-ci",
        "kustomize",
        "prometheus",
        "grafana",
    ),
}
MODULE_PATH_SIGNAL_PATTERNS = {
    "frontend": ("/frontend/", "/web/", "/client/", "/ui/", "/components/", "/pages/"),
    "backend": ("/backend/", "/server/", "/api/", "/services/", "/controllers/", "/routes/"),
    "qa": ("/test/", "/tests/", "__tests__", "/e2e/", "playwright", "cypress", ".spec."),
    "mobile": ("/mobile/", "/ios/", "/android/"),
    "data": ("/data/", "/analytics/", "/ml/", "/models/", "/pipelines/", "/etl/"),
    "ops": ("/ops/", "/infra/", "/deploy/", "/helm/", "/k8s/", "/.github/workflows/"),
}


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def write_if_missing(path: Path, content: str):
    if path.exists():
        return False
    ensure_parent(path)
    path.write_text(content, encoding="utf-8")
    return True


def canonical_module_name(value: str) -> str:
    token = str(value or "").strip().lower().replace("_", "-").replace(" ", "-")
    while "--" in token:
        token = token.replace("--", "-")
    if not token:
        return ""
    return MODULE_ALIAS_MAP.get(token, token)


def normalize_source_modules(raw_modules: list[str], source_name: str) -> list[str]:
    modules: set[str] = set()
    invalid: list[str] = []
    for raw_module in raw_modules:
        normalized = canonical_module_name(raw_module)
        if not normalized:
            continue
        if normalized in SOURCE_ALLOWED_MODULES:
            modules.add(normalized)
        else:
            invalid.append(str(raw_module))
    if invalid:
        allowed = ", ".join(f"'{name}'" for name in sorted(SOURCE_ALLOWED_MODULES))
        raise ValueError(
            f"Source '{source_name}' modules contain non-technical values: {', '.join(invalid)}. "
            f"First-layer modules must be technical buckets ({allowed}); business slices belong under "
            "modules/<frontend|backend>/<feature>.md."
        )
    if not modules:
        raise ValueError(f"Source '{source_name}' modules must include at least one technical module.")
    return sorted(modules)


def ensure_project_modules(modules: set[str] | list[str]) -> list[str]:
    normalized: set[str] = set()
    for raw_module in modules:
        module = canonical_module_name(raw_module)
        if module in PROJECT_ALLOWED_MODULES:
            normalized.add(module)
    if not normalized:
        normalized.update(CORE_TECH_MODULES)
    normalized.add("reviewer")
    return sorted(normalized)


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
                    try:
                        modules = normalize_source_modules(modules, name)
                    except ValueError as exc:
                        raise SystemExit(str(exc))
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
- First layer uses technical boundaries. Always keep `{modules_dir}/frontend/` and `{modules_dir}/backend/`.
- Optional technical buckets include `{modules_dir}/qa/`, `{modules_dir}/mobile/`, `{modules_dir}/data/`, `{modules_dir}/ops/`, and `{modules_dir}/reviewer/`.
- Business slices belong to second-layer files such as `{modules_dir}/frontend/new-sign.md`.
"""


def infer_detected_modules(code_dir: Path) -> list[str]:
    candidates = set()
    candidates.update(infer_modules_from_code_signals(code_dir))
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

    return sorted(candidates)


def iter_infer_scan_files(code_dir: Path):
    scanned = 0
    for root, dirnames, filenames in os.walk(code_dir):
        dirnames[:] = [name for name in sorted(dirnames) if name not in INFER_SCAN_IGNORE_DIRS]
        for filename in sorted(filenames):
            file_path = Path(root) / filename
            suffix = file_path.suffix.lower()
            if suffix not in INFER_SCAN_SUFFIXES and filename not in INFER_SCAN_FILENAMES:
                continue
            try:
                if file_path.stat().st_size > INFER_SCAN_MAX_BYTES:
                    continue
            except OSError:
                continue
            yield file_path
            scanned += 1
            if scanned >= INFER_SCAN_MAX_FILES:
                return


def infer_modules_from_code_signals(code_dir: Path) -> set[str]:
    scores = {module: 0 for module in OPTIONAL_TECH_MODULES + CORE_TECH_MODULES}
    path_hits = {module: 0 for module in OPTIONAL_TECH_MODULES + CORE_TECH_MODULES}
    for file_path in iter_infer_scan_files(code_dir):
        try:
            relative = "/" + file_path.relative_to(code_dir).as_posix().lower()
        except ValueError:
            continue

        for module, path_patterns in MODULE_PATH_SIGNAL_PATTERNS.items():
            if any(pattern in relative for pattern in path_patterns):
                scores[module] += 1
                path_hits[module] += 1

        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        if not text:
            continue
        text_sample = text[:12000]
        for module, content_patterns in MODULE_CODE_SIGNAL_PATTERNS.items():
            if any(pattern in text_sample for pattern in content_patterns):
                scores[module] += 1

    detected = set()
    for module, score in scores.items():
        if score < 2:
            continue
        if module in OPTIONAL_TECH_MODULES and path_hits[module] == 0:
            continue
        detected.add(module)
    return detected


def infer_modules(code_dir: Path) -> list[str]:
    detected = infer_detected_modules(code_dir)
    return ensure_project_modules(detected)


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
    write_if_missing(
        layout.entrypoints_path(project_root),
        "# Entrypoints\n\n- Run sync to populate generated entrypoints and runtime/build indices.\n- Add durable manual notes outside AUTO blocks when needed.\n",
    )
    write_if_missing(
        layout.feature_map_path(project_root),
        "# Feature Map\n\n- Run sync to populate generated feature-to-module mappings.\n- Add durable manual notes outside AUTO blocks when business boundaries need clarification.\n",
    )
    write_if_missing(
        layout.requirements_map_path(project_root),
        (
            "# Requirements Map\n\n"
            "- Add PRD docs under `references/prd.md` or `references/prd/*.md`.\n"
            "- Run sync to refresh the generated requirement-to-code trace matrix.\n"
        ),
    )
    write_if_missing(
        layout.domain_model_path(project_root),
        (
            "# Domain Model\n\n"
            "- Run sync to refresh the generated domain entities/states/rules snapshot.\n"
            "- Add durable business notes outside AUTO blocks when needed.\n"
        ),
    )
    write_if_missing(
        layout.references_dir(project_root) / "prd.md",
        (
            "# PRD\n\n"
            "## Requirements\n"
            "- REQ-001: Describe one requirement with acceptance criteria.\n"
        ),
    )

    multi_sources = load_multi_sources(code_dir)
    if multi_sources:
        modules = set()
        for source in multi_sources:
            # Always infer first-layer modules from source code structure.
            modules.update(infer_detected_modules(source["path"]))
        modules = ensure_project_modules(modules)
    else:
        modules = infer_modules(code_dir)
    for module in modules:
        write_if_missing(layout.module_overview_path(project_root, module), f"# {module}\n")
        write_if_missing(
            layout.module_detail_path(project_root, module),
            (
                f"# {module} Module\n\n"
                "- Sync populates a generated code summary below.\n"
                "- Add durable manual notes outside the AUTO block when project-specific corrections or decisions are needed.\n"
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
