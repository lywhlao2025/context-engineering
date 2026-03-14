#!/usr/bin/env python3
"""Synchronize a team-style project context directory.

Modes:
- Git repo with valid sync state: incremental sync
- Git repo without valid sync state: full sync
- Non-Git repo: full sync

The sync process only rewrites managed AUTO blocks. Manual content outside those
blocks is preserved. If a previously generated AUTO block was edited manually,
the sync aborts unless --force-generated is passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

import context_layout as layout
from init_context_project import infer_modules
from source_resolver import ResolvedSource, SourceResolutionError, normalize_source_locator, resolve_code_source


STATE_VERSION = 3
AUTO_BLOCK_PATTERN = r"<!-- BEGIN AUTO:{name} -->\n?(.*?)\n?<!-- END AUTO:{name} -->"
AUTO_BEGIN = "<!-- BEGIN AUTO:{name} -->"
AUTO_END = "<!-- END AUTO:{name} -->"
IGNORE_DIRS = {
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
IGNORE_FILE_NAMES = {
    ".DS_Store",
}
IGNORE_FILE_SUFFIXES = {
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
}
ALLOWED_DEFAULT_BRANCHES = ("main", "master")
GLOBAL_CONFIG_FILES = {
    "package.json",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "pnpm-workspace.yaml",
    "turbo.json",
    "nx.json",
    "lerna.json",
    "pyproject.toml",
    "poetry.lock",
    "requirements.txt",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Cargo.toml",
    "Cargo.lock",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "Makefile",
    "justfile",
}
GLOBAL_DOC_FILES = {
    "README",
    "README.md",
    "README.rst",
    "CHANGELOG",
    "CHANGELOG.md",
    "architecture.md",
    "tech.md",
}
GLOBAL_DIR_NAMES = {"docs", ".github", "scripts", "config", "configs"}
MODULE_KEYWORDS = {
    "frontend": {"frontend", "web", "client", "ui", "browser", "pages"},
    "backend": {"backend", "server", "api", "service", "services", "worker"},
    "qa": {"test", "tests", "qa", "e2e", "cypress", "playwright"},
    "mobile": {"mobile", "ios", "android"},
    "data": {"data", "analytics", "ml", "model", "models"},
    "ops": {"ops", "infra", "devops", "deploy", "helm", "k8s", "terraform"},
}
DEFAULT_MODULE_PATHS = {
    "frontend": ["frontend", "web", "client", "ui", "app", "src", "public"],
    "backend": ["backend", "server", "api", "services", "src", "app", "cmd"],
    "qa": ["test", "tests", "qa", "e2e", "cypress", "playwright"],
    "mobile": ["mobile", "ios", "android"],
    "data": ["data", "analytics", "ml", "model", "models"],
    "ops": ["ops", "infra", "devops", "deploy", "helm", "k8s", "terraform"],
}
ENTRYPOINT_FILE_NAMES = {
    "main.py",
    "main.ts",
    "main.tsx",
    "main.js",
    "main.jsx",
    "index.ts",
    "index.tsx",
    "index.js",
    "index.jsx",
    "app.py",
    "app.ts",
    "app.tsx",
    "app.js",
    "app.jsx",
    "server.py",
    "server.ts",
    "server.js",
    "manage.py",
    "manifest.json",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}
ENTRYPOINT_SENSITIVE_FILE_NAMES = ENTRYPOINT_FILE_NAMES | {
    "vite.config.ts",
    "vite.config.js",
    "vite.config.mjs",
    "vite.config.cjs",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "nuxt.config.ts",
    "nuxt.config.js",
    "astro.config.mjs",
    "astro.config.ts",
    "svelte.config.js",
    "angular.json",
}
DATA_KEYWORDS = ("prisma", "schema", "db", "database", "migrations", "migration", "sql")
I18N_KEYWORDS = ("i18n", "locale", "locales", "translation", "translations")
MAX_DISCOVERED_FILES = 30
MAX_LISTED_ITEMS = 12
REVIEW_OUTCOME_CHOICES = ("pending", "pass", "pass_with_findings", "fail")
LINE_HINTS_BY_FILENAME = {
    "package.json": ('"scripts"', '"main"', '"exports"', '"bin"'),
    "pyproject.toml": ("[project.scripts]", "[tool.poetry.scripts]", "[project]"),
    "Cargo.toml": ("[package]", "[dependencies]"),
}


@dataclass
class SyncMode:
    name: str
    changed_modules: list[str]
    update_global: bool
    reason: str


@dataclass
class ReviewPlan:
    scope: str
    reason: str
    target_modules: list[str]
    target_paths: list[str]


@dataclass
class ReviewRecord:
    outcome: str
    notes: str | None
    recorded_at: str | None
    reviewed_head: str | None


class SyncError(RuntimeError):
    """Raised when the sync cannot continue safely."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_command(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise SyncError(result.stderr.strip() or "Command failed: " + " ".join(args))
    return result.stdout.strip()


def try_command(args: list[str], cwd: Path | None = None) -> str | None:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def command_succeeds(args: list[str], cwd: Path | None = None) -> bool:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def is_git_repo(code_dir: Path) -> Path | None:
    output = try_command(["git", "-C", str(code_dir), "rev-parse", "--show-toplevel"])
    return Path(output).resolve() if output else None


def ensure_clean_default_branch(repo_root: Path) -> tuple[str, str]:
    current_head = run_command(["git", "-C", str(repo_root), "rev-parse", "HEAD"])
    branch = run_command(["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"])
    if branch not in ALLOWED_DEFAULT_BRANCHES:
        allowed = " or ".join(f"`{name}`" for name in ALLOWED_DEFAULT_BRANCHES)
        raise SyncError(
            f"Default-branch sync requires the checked-out branch to be {allowed}. "
            f"Current branch: `{branch}`."
        )

    status_output = run_command(["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"])
    if status_output:
        raise SyncError(
            "Default-branch sync requires a clean worktree on the checked-out default branch. "
            "Commit, stash, or remove local changes before syncing."
        )

    return current_head, branch


def run_init_scaffold(project: str, code_dir: Path, target_root: Path) -> None:
    script_path = Path(__file__).with_name("init_context_project.py")
    run_command(
        [
            sys.executable,
            str(script_path),
            "--project",
            project,
            "--code-dir",
            str(code_dir),
            "--target-root",
            str(target_root),
        ]
    )


def state_dir(project_root: Path) -> Path:
    return layout.sync_state_dir(project_root)


def state_path(project_root: Path) -> Path:
    return layout.sync_state_path(project_root)


def load_state(project_root: Path) -> dict:
    path = state_path(project_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(f"Invalid sync state at {path}: {exc}") from exc


def save_state(project_root: Path, state: dict) -> None:
    path = state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def code_entries(code_dir: Path) -> list[Path]:
    entries: list[Path] = []
    for path in sorted(code_dir.iterdir(), key=lambda item: item.name.lower()):
        if path.name in IGNORE_DIRS:
            continue
        if path.name in IGNORE_FILE_NAMES:
            continue
        if path.is_file() and path.suffix.lower() in IGNORE_FILE_SUFFIXES:
            continue
        entries.append(path)
    return entries


def detect_manifests(code_dir: Path) -> list[str]:
    manifests = []
    for name in sorted(GLOBAL_CONFIG_FILES):
        if (code_dir / name).exists():
            manifests.append(name)
    return manifests


def classify_top_level_path(path: Path, modules: list[str], has_frontend_manifest: bool, has_backend_manifest: bool) -> list[str]:
    name = path.name.lower()
    if name in GLOBAL_DIR_NAMES:
        return []
    matches = [module for module, keywords in MODULE_KEYWORDS.items() if module in modules and name in keywords]
    if matches:
        return matches
    if name in {"src", "app", "lib"}:
        if has_frontend_manifest and not has_backend_manifest and "frontend" in modules:
            return ["frontend"]
        if has_backend_manifest and not has_frontend_manifest and "backend" in modules:
            return ["backend"]
    if name == "public" and "frontend" in modules:
        return ["frontend"]
    if name in {"prisma", "migrations", "migration", "db", "database"}:
        matches = []
        if "backend" in modules:
            matches.append("backend")
        if "data" in modules:
            matches.append("data")
        return matches
    return []


def discover_module_map(code_dir: Path, modules: list[str]) -> tuple[dict[str, list[str]], list[str], list[str]]:
    module_map = {module: [] for module in modules if module != "reviewer"}
    global_paths: list[str] = []
    unmatched_roots: list[str] = []
    manifests = detect_manifests(code_dir)
    has_frontend_manifest = "package.json" in manifests
    has_backend_manifest = any(
        name in manifests
        for name in {"pyproject.toml", "requirements.txt", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "Cargo.toml"}
    )

    for entry in code_entries(code_dir):
        name = entry.name
        lowered = name.lower()
        if (
            name in GLOBAL_CONFIG_FILES
            or name in GLOBAL_DOC_FILES
            or lowered.startswith("readme")
            or lowered.startswith("changelog")
            or lowered in GLOBAL_DIR_NAMES
        ):
            global_paths.append(name)
            continue
        matched_modules = classify_top_level_path(entry, modules, has_frontend_manifest, has_backend_manifest)
        if not matched_modules:
            unmatched_roots.append(name)
            continue
        for module in matched_modules:
            if module != "reviewer":
                module_map[module].append(name)

    for module, candidates in DEFAULT_MODULE_PATHS.items():
        if module not in module_map:
            continue
        if module_map[module]:
            continue
        for candidate in candidates:
            candidate_path = code_dir / candidate
            if candidate_path.exists():
                module_map[module].append(candidate)
        if not module_map[module] and module in {"frontend", "backend"} and (code_dir / "src").exists():
            if module == "frontend" and has_frontend_manifest and not has_backend_manifest:
                module_map[module].append("src")
            elif module == "backend" and has_backend_manifest and not has_frontend_manifest:
                module_map[module].append("src")

    normalized_map = {
        module: sorted(dict.fromkeys(paths))
        for module, paths in module_map.items()
    }
    global_paths = sorted(dict.fromkeys(global_paths))
    unmatched_roots = sorted(dict.fromkeys(unmatched_roots))
    return normalized_map, global_paths, unmatched_roots


def relative_to_code_root(path: str, repo_root: Path, code_dir: Path) -> str | None:
    repo_rel = PurePosixPath(path)
    code_prefix = ""
    if code_dir != repo_root:
        code_prefix = code_dir.relative_to(repo_root).as_posix().strip(".")
    if code_prefix:
        prefix = PurePosixPath(code_prefix)
        try:
            return repo_rel.relative_to(prefix).as_posix()
        except ValueError:
            return None
    return repo_rel.as_posix()


def git_changed_files(
    repo_root: Path,
    code_dir: Path,
    last_synced_head: str | None,
    has_previous_state: bool,
) -> tuple[list[str], str, str, str | None]:
    current_head, branch = ensure_clean_default_branch(repo_root)
    raw_paths: set[str] = set()
    base_issue: str | None = None

    if has_previous_state:
        if not last_synced_head:
            base_issue = "Previous sync state is missing `last_synced_head`."
        elif not command_succeeds(["git", "-C", str(repo_root), "cat-file", "-e", f"{last_synced_head}^{{commit}}"]):
            base_issue = "Last synced commit is no longer available in the local default-branch history."
        elif not command_succeeds(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", last_synced_head, "HEAD"]):
            base_issue = "Last synced commit is not an ancestor of the current default-branch HEAD."
        else:
            diff_output = run_command(["git", "-C", str(repo_root), "diff", "--name-only", f"{last_synced_head}..HEAD"])
            raw_paths.update(filter(None, diff_output.splitlines()))

    changed_paths = []
    for raw_path in sorted(raw_paths):
        rel_path = relative_to_code_root(raw_path, repo_root, code_dir)
        if rel_path:
            if should_ignore_relative_path(rel_path):
                continue
            changed_paths.append(rel_path)
    return changed_paths, current_head, branch, base_issue


def path_matches_root(relative_path: str, root: str) -> bool:
    rel = PurePosixPath(relative_path)
    root_path = PurePosixPath(root)
    if root == ".":
        return True
    if rel == root_path:
        return True
    try:
        rel.relative_to(root_path)
        return True
    except ValueError:
        return False


def should_ignore_relative_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if path.name in IGNORE_FILE_NAMES:
        return True
    if path.suffix.lower() in IGNORE_FILE_SUFFIXES:
        return True
    return False


def map_changed_paths(
    changed_paths: list[str],
    module_map: dict[str, list[str]],
    global_paths: list[str],
) -> tuple[list[str], bool, list[str]]:
    changed_modules: set[str] = set()
    update_global = False
    unmatched: list[str] = []

    for relative_path in changed_paths:
        matched = False
        basename = PurePosixPath(relative_path).name
        if basename in GLOBAL_CONFIG_FILES or basename in GLOBAL_DOC_FILES:
            update_global = True
            matched = True
        for root in global_paths:
            if path_matches_root(relative_path, root):
                update_global = True
                matched = True
        for module, roots in module_map.items():
            for root in roots:
                if path_matches_root(relative_path, root):
                    changed_modules.add(module)
                    matched = True
                    break
        if not matched:
            unmatched.append(relative_path)

    return sorted(changed_modules), update_global, unmatched


def resolve_module_targets(mode: SyncMode, modules: list[str]) -> list[str]:
    module_targets = set(mode.changed_modules)
    if mode.name == "full":
        module_targets = {module for module in modules}
    if mode.name == "incremental" and module_targets:
        module_targets.add("reviewer")
    return sorted(module_targets)


def resolve_agent_targets(mode: SyncMode, modules: list[str]) -> list[str]:
    return resolve_module_targets(mode, modules)


def is_entrypoint_sensitive_path(relative_path: str) -> bool:
    return PurePosixPath(relative_path).name in ENTRYPOINT_SENSITIVE_FILE_NAMES


def detect_entrypoint_ambiguity(code_dir: Path, changed_paths: list[str]) -> str | None:
    sensitive_changes = [path for path in changed_paths if is_entrypoint_sensitive_path(path)]
    if not sensitive_changes:
        return None
    candidates = entrypoint_candidates(code_dir)
    if len(candidates) <= 1:
        return None
    sensitive_sample = ", ".join(f"`{path}`" for path in limited_paths(sensitive_changes))
    candidate_sample = ", ".join(f"`{path}`" for path in limited_paths(candidates))
    return (
        "Entrypoint-sensitive files changed while multiple runtime/build entrypoint candidates exist. "
        f"Changed: {sensitive_sample}. Candidates: {candidate_sample}."
    )


def expected_generated_targets(
    project_root: Path,
    module_targets: list[str],
    agent_targets: list[str],
    include_global: bool,
) -> list[tuple[Path, str]]:
    targets: list[tuple[Path, str]] = []
    if include_global:
        targets.extend(
            [
                (layout.skill_path(project_root), "l1"),
                (layout.entrypoints_path(project_root), "entrypoints"),
                (layout.modules_index_path(project_root), "module-index"),
                (layout.agents_index_path(project_root), "agent-index"),
            ]
        )
    for agent in agent_targets:
        targets.extend(
            [
                (layout.agent_readme_path(project_root, agent), "agent-readme"),
                (layout.agent_tools_path(project_root, agent), "agent-tools"),
                (layout.agent_memory_path(project_root, agent), "agent-memory"),
            ]
        )
    for module in module_targets:
        targets.extend(
            [
                (layout.module_overview_path(project_root, module), "module-overview"),
                (layout.module_detail_path(project_root, module), "module-detail"),
            ]
        )
    targets.append((layout.project_status_path(project_root), "sync-status"))
    return targets


def detect_context_scope_mismatch(
    project_root: Path,
    module_targets: list[str],
    agent_targets: list[str],
    include_global: bool,
) -> list[str]:
    missing: list[str] = []
    for file_path, block_name in expected_generated_targets(project_root, module_targets, agent_targets, include_global):
        relative_doc_path = file_path.relative_to(project_root).as_posix()
        if not file_path.exists():
            missing.append(f"{relative_doc_path} [{block_name}]")
            continue
        if extract_auto_block(read_text(file_path), block_name) is None:
            missing.append(f"{relative_doc_path} [{block_name}]")
    return missing


def auto_block_key(relative_path: str, block_name: str) -> str:
    return f"{relative_path}::{block_name}"


def auto_block_regex(block_name: str) -> re.Pattern[str]:
    return re.compile(AUTO_BLOCK_PATTERN.format(name=re.escape(block_name)), re.DOTALL)


def extract_auto_block(text: str, block_name: str) -> str | None:
    match = auto_block_regex(block_name).search(text)
    if not match:
        return None
    return match.group(1).strip("\n")


def upsert_auto_block(text: str, block_name: str, content: str) -> str:
    begin = AUTO_BEGIN.format(name=block_name)
    end = AUTO_END.format(name=block_name)
    block = f"{begin}\n{content.rstrip()}\n{end}"
    pattern = auto_block_regex(block_name)
    if pattern.search(text):
        updated = pattern.sub(block, text, count=1)
    else:
        trimmed = text.rstrip()
        if trimmed:
            updated = trimmed + "\n\n" + block + "\n"
        else:
            updated = block + "\n"
    return updated


def detect_auto_conflicts(project_root: Path, updates: list[tuple[Path, str, str]], stored_hashes: dict[str, str], force_generated: bool) -> list[str]:
    if force_generated:
        return []
    conflicts: list[str] = []
    for file_path, block_name, _ in updates:
        relative_doc_path = file_path.relative_to(project_root).as_posix()
        known_hash = stored_hashes.get(auto_block_key(relative_doc_path, block_name))
        if not known_hash or not file_path.exists():
            continue
        current_block = extract_auto_block(read_text(file_path), block_name)
        if current_block is None:
            continue
        if sha256_text(current_block) != known_hash:
            conflicts.append(f"{relative_doc_path} [{block_name}]")
    return conflicts


def list_top_level_entries(code_dir: Path) -> list[str]:
    return [path.name for path in code_entries(code_dir)]


def walk_files(code_dir: Path):
    for root, dirnames, filenames in os.walk(code_dir):
        dirnames[:] = [name for name in sorted(dirnames) if name not in IGNORE_DIRS]
        for filename in sorted(filenames):
            if filename in IGNORE_FILE_NAMES:
                continue
            if Path(filename).suffix.lower() in IGNORE_FILE_SUFFIXES:
                continue
            yield Path(root) / filename


def limited_paths(paths: list[str], limit: int = MAX_LISTED_ITEMS) -> list[str]:
    if len(paths) <= limit:
        return paths
    remaining = len(paths) - limit
    return paths[:limit] + [f"... and {remaining} more"]


def first_meaningful_line(file_path: Path) -> int | None:
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for hint in LINE_HINTS_BY_FILENAME.get(file_path.name, ()):
            for line_number, line in enumerate(lines, start=1):
                if hint in line:
                    return line_number
        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in {"{", "}", "[", "]", "(", ")"}:
                continue
            if stripped.startswith(("#", "//", "/*", "*", "--", ";", "<!--")):
                continue
            return line_number
    except OSError:
        return None
    return 1 if file_path.exists() else None


def first_evidence_file(path: Path) -> Path | None:
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    for candidate in walk_files(path):
        return candidate
    return None


def format_line_ref(relative_path: str, line_number: int | None) -> str:
    if line_number:
        return f"`{relative_path}:{line_number}`"
    return f"`{relative_path}`"


def path_line_ref(code_dir: Path, relative_path: str) -> str:
    candidate = code_dir / relative_path
    evidence_file = first_evidence_file(candidate)
    if not evidence_file:
        return format_line_ref(relative_path, None)
    relative = evidence_file.relative_to(code_dir).as_posix()
    return format_line_ref(relative, first_meaningful_line(evidence_file))


def line_refs_for_paths(code_dir: Path, paths: list[str], limit: int = MAX_LISTED_ITEMS) -> list[str]:
    refs = [path_line_ref(code_dir, path) for path in paths]
    return limited_paths(list(dict.fromkeys(refs)), limit)


def format_list(items: list[str], empty_message: str, *, quote: bool = True) -> list[str]:
    if not items:
        return [f"- {empty_message}"]
    if not quote:
        return [f"- {item}" for item in items]
    return [f"- `{item}`" for item in items]


def package_json_scripts(code_dir: Path) -> list[str]:
    package_path = code_dir / "package.json"
    if not package_path.exists():
        return []
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    scripts = data.get("scripts") or {}
    ordered_names = ["dev", "start", "build", "test", "lint"]
    commands = []
    for name in ordered_names:
        if name in scripts:
            commands.append(f"npm run {name}")
    for name in sorted(scripts):
        if name not in ordered_names and len(commands) < MAX_LISTED_ITEMS:
            commands.append(f"npm run {name}")
    return commands


def make_targets(code_dir: Path) -> list[str]:
    makefile = code_dir / "Makefile"
    if not makefile.exists():
        return []
    targets = []
    for line in makefile.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("\t") or ":" not in line:
            continue
        target = line.split(":", 1)[0].strip()
        if not target or " " in target or target.startswith("."):
            continue
        targets.append(f"make {target}")
        if len(targets) >= MAX_LISTED_ITEMS:
            break
    return targets


def python_scripts(code_dir: Path) -> list[str]:
    commands = []
    pyproject = code_dir / "pyproject.toml"
    if pyproject.exists() and tomllib:
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        project_scripts = ((data.get("project") or {}).get("scripts") or {})
        for name in sorted(project_scripts):
            commands.append(name)
    if (code_dir / "requirements.txt").exists() or pyproject.exists():
        commands.extend(["pytest", "python -m <module>"])
    return list(dict.fromkeys(commands))[:MAX_LISTED_ITEMS]


def build_run_commands(code_dir: Path) -> list[str]:
    commands = []
    commands.extend(package_json_scripts(code_dir))
    commands.extend(make_targets(code_dir))
    commands.extend(python_scripts(code_dir))
    if (code_dir / "go.mod").exists():
        commands.extend(["go test ./...", "go run ./..."])
    if (code_dir / "Cargo.toml").exists():
        commands.extend(["cargo test", "cargo run"])
    return list(dict.fromkeys(commands))[:MAX_LISTED_ITEMS]


def find_files(code_dir: Path, predicate, limit: int = MAX_DISCOVERED_FILES) -> list[str]:
    matches = []
    for file_path in walk_files(code_dir):
        relative = file_path.relative_to(code_dir).as_posix()
        if predicate(file_path, relative):
            matches.append(relative)
            if len(matches) >= limit:
                break
    return matches


def entrypoint_candidates(code_dir: Path) -> list[str]:
    return find_files(
        code_dir,
        lambda file_path, relative: file_path.name in ENTRYPOINT_FILE_NAMES or relative in GLOBAL_CONFIG_FILES,
    )


def data_paths(code_dir: Path) -> list[str]:
    return find_files(
        code_dir,
        lambda file_path, relative: any(keyword in relative.lower() for keyword in DATA_KEYWORDS),
    )


def i18n_paths(code_dir: Path) -> list[str]:
    return find_files(
        code_dir,
        lambda file_path, relative: any(keyword in relative.lower() for keyword in I18N_KEYWORDS),
    )


def test_paths(code_dir: Path) -> list[str]:
    return find_files(
        code_dir,
        lambda file_path, relative: any(token in relative.lower() for token in ("test", "spec", "e2e", "playwright", "cypress")),
    )


def docs_paths(code_dir: Path) -> list[str]:
    matches = []
    for path in code_entries(code_dir):
        lowered = path.name.lower()
        if lowered.startswith("readme") or lowered.startswith("changelog") or path.name in {"docs", "architecture.md", "tech.md"}:
            matches.append(path.name)
    return matches


def module_entrypoints(code_dir: Path, module_paths: list[str]) -> list[str]:
    if not module_paths:
        return []
    matches = []
    for file_path in walk_files(code_dir):
        relative = file_path.relative_to(code_dir).as_posix()
        if not any(path_matches_root(relative, root) for root in module_paths):
            continue
        if file_path.name in ENTRYPOINT_FILE_NAMES:
            matches.append(relative)
        if len(matches) >= MAX_LISTED_ITEMS:
            break
    return matches


def module_key_files(code_dir: Path, module_paths: list[str]) -> list[str]:
    if not module_paths:
        return []
    matches = []
    for root in module_paths:
        candidate = code_dir / root
        if candidate.is_file():
            matches.append(root)
            continue
        if not candidate.exists():
            continue
        for file_path in walk_files(candidate):
            relative = file_path.relative_to(code_dir).as_posix()
            matches.append(relative)
            if len(matches) >= MAX_LISTED_ITEMS:
                return sorted(dict.fromkeys(matches))
    return sorted(dict.fromkeys(matches))


def module_test_paths(code_dir: Path, module_paths: list[str]) -> list[str]:
    all_tests = test_paths(code_dir)
    return [path for path in all_tests if any(path_matches_root(path, root) for root in module_paths)]


def module_responsibility(module: str) -> str:
    responsibilities = {
        "frontend": "Owns user-facing UI, client-side flows, and presentation assets.",
        "backend": "Owns server-side APIs, business logic, and persistence workflows.",
        "qa": "Owns test strategy, verification paths, and release confidence checks.",
        "mobile": "Owns mobile clients and device-specific runtime behavior.",
        "data": "Owns analytics, models, pipelines, and data-oriented assets.",
        "ops": "Owns deployment, environment, and runtime operations.",
        "reviewer": "Owns cross-cutting code review guidance, risks, and quality gates.",
    }
    return responsibilities.get(module, "Owns the module-specific responsibilities discovered in the codebase.")


def module_tasks(module: str) -> list[str]:
    tasks = {
        "frontend": ["Review UI entrypoints and routing changes.", "Track component and state management changes."],
        "backend": ["Review API entrypoints and domain logic changes.", "Track data access and migration-related changes."],
        "qa": ["Review test coverage, critical scenarios, and failing paths.", "Track test framework and fixture updates."],
        "mobile": ["Review mobile entrypoints and platform-specific integrations.", "Track device runtime and packaging changes."],
        "data": ["Review schemas, pipelines, and model boundaries.", "Track data ingestion and reporting updates."],
        "ops": ["Review deployment entrypoints and environment configuration.", "Track build, release, and infra changes."],
        "reviewer": ["Review cross-module regressions and architectural drift.", "Track unresolved risks and missing tests."],
    }
    return tasks.get(module, ["Review code changes inside this module.", "Track module-specific risks and dependencies."])


def module_line_refs(code_dir: Path, module_paths: list[str]) -> list[str]:
    key_files = module_key_files(code_dir, module_paths)
    if key_files:
        return line_refs_for_paths(code_dir, key_files)
    return line_refs_for_paths(code_dir, module_paths)


def build_manifest_refs(code_dir: Path) -> list[str]:
    manifests = [
        name
        for name in (
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "Makefile",
            "go.mod",
            "Cargo.toml",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        )
        if (code_dir / name).exists()
    ]
    return line_refs_for_paths(code_dir, manifests)


def agent_scope_paths(agent: str, module_map: dict[str, list[str]]) -> list[str]:
    if agent == "reviewer":
        flattened = []
        for module, module_paths in sorted(module_map.items()):
            if module == "reviewer":
                continue
            flattened.extend(module_paths)
        return sorted(dict.fromkeys(flattened))
    return module_map.get(agent, [])


def agent_role(agent: str) -> str:
    if agent == "reviewer":
        return "Routes cross-module review work, checks risks, and widens scope when localized review is unsafe."
    return f"Acts as the first-stop sub-agent for `{agent}` work before deeper module detail is loaded."


def agent_principles(agent: str) -> list[str]:
    principles = [
        "Start from the agent scope before loading deeper module detail.",
        "Support important claims with file-and-line evidence from the current code snapshot.",
        "Escalate to broader review when entrypoints, boundaries, or diff-to-context mapping are ambiguous.",
    ]
    if agent == "reviewer":
        principles.append("Prefer risk surfacing and boundary checks over rewriting large amounts of text.")
    return principles


def agent_deliverables(agent: str) -> list[str]:
    if agent == "reviewer":
        return [
            "Cross-module findings with file and line references.",
            "Review outcome recommendation: pass, pass with findings, or fail.",
        ]
    return [
        f"Scoped `{agent}` summaries tied to concrete code references.",
        f"`{agent}` risks, entrypoints, dependencies, and test hooks for downstream review.",
    ]


def generate_agents_index_block(modules: list[str], module_map: dict[str, list[str]]) -> str:
    lines = [
        "## Generated Agent Index",
        "- Route through the task-matched agent before loading module details.",
    ]
    for agent in modules:
        if agent == "reviewer":
            lines.append(
                f"- `reviewer`: start at `{layout.AGENTS_DIRNAME}/reviewer/{layout.AGENT_README_FILENAME}`, "
                f"then widen into changed modules or `{layout.REFERENCES_DIRNAME}/{layout.ENTRYPOINTS_FILENAME}`."
            )
            continue
        scope_paths = module_map.get(agent, [])
        scope_text = ", ".join(f"`{path}`" for path in scope_paths) if scope_paths else "no stable path mapping inferred yet"
        lines.append(
            f"- `{agent}`: start at `{layout.AGENTS_DIRNAME}/{agent}/{layout.AGENT_README_FILENAME}`, "
            f"then load `{layout.relative_module_overview(agent)}`. Scope: {scope_text}."
        )
    return "\n".join(lines)


def generate_agent_readme_block(agent: str, code_dir: Path, module_map: dict[str, list[str]]) -> str:
    scope_paths = agent_scope_paths(agent, module_map)
    evidence_refs = limited_paths(module_line_refs(code_dir, scope_paths))
    lines = [
        "## Generated Agent Profile",
        f"- Role: {agent_role(agent)}",
        "",
        "## Principles",
        *[f"- {item}" for item in agent_principles(agent)],
        "",
        "## Responsibilities",
        *[f"- {task}" for task in module_tasks(agent)],
        "",
        "## Deliverables",
        *[f"- {item}" for item in agent_deliverables(agent)],
        "",
        "## Working Style",
        f"- Start with `{layout.AGENT_README_FILENAME}`, load `{layout.AGENT_TOOLS_FILENAME}` and `{layout.AGENT_MEMORY_FILENAME}` only when needed, then move into the module docs.",
        "- Keep the review scoped to the mapped module roots unless the diff or evidence says that is unsafe.",
        "",
        "## Scope Evidence",
        *format_list(evidence_refs, "No representative line-level evidence was discovered automatically.", quote=False),
        "",
        "## Directory Guide",
        f"- `{layout.AGENT_TOOLS_FILENAME}`: commands, entrypoints, and practical inspection starting points.",
        f"- `{layout.AGENT_MEMORY_FILENAME}`: stable scope notes, adjacent modules, and escalation triggers.",
        f"- `{layout.AGENT_DECISIONS_FILENAME}`: durable decisions for this agent.",
        f"- `{layout.AGENT_FAILS_FILENAME}`: repeated failure modes and review misses.",
    ]
    return "\n".join(lines)


def generate_agent_tools_block(agent: str, code_dir: Path, module_map: dict[str, list[str]]) -> str:
    scope_paths = agent_scope_paths(agent, module_map)
    commands = limited_paths(build_run_commands(code_dir))
    manifest_refs = limited_paths(build_manifest_refs(code_dir))
    if agent == "reviewer":
        entrypoint_refs = limited_paths(line_refs_for_paths(code_dir, entrypoint_candidates(code_dir)))
        test_refs = limited_paths(line_refs_for_paths(code_dir, test_paths(code_dir)))
    else:
        entrypoint_refs = limited_paths(line_refs_for_paths(code_dir, module_entrypoints(code_dir, scope_paths)))
        test_refs = limited_paths(line_refs_for_paths(code_dir, module_test_paths(code_dir, scope_paths)))
    lines = [
        "## Generated Tools Guide",
        "- Preferred commands:",
        *format_list(commands, "No common commands discovered automatically."),
        "- Command manifest evidence:",
        *format_list(manifest_refs, "No build or runtime manifests discovered automatically.", quote=False),
        "- Entrypoint evidence:",
        *format_list(entrypoint_refs, "No scoped entrypoint evidence discovered automatically.", quote=False),
        "- Testing evidence:",
        *format_list(test_refs, "No scoped testing evidence discovered automatically.", quote=False),
    ]
    return "\n".join(lines)


def generate_agent_memory_block(agent: str, code_dir: Path, module_map: dict[str, list[str]]) -> str:
    scope_paths = agent_scope_paths(agent, module_map)
    evidence_refs = limited_paths(module_line_refs(code_dir, scope_paths))
    adjacent_modules = [
        name
        for name, paths in sorted(module_map.items())
        if name != agent and name != "reviewer" and paths
    ]
    lines = [
        "## Generated Working Memory",
        "- Stable scope roots:",
    ]
    if scope_paths:
        lines.extend(f"- `{path}`" for path in limited_paths(scope_paths))
    else:
        lines.append("- No stable scope roots inferred automatically.")
    lines.extend(
        [
            "- Adjacent modules:",
            *format_list(adjacent_modules[:4], "No adjacent modules inferred yet."),
            "- Re-entry evidence:",
            *format_list(evidence_refs, "No representative evidence recorded automatically.", quote=False),
            "- Escalation triggers:",
            "- Widen review when entrypoint-sensitive files change or when the diff no longer maps cleanly to this agent scope.",
            "- Record durable decisions outside this AUTO block in `decisions.jsonl` or the project-level `decisions.md`.",
        ]
    )
    if agent == "reviewer":
        lines.append("- Reviewer memory should preserve recurring cross-module risks, stale docs, and missed test coverage patterns.")
    return "\n".join(lines)


def generate_skill_block(
    project: str,
    code_dir: Path,
    modules: list[str],
    module_map: dict[str, list[str]],
    global_paths: list[str],
    mode: SyncMode,
    manifests: list[str],
    repo_root: Path | None,
    branch: str | None,
    head: str | None,
) -> str:
    top_entries = limited_paths(list_top_level_entries(code_dir))
    commands = limited_paths(build_run_commands(code_dir))
    command_evidence = limited_paths(build_manifest_refs(code_dir))
    raw_entrypoints = entrypoint_candidates(code_dir)
    entrypoint_refs = limited_paths(line_refs_for_paths(code_dir, raw_entrypoints))
    docs = limited_paths(docs_paths(code_dir))
    manifest_refs = limited_paths(line_refs_for_paths(code_dir, manifests))

    lines = [
        "## Generated Context Summary",
        f"- Project: `{project}`",
        f"- Code directory: `{code_dir}`",
        f"- Sync mode: `{mode.name}`",
        f"- Sync reason: {mode.reason}",
    ]
    if repo_root:
        lines.extend(
            [
                f"- Git repo root: `{repo_root}`",
                f"- Git branch: `{branch or 'unknown'}`",
                f"- Git HEAD: `{head or 'unknown'}`",
            ]
        )
    else:
        lines.append("- Git repo root: not available; using full sync.")

    lines.extend(
        [
            "",
            "## Project Summary",
            "- Top-level areas discovered:",
            *format_list(top_entries, "No top-level entries discovered."),
            "- Top-level docs:",
            *format_list(docs, "No README/docs files discovered at the code root."),
            "- Tech signals:",
            *format_list(manifests, "No known build/runtime manifest found at the code root."),
            "- Tech-signal evidence:",
            *format_list(manifest_refs, "No manifest line references discovered automatically.", quote=False),
            "",
            "## Architecture And Boundaries",
            "- Global paths watched by sync:",
            *format_list(global_paths, "No dedicated global paths inferred."),
            "- Module map:",
        ]
    )

    for module in modules:
        if module == "reviewer":
            lines.append("- `reviewer` -> synthetic review module with no direct code roots")
            continue
        mapped_paths = limited_paths(module_map.get(module, []))
        if mapped_paths:
            lines.append(f"- `{module}` -> {', '.join(f'`{item}`' for item in mapped_paths)}")
        else:
            lines.append(f"- `{module}` -> no stable path mapping; sync may fall back to full refresh")

    lines.extend(
        [
            "",
            "## Entrypoints And Build Or Run",
            "- Common commands:",
            *format_list(commands, "No common commands discovered automatically."),
            "- Command manifest evidence:",
            *format_list(command_evidence, "No command manifest line references discovered automatically.", quote=False),
            "- Candidate entrypoints:",
            *format_list(entrypoint_refs, "No common entrypoint files discovered automatically.", quote=False),
            "",
            "## Module Navigation",
        ]
    )
    for module in modules:
        if module == "reviewer":
            lines.append("- `reviewer`: cross-cutting risk review and quality gates.")
            continue
        lines.append(
            f"- `{module}`: load `{layout.relative_module_overview(module)}` first, "
            f"then `{layout.relative_module_detail(module)}`."
        )

    lines.extend(
        [
            "",
            "## Progressive Loading Model",
            f"- L1: `{layout.SKILL_FILENAME}` for global overview, routing rules, loading order, and runtime notes.",
            f"- L2: `{layout.AGENTS_DIRNAME}/` and module overview files such as "
            f"`{layout.MODULES_DIRNAME}/<module>/{layout.MODULE_OVERVIEW_FILENAME}`.",
            f"- L3: module detail files such as `{layout.MODULES_DIRNAME}/<module>/<module>.md` "
            f"and detailed `{layout.REFERENCES_DIRNAME}/` docs.",
            "",
            "### Preferred Load Order",
            f"- Load `{layout.SKILL_FILENAME}` first.",
            f"- Route to the relevant agent under `{layout.AGENTS_DIRNAME}/<agent>/`.",
            "- Let that agent choose which module to inspect.",
            f"- Load `{layout.MODULES_DIRNAME}/<module>/{layout.MODULE_OVERVIEW_FILENAME}` before "
            f"`{layout.MODULES_DIRNAME}/<module>/<module>.md`.",
            f"- Load `{layout.REFERENCES_DIRNAME}/` only for evidence-level checks.",
            "",
            "## Spec-Driven Development",
            "- Keep spec-first changes outside this AUTO block if the project needs custom policy.",
            "- Minimum spec fields: scope, interfaces, edge cases, acceptance criteria, and tests.",
            f"- Record major spec changes in `{layout.DECISIONS_FILENAME}` or the relevant agent `{layout.AGENT_DECISIONS_FILENAME}`.",
        ]
    )
    return "\n".join(lines)


def generate_modules_index_block(modules: list[str], module_map: dict[str, list[str]]) -> str:
    lines = [
        "## Generated Module Index",
        "- Load the module README before the detailed module note.",
    ]
    for module in modules:
        mapped_paths = module_map.get(module, [])
        if module == "reviewer":
            lines.append("- `reviewer`: review-only module; does not map to a single code path.")
            continue
        if mapped_paths:
            lines.append(f"- `{module}`: covers {', '.join(f'`{path}`' for path in limited_paths(mapped_paths))}.")
        else:
            lines.append(f"- `{module}`: no stable path mapping inferred yet.")
    return "\n".join(lines)


def generate_module_overview_block(module: str, code_dir: Path, module_paths: list[str]) -> str:
    key_files = limited_paths(module_line_refs(code_dir, module_paths))
    tasks = module_tasks(module)
    lines = [
        "## Generated Overview",
        f"- Responsibility: {module_responsibility(module)}",
        "- Key areas/files with line evidence:",
        *format_list(key_files, "No concrete line-level evidence discovered yet.", quote=False),
        "- Typical tasks:",
        *[f"- {task}" for task in tasks],
    ]
    return "\n".join(lines)


def generate_module_detail_block(module: str, code_dir: Path, module_paths: list[str], module_map: dict[str, list[str]]) -> str:
    key_files = limited_paths(module_line_refs(code_dir, module_paths))
    entrypoints = limited_paths(line_refs_for_paths(code_dir, module_entrypoints(code_dir, module_paths)))
    tests = limited_paths(line_refs_for_paths(code_dir, module_test_paths(code_dir, module_paths)))
    sibling_modules = [name for name, paths in module_map.items() if name != module and paths]
    lines = [
        "## Generated Evidence Snapshot",
        "- Content inside this AUTO block is managed by `scripts/sync_context_project.py`.",
        "- Add durable manual notes outside the AUTO block so sync can preserve them.",
        "- If this block is edited manually, future syncs stop unless `--force-generated` is used.",
        "",
        "### Scope Evidence",
        f"- Covers: {', '.join(f'`{path}`' for path in module_paths) if module_paths else 'No stable path mapping inferred yet.'}",
        "",
        "### Responsibility Evidence",
        f"- {module_responsibility(module)}",
        "- Key files with line evidence:",
        *format_list(key_files, "No representative line-level evidence discovered automatically.", quote=False),
        "",
        "### Dependency Evidence",
    ]
    if sibling_modules:
        lines.extend(f"- See `{name}` module for adjacent behavior." for name in sibling_modules[:4])
    else:
        lines.append("- No adjacent module hints inferred.")
    lines.extend(
        [
            "",
            "### Flow Entrypoints",
            "- Candidate entrypoints with line evidence:",
            *format_list(entrypoints, "No common entrypoint line references discovered inside this module.", quote=False),
            "",
            "### Testing Hooks",
            *format_list(tests, "No module-local test evidence discovered automatically.", quote=False),
        ]
    )
    return "\n".join(lines)


def generate_entrypoints_block(code_dir: Path) -> str:
    entrypoints = limited_paths(line_refs_for_paths(code_dir, entrypoint_candidates(code_dir)))
    data_items = limited_paths(line_refs_for_paths(code_dir, data_paths(code_dir)))
    i18n_items = limited_paths(line_refs_for_paths(code_dir, i18n_paths(code_dir)))
    test_items = limited_paths(line_refs_for_paths(code_dir, test_paths(code_dir)))
    build_items = limited_paths(build_run_commands(code_dir))
    build_refs = limited_paths(build_manifest_refs(code_dir))

    lines = [
        "## Generated Entrypoints Index",
        "- Entry file index:",
        *format_list(entrypoints, "No common entrypoints discovered automatically.", quote=False),
        "- Data or storage index:",
        *format_list(data_items, "No data or storage paths discovered automatically.", quote=False),
        "- i18n index:",
        *format_list(i18n_items, "No i18n or locale paths discovered automatically.", quote=False),
        "- Testing and QA index:",
        *format_list(test_items, "No test or QA paths discovered automatically.", quote=False),
        "- Build or release or ops entrypoints:",
        *format_list(build_items, "No common build or runtime commands discovered automatically."),
        "- Build manifest evidence:",
        *format_list(build_refs, "No build manifest line references discovered automatically.", quote=False),
    ]
    return "\n".join(lines)


def generate_status_block(
    mode: SyncMode,
    review_plan: ReviewPlan,
    review_record: ReviewRecord,
    repo_root: Path | None,
    branch: str | None,
    head: str | None,
    changed_paths: list[str],
) -> str:
    lines = [
        "## Generated Sync Status",
        f"- Updated at: {now_iso()}",
        f"- Sync mode: `{mode.name}`",
        f"- Sync reason: {mode.reason}",
        f"- Review scope: `{review_plan.scope}`",
        f"- Review reason: {review_plan.reason}",
        f"- Review outcome: `{display_review_outcome(review_record.outcome)}`",
    ]
    if review_record.recorded_at:
        lines.append(f"- Review recorded at: `{review_record.recorded_at}`")
    else:
        lines.append("- Review recorded at: not recorded yet; this sync is still pending review completion.")
    if review_record.notes:
        lines.append(f"- Review notes: {review_record.notes}")
    else:
        lines.append("- Review notes: none recorded")
    if repo_root:
        lines.extend(
            [
                f"- Git repo root: `{repo_root}`",
                f"- Git branch: `{branch or 'unknown'}`",
                f"- Git HEAD: `{head or 'unknown'}`",
            ]
        )
    else:
        lines.append("- Git metadata: not available; this project is being synced in full-scan mode.")

    if mode.changed_modules:
        lines.append("- Changed modules: " + ", ".join(f"`{module}`" for module in mode.changed_modules))
    else:
        lines.append("- Changed modules: none detected")

    if review_plan.target_modules:
        lines.append("- Review target modules: " + ", ".join(f"`{module}`" for module in review_plan.target_modules))
    else:
        lines.append("- Review target modules: none")

    lines.append("- Changed paths sample:")
    lines.extend(format_list(limited_paths(changed_paths), "No changed paths detected in the watched code root."))
    lines.append("- Review path sample:")
    lines.extend(format_list(limited_paths(review_plan.target_paths), "No review-target paths detected."))
    return "\n".join(lines)


def build_updates(
    project_root: Path,
    project: str,
    code_dir: Path,
    modules: list[str],
    module_map: dict[str, list[str]],
    global_paths: list[str],
    mode: SyncMode,
    manifests: list[str],
    repo_root: Path | None,
    branch: str | None,
    head: str | None,
    changed_paths: list[str],
    review_plan: ReviewPlan,
    review_record: ReviewRecord,
) -> list[tuple[Path, str, str]]:
    updates: list[tuple[Path, str, str]] = []
    if mode.update_global or mode.name == "full":
        updates.append(
            (
                layout.skill_path(project_root),
                "l1",
                generate_skill_block(project, code_dir, modules, module_map, global_paths, mode, manifests, repo_root, branch, head),
            )
        )
        updates.append(
            (
                layout.entrypoints_path(project_root),
                "entrypoints",
                generate_entrypoints_block(code_dir),
            )
        )
        updates.append(
            (
                layout.modules_index_path(project_root),
                "module-index",
                generate_modules_index_block(modules, module_map),
            )
        )
        updates.append(
            (
                layout.agents_index_path(project_root),
                "agent-index",
                generate_agents_index_block(modules, module_map),
            )
        )

    module_targets = resolve_module_targets(mode, modules)
    agent_targets = resolve_agent_targets(mode, modules)

    for agent in agent_targets:
        updates.append(
            (
                layout.agent_readme_path(project_root, agent),
                "agent-readme",
                generate_agent_readme_block(agent, code_dir, module_map),
            )
        )
        updates.append(
            (
                layout.agent_tools_path(project_root, agent),
                "agent-tools",
                generate_agent_tools_block(agent, code_dir, module_map),
            )
        )
        updates.append(
            (
                layout.agent_memory_path(project_root, agent),
                "agent-memory",
                generate_agent_memory_block(agent, code_dir, module_map),
            )
        )

    for module in module_targets:
        module_paths = module_map.get(module, [])
        updates.append(
            (
                layout.module_overview_path(project_root, module),
                "module-overview",
                generate_module_overview_block(module, code_dir, module_paths),
            )
        )
        updates.append(
            (
                layout.module_detail_path(project_root, module),
                "module-detail",
                generate_module_detail_block(module, code_dir, module_paths, module_map),
            )
        )

    updates.append(
        (
            layout.project_status_path(project_root),
            "sync-status",
            generate_status_block(mode, review_plan, review_record, repo_root, branch, head, changed_paths),
        )
    )
    return updates


def apply_updates(project_root: Path, updates: list[tuple[Path, str, str]]) -> dict[str, str]:
    generated_hashes: dict[str, str] = {}
    for file_path, block_name, content in updates:
        original = read_text(file_path)
        updated = upsert_auto_block(original, block_name, content)
        write_text(file_path, updated)
        relative_doc_path = file_path.relative_to(project_root).as_posix()
        generated_hashes[auto_block_key(relative_doc_path, block_name)] = sha256_text(content.rstrip())
    return generated_hashes


def determine_sync_mode(
    git_repo_root: Path | None,
    current_state: dict,
    module_map: dict[str, list[str]],
    changed_paths: list[str],
    changed_modules: list[str],
    update_global: bool,
    unmatched_changes: list[str],
    sync_base_issue: str | None,
) -> SyncMode:
    if not git_repo_root:
        return SyncMode("full", [], True, "Non-Git project; full sync only.")
    if not current_state:
        return SyncMode("full", [], True, "No previous sync state found.")
    if current_state.get("state_version") != STATE_VERSION:
        return SyncMode("full", [], True, "Sync state version changed.")
    if current_state.get("module_map") != module_map:
        return SyncMode("full", [], True, "Module map changed since the last sync.")
    if sync_base_issue:
        return SyncMode("full", [], True, sync_base_issue)
    if unmatched_changes:
        return SyncMode("full", [], True, "Changed files could not be mapped to a module safely.")

    non_reviewer_modules = [module for module in module_map if module != "reviewer"]
    touched_count = len([module for module in changed_modules if module != "reviewer"])
    threshold = max(2, math.ceil(max(len(non_reviewer_modules), 1) * 0.5))
    if touched_count >= threshold and changed_paths:
        return SyncMode("full", [], True, "A broad change touched too many modules for safe incremental sync.")

    if update_global:
        return SyncMode("incremental", changed_modules, True, "Global or architecture-level files changed.")
    return SyncMode("incremental", changed_modules, False, "Scoped module changes detected.")


def determine_review_plan(
    project_root: Path,
    code_dir: Path,
    git_repo_root: Path | None,
    previous_state: dict,
    module_map: dict[str, list[str]],
    mode: SyncMode,
    changed_paths: list[str],
    changed_modules: list[str],
    unmatched_changes: list[str],
    sync_base_issue: str | None,
) -> ReviewPlan:
    if mode.name == "noop":
        return ReviewPlan(
            "noop",
            "No code changes detected. Start from Git state only and skip source re-reading.",
            [],
            [],
        )

    if not git_repo_root:
        return ReviewPlan(
            "broad-source-review",
            "Non-Git repo: no diff/tree baseline exists for targeted review.",
            sorted(changed_modules),
            changed_paths,
        )

    if not previous_state:
        return ReviewPlan(
            "broad-source-review",
            "Initial context build: no prior context baseline exists.",
            sorted(changed_modules),
            changed_paths,
        )

    if previous_state.get("state_version") != STATE_VERSION:
        return ReviewPlan(
            "broad-source-review",
            "Context sync state version changed; the previous baseline cannot be trusted for diff-only review.",
            sorted(changed_modules),
            changed_paths,
        )

    if previous_state.get("module_map") != module_map:
        return ReviewPlan(
            "broad-source-review",
            "Module map changed since the last sync.",
            sorted(changed_modules),
            changed_paths,
        )

    if sync_base_issue:
        return ReviewPlan(
            "broad-source-review",
            sync_base_issue,
            sorted(changed_modules),
            changed_paths,
        )

    if unmatched_changes:
        return ReviewPlan(
            "broad-source-review",
            "Diff could not be mapped cleanly to the existing module context.",
            sorted(changed_modules),
            changed_paths,
        )

    entrypoint_reason = detect_entrypoint_ambiguity(code_dir, changed_paths)
    if entrypoint_reason:
        return ReviewPlan(
            "broad-source-review",
            entrypoint_reason,
            sorted(changed_modules),
            changed_paths,
        )

    scoped_modules = sorted(changed_modules)
    scoped_agents = resolve_agent_targets(mode, scoped_modules)
    scope_mismatch = detect_context_scope_mismatch(
        project_root,
        scoped_modules,
        scoped_agents,
        mode.update_global or mode.name == "full",
    )
    if scope_mismatch:
        mismatch_sample = ", ".join(f"`{item}`" for item in limited_paths(scope_mismatch))
        return ReviewPlan(
            "broad-source-review",
            "Context files or AUTO blocks for the diff scope are missing or out of shape. "
            f"Targets: {mismatch_sample}.",
            scoped_modules,
            changed_paths,
        )

    return ReviewPlan(
        "git-diff-only",
        "Start from Git diff/tree and spot-check only the modules hit by the diff. "
        "Broaden source review only if the targeted check finds a mismatch.",
        scoped_modules,
        changed_paths,
    )


def normalize_review_outcome(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in REVIEW_OUTCOME_CHOICES:
        choices = ", ".join(f"`{item}`" for item in ("pending", "pass", "pass-with-findings", "fail"))
        raise SyncError(f"Invalid review outcome `{value}`. Expected one of {choices}.")
    return normalized


def display_review_outcome(value: str) -> str:
    return value.replace("_", " ")


def determine_review_record(
    previous_state: dict,
    mode: SyncMode,
    current_head: str | None,
    requested_outcome: str | None,
    requested_notes: str | None,
) -> ReviewRecord:
    normalized_outcome = normalize_review_outcome(requested_outcome)
    if requested_notes and not normalized_outcome:
        raise SyncError("`--review-notes` requires `--review-outcome`.")

    if mode.name == "noop":
        review_record = ReviewRecord(
            previous_state.get("last_review_outcome") or "pending",
            previous_state.get("last_review_notes"),
            previous_state.get("last_review_at"),
            previous_state.get("last_review_head"),
        )
    else:
        review_record = ReviewRecord("pending", None, None, None)

    if normalized_outcome:
        review_record = ReviewRecord(
            normalized_outcome,
            requested_notes.strip() if requested_notes else None,
            now_iso(),
            current_head,
        )

    return review_record


def validate_source_identity(previous_state: dict, source: ResolvedSource, git_repo_root: Path | None) -> None:
    if not previous_state:
        return

    previous_source_type = previous_state.get("source_type")
    previous_git_url = previous_state.get("source_git_url")
    previous_code_dir = previous_state.get("code_dir")
    previous_repo_root = previous_state.get("repo_root")

    if previous_source_type and previous_source_type != source.source_type:
        raise SyncError(
            "Existing project context is already bound to a different source type. "
            "Use a new project name if you want to analyze a different repository."
        )

    if previous_git_url:
        if not source.git_url or normalize_source_locator(previous_git_url) != normalize_source_locator(source.git_url):
            raise SyncError(
                "Existing project context is already bound to a different Git source. "
                "Use a new project name if you want to analyze a different repository."
            )
        return

    if previous_code_dir:
        previous_path = Path(previous_code_dir).expanduser().resolve()
        if previous_path != source.code_dir:
            raise SyncError(
                "Existing project context is already bound to a different local code directory. "
                "Use a new project name if you want to analyze a different repository."
            )

    if previous_repo_root and git_repo_root:
        if Path(previous_repo_root).expanduser().resolve() != git_repo_root:
            raise SyncError(
                "Existing project context is already bound to a different Git repository root. "
                "Use a new project name if you want to analyze a different repository."
            )


def prepare_state(
    previous_state: dict,
    project_root: Path,
    code_dir: Path,
    git_repo_root: Path | None,
    current_head: str | None,
    branch: str | None,
    source: ResolvedSource,
    module_map: dict[str, list[str]],
    global_paths: list[str],
    generated_hashes: dict[str, str],
    mode: SyncMode,
    review_plan: ReviewPlan,
    review_record: ReviewRecord,
) -> dict:
    merged_hashes = dict(previous_state.get("generated_hashes") or {})
    merged_hashes.update(generated_hashes)
    return {
        "state_version": STATE_VERSION,
        "project_root": str(project_root),
        "code_dir": str(code_dir),
        "repo_root": str(git_repo_root) if git_repo_root else None,
        "source_type": source.source_type,
        "source_git_url": source.git_url,
        "managed_source": source.managed,
        "last_synced_head": current_head if git_repo_root else None,
        "last_synced_branch": branch if git_repo_root else None,
        "last_sync_at": now_iso(),
        "last_sync_mode": mode.name,
        "last_review_scope": review_plan.scope,
        "last_review_reason": review_plan.reason,
        "last_review_modules": review_plan.target_modules,
        "last_review_outcome": review_record.outcome,
        "last_review_notes": review_record.notes,
        "last_review_at": review_record.recorded_at,
        "last_review_head": review_record.reviewed_head,
        "module_map": module_map,
        "global_paths": global_paths,
        "generated_hashes": merged_hashes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize a team-style project context directory.")
    parser.add_argument("--project", required=True, help="Project name (folder name).")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--code-dir", help="Absolute path to the local code directory.")
    source_group.add_argument("--git-url", help="Git repository URL or local Git path to clone for analysis.")
    parser.add_argument(
        "--target-root",
        default=str(layout.DEFAULT_TARGET_ROOT),
        help=f"Target root for team context (default: {layout.DEFAULT_TARGET_ROOT_DISPLAY}).",
    )
    parser.add_argument(
        "--force-generated",
        action="store_true",
        help="Overwrite AUTO blocks even if they were edited after the last sync.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without writing files.",
    )
    parser.add_argument(
        "--review-outcome",
        help="Record the review result for this sync: pending, pass, pass-with-findings, or fail.",
    )
    parser.add_argument(
        "--review-notes",
        help="Optional short review summary or findings note. Requires --review-outcome.",
    )
    args = parser.parse_args()

    target_root = Path(args.target_root).expanduser().resolve()
    project_root = layout.project_root(target_root, args.project)
    previous_state = load_state(project_root)

    try:
        source = resolve_code_source(
            args.project,
            target_root,
            code_dir=args.code_dir,
            git_url=args.git_url,
            allow_mutation=not args.dry_run,
        )
    except SourceResolutionError as exc:
        raise SyncError(str(exc)) from exc

    code_dir = source.code_dir

    if not args.dry_run:
        run_init_scaffold(args.project, code_dir, target_root)

    modules = infer_modules(code_dir)
    module_map, global_paths, _ = discover_module_map(code_dir, modules)
    git_repo_root = is_git_repo(code_dir)
    validate_source_identity(previous_state, source, git_repo_root)

    changed_paths: list[str] = []
    branch: str | None = None
    current_head: str | None = None
    sync_base_issue: str | None = None
    if git_repo_root:
        changed_paths, current_head, branch, sync_base_issue = git_changed_files(
            git_repo_root,
            code_dir,
            previous_state.get("last_synced_head"),
            bool(previous_state),
        )

    changed_modules: list[str] = []
    update_global = True
    unmatched_changes: list[str] = []
    if git_repo_root and previous_state.get("state_version") == STATE_VERSION:
        changed_modules, update_global, unmatched_changes = map_changed_paths(changed_paths, module_map, global_paths)

    mode = determine_sync_mode(
        git_repo_root,
        previous_state,
        module_map,
        changed_paths,
        changed_modules,
        update_global,
        unmatched_changes,
        sync_base_issue,
    )

    if git_repo_root and mode.name == "incremental" and not changed_paths:
        mode = SyncMode("noop", [], False, "No code changes detected since the last successful sync.")

    review_plan = determine_review_plan(
        project_root,
        code_dir,
        git_repo_root,
        previous_state,
        module_map,
        mode,
        changed_paths,
        changed_modules,
        unmatched_changes,
        sync_base_issue,
    )
    review_record = determine_review_record(
        previous_state,
        mode,
        current_head,
        args.review_outcome,
        args.review_notes,
    )

    manifests = detect_manifests(code_dir)
    updates = build_updates(
        project_root,
        args.project,
        code_dir,
        modules,
        module_map,
        global_paths,
        mode if mode.name != "noop" else SyncMode("noop", [], False, mode.reason),
        manifests,
        git_repo_root,
        branch,
        current_head,
        changed_paths,
        review_plan,
        review_record,
    )

    conflicts = detect_auto_conflicts(
        project_root,
        updates,
        previous_state.get("generated_hashes") or {},
        args.force_generated,
    )
    if conflicts:
        conflict_message = "\n".join(f"- {conflict}" for conflict in conflicts)
        raise SyncError(
            "Refusing to overwrite manually edited AUTO blocks.\n"
            "Move notes outside the AUTO block or rerun with --force-generated.\n"
            f"{conflict_message}"
        )

    generated_hashes: dict[str, str] = {}
    if args.dry_run:
        print(f"[dry-run] mode={mode.name}")
        for file_path, block_name, _ in updates:
            print(f"[dry-run] update {file_path.relative_to(project_root)} [{block_name}]")
    else:
        generated_hashes = apply_updates(project_root, updates)

    next_state = prepare_state(
        previous_state,
        project_root,
        code_dir,
        git_repo_root,
        current_head,
        branch,
        source,
        module_map,
        global_paths,
        generated_hashes,
        mode,
        review_plan,
        review_record,
    )
    if args.dry_run:
        print(f"[dry-run] state -> {state_path(project_root)}")
    else:
        save_state(project_root, next_state)

    print(f"Sync mode: {mode.name}")
    print(f"Reason: {mode.reason}")
    print(f"Review scope: {review_plan.scope}")
    print(f"Review reason: {review_plan.reason}")
    print(f"Review outcome: {display_review_outcome(review_record.outcome)}")
    if changed_paths:
        print(f"Changed paths: {len(changed_paths)}")
    if mode.changed_modules:
        print("Changed modules: " + ", ".join(mode.changed_modules))
    if review_plan.target_modules:
        print("Review target modules: " + ", ".join(review_plan.target_modules))


if __name__ == "__main__":
    try:
        main()
    except SyncError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
