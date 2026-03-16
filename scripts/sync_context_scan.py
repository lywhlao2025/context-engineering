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
from collections import Counter, defaultdict
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
from init_context_project import (
    CORE_TECH_MODULES,
    ensure_project_modules,
    infer_detected_modules,
    infer_modules,
    normalize_source_modules,
)
from source_resolver import ResolvedSource, SourceResolutionError, normalize_source_locator, resolve_code_source


STATE_VERSION = 5
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
MULTI_SOURCE_FILENAMES = ("context-sources.json", ".context-sources.json")
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
PYTHON_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)\b"),
)
JS_TS_SYMBOL_PATTERNS = (
    re.compile(r"^\s*export\s+default\s+class\s+([A-Za-z_$][\w$]*)\b"),
    re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)\b"),
    re.compile(r"^\s*export\s+default\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\b"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
    re.compile(r"^\s*(?:export\s+)?(?:type|interface|enum)\s+([A-Za-z_$][\w$]*)\b"),
)
GO_SYMBOL_PATTERNS = (
    re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_]\w*)\s*\("),
)
RUST_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\s*\("),
)
RUBY_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:def|class|module)\s+([A-Za-z_]\w*[!?=]?)\b"),
)
GENERIC_CLASS_SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:public|private|protected|internal|final|sealed|abstract|static|open|data|suspend|override|\s)*(?:class|interface|enum|record|struct|object)\s+([A-Za-z_]\w*)\b"),
)
SYMBOL_PATTERNS_BY_SUFFIX = {
    ".py": PYTHON_SYMBOL_PATTERNS,
    ".js": JS_TS_SYMBOL_PATTERNS,
    ".jsx": JS_TS_SYMBOL_PATTERNS,
    ".ts": JS_TS_SYMBOL_PATTERNS,
    ".tsx": JS_TS_SYMBOL_PATTERNS,
    ".mjs": JS_TS_SYMBOL_PATTERNS,
    ".cjs": JS_TS_SYMBOL_PATTERNS,
    ".go": GO_SYMBOL_PATTERNS,
    ".rs": RUST_SYMBOL_PATTERNS,
    ".rb": RUBY_SYMBOL_PATTERNS,
    ".java": GENERIC_CLASS_SYMBOL_PATTERNS,
    ".kt": GENERIC_CLASS_SYMBOL_PATTERNS,
    ".kts": GENERIC_CLASS_SYMBOL_PATTERNS,
    ".cs": GENERIC_CLASS_SYMBOL_PATTERNS,
    ".swift": GENERIC_CLASS_SYMBOL_PATTERNS,
}
PRD_FILENAME_CANDIDATES = ("prd.md", "requirements.md")
PRD_DIRNAME = "prd"
REQ_ID_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_-]{1,24}-\d{1,6})\b")
PRD_HEADING_PATTERN = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
PRD_LIST_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.+?)\s*$")
PRD_SECTION_IGNORE = {
    "overview",
    "scope",
    "background",
    "goals",
    "goal",
    "goals and scope",
    "requirements",
    "appendix",
    "附录",
    "背景",
    "目标",
    "范围",
    "需求",
}
MATCH_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "when",
    "where",
    "what",
    "which",
    "will",
    "must",
    "should",
    "need",
    "allow",
    "allows",
    "can",
    "able",
    "about",
    "under",
    "over",
    "after",
    "before",
    "todo",
    "done",
    "feature",
    "features",
    "requirement",
    "requirements",
    "module",
    "modules",
}
ROOT_CONTAINER_SEGMENTS = {"src", "app", "apps", "service", "services", "api"}
GENERIC_TECHNICAL_SEGMENTS = {
    "shared",
    "common",
    "core",
    "lib",
    "libs",
    "utils",
    "util",
    "components",
    "pages",
    "views",
    "hooks",
    "store",
    "stores",
    "types",
    "models",
    "entities",
    "dto",
    "contracts",
    "services",
    "controllers",
    "routes",
    "repository",
    "repositories",
    "locale",
    "locales",
    "translation",
    "translations",
}
SUMMARY_AREA_CONTAINER_SEGMENTS = {
    "src",
    "app",
    "apps",
    "lib",
    "libs",
    "internal",
    "client",
    "server",
    "web",
    "ui",
}
LANGUAGE_NAMES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript/JSX",
    ".ts": "TypeScript",
    ".tsx": "TypeScript/TSX",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".cs": "C#",
    ".swift": "Swift",
    ".php": "PHP",
    ".scala": "Scala",
    ".sql": "SQL",
    ".prisma": "Prisma",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".ini": "INI",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".vue": "Vue",
    ".svelte": "Svelte",
}
SUMMARY_TEXT_SUFFIXES = set(LANGUAGE_NAMES) | {
    ".md",
    ".txt",
    ".env",
    ".conf",
    ".cfg",
    ".properties",
}
SUMMARY_BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svg",
    ".pdf",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".lock",
}
MAX_SUMMARY_SCAN_FILES = 200
MAX_SUMMARY_AREA_ITEMS = 4
MAX_SUMMARY_CATEGORY_ITEMS = 4
MAX_SUMMARY_REFS = 3
MODULE_CATEGORY_KEYWORDS = {
    "frontend": {
        "pages": ("page", "pages", "screen", "screens", "view", "views", "route", "routes"),
        "components": ("component", "components", "layout", "layouts", "widget", "widgets", "ui"),
        "hooks": ("hook", "hooks", "composable", "composables"),
        "state": ("store", "stores", "state", "redux", "zustand", "context", "contexts", "provider", "providers"),
        "forms": ("form", "forms", "validation", "validator", "validators"),
        "api": ("api", "client", "clients", "query", "queries", "mutation", "mutations", "service", "services", "graphql"),
        "i18n": ("i18n", "locale", "locales", "translation", "translations"),
        "styles": ("style", "styles", "theme", "themes", "css", "scss", "sass"),
    },
    "backend": {
        "http": ("route", "routes", "router", "routers", "controller", "controllers", "handler", "handlers", "endpoint", "endpoints", "api"),
        "service": ("service", "services", "usecase", "usecases", "use-case", "domain", "logic"),
        "data": ("repo", "repository", "repositories", "dao", "model", "models", "schema", "schemas", "entity", "entities", "db", "database", "migration", "migrations", "sql", "prisma", "orm"),
        "job": ("worker", "workers", "job", "jobs", "queue", "queues", "task", "tasks", "cron", "scheduler"),
        "auth": ("auth", "oauth", "jwt", "session", "token", "permission", "permissions", "acl", "rbac"),
        "integration": ("client", "clients", "gateway", "gateways", "adapter", "adapters", "sdk", "webhook", "webhooks", "integration", "integrations"),
        "config": ("config", "configs", "setting", "settings", "env"),
    },
    "qa": {
        "unit": ("test", "tests", "spec", "specs"),
        "e2e": ("e2e", "playwright", "cypress"),
        "fixtures": ("fixture", "fixtures", "mock", "mocks", "stub", "stubs"),
    },
    "mobile": {
        "screens": ("screen", "screens", "view", "views", "page", "pages"),
        "state": ("store", "stores", "state", "context", "contexts", "provider", "providers"),
        "api": ("api", "client", "clients", "query", "queries", "mutation", "mutations", "service", "services"),
        "device": ("push", "notification", "permissions", "camera", "location", "bluetooth"),
        "styles": ("style", "styles", "theme", "themes"),
    },
    "data": {
        "pipelines": ("pipeline", "pipelines", "etl", "job", "jobs", "workflow", "workflows"),
        "models": ("model", "models", "feature", "features"),
        "storage": ("warehouse", "lake", "dataset", "datasets", "schema", "schemas", "sql"),
        "quality": ("test", "tests", "validation", "validator", "validators", "quality"),
    },
    "ops": {
        "deploy": ("deploy", "deployment", "helm", "k8s", "kubernetes", "terraform", "docker", "compose"),
        "runtime": ("env", "config", "configs", "secret", "secrets", "runtime"),
        "ci": ("github", "actions", "ci", "workflow", "workflows", "pipeline", "pipelines"),
        "observability": ("monitor", "monitoring", "metrics", "logging", "logs", "trace", "tracing", "alert"),
    },
}
MODULE_CATEGORY_LABELS = {
    "frontend": {
        "pages": "User-facing flows and route-level screens",
        "components": "Reusable UI components and layout primitives",
        "hooks": "Stateful client-side hooks or composables",
        "state": "Client state containers and shared UI state",
        "forms": "Forms and validation logic",
        "api": "Client-side API/query integration code",
        "i18n": "Localization helpers and locale assets",
        "styles": "Styling and theme layers",
    },
    "backend": {
        "http": "HTTP/API entrypoints and request handlers",
        "service": "Business logic and orchestration services",
        "data": "Persistence, schema, and data access code",
        "job": "Background jobs and async processing",
        "auth": "Authentication and authorization code",
        "integration": "External integrations and client adapters",
        "config": "Runtime configuration and environment wiring",
    },
    "qa": {
        "unit": "Unit and module-level verification paths",
        "e2e": "End-to-end or browser-driven test flows",
        "fixtures": "Fixtures, mocks, and test data helpers",
    },
    "mobile": {
        "screens": "Screen-level user flows",
        "state": "Shared state and lifecycle coordination",
        "api": "Remote data access and sync code",
        "device": "Device capability integrations",
        "styles": "Styling and theme layers",
    },
    "data": {
        "pipelines": "Pipelines and scheduled data movement",
        "models": "Models and feature-engineering code",
        "storage": "Schemas, datasets, and storage contracts",
        "quality": "Data validation and quality checks",
    },
    "ops": {
        "deploy": "Deployment and environment rollout logic",
        "runtime": "Runtime configuration and secret management",
        "ci": "CI/CD workflows and automation",
        "observability": "Metrics, logging, and alerting setup",
    },
}
MODULE_FRAMEWORK_PATTERNS = {
    "frontend": {
        "React": ("from 'react'", 'from "react"', "react-dom", "jsx", "tsx"),
        "Next.js": ("next.config", "from 'next", 'from "next', "next/navigation", "next/server"),
        "Vue": ("from 'vue'", 'from "vue"', "definecomponent(", "createapp("),
        "Svelte": ("from 'svelte'", 'from "svelte"', ".svelte"),
        "Redux": ("@reduxjs/toolkit", "redux", "createstore(", "configurestore("),
    },
    "backend": {
        "Express": ("from 'express'", 'from "express"', "express()", "express.router("),
        "FastAPI": ("from fastapi", "fastapi(", "@app.", "@router."),
        "Django": ("django.", "urlpatterns", "rest_framework"),
        "Flask": ("from flask", "flask(", "@app.route"),
        "Spring": ("@restcontroller", "@controller", "@service", "@repository"),
        "NestJS": ("@nestjs/", "@controller(", "@injectable("),
        "Prisma": ("prisma", "schema.prisma"),
        "SQLAlchemy": ("sqlalchemy", "declarative_base", "sessionmaker"),
    },
    "qa": {
        "Playwright": ("playwright", "@playwright/test"),
        "Cypress": ("cypress", "cy."),
        "Jest": ("jest", "describe(", "test("),
        "Pytest": ("pytest", "def test_"),
    },
    "mobile": {
        "React Native": ("react-native", "@react-navigation"),
        "SwiftUI": ("import swiftui", "struct ", "var body: some view"),
        "Kotlin Android": ("androidx.", "compose", "@composable"),
    },
    "data": {
        "dbt": ("dbt", "ref(", "source("),
        "Airflow": ("airflow", "dag(", "@dag"),
        "Spark": ("pyspark", "spark.", "sparksession"),
        "Pandas": ("import pandas", "pd."),
    },
    "ops": {
        "Docker": ("dockerfile", "docker-compose", "compose.yaml"),
        "Terraform": ("terraform", "resource ", "provider "),
        "Kubernetes": ("apiversion:", "kind:", "helm"),
        "GitHub Actions": ("name:", "on:", "jobs:", ".github/workflows"),
    },
}
DOMAIN_ENTITY_SKIP_TOKENS = {
    "src",
    "app",
    "apps",
    "service",
    "services",
    "api",
    "backend",
    "frontend",
    "shared",
    "common",
    "core",
    "lib",
    "libs",
    "utils",
    "util",
    "components",
    "pages",
    "views",
    "hooks",
    "store",
    "stores",
    "types",
    "models",
    "entities",
    "dto",
    "controller",
    "controllers",
    "routes",
    "tests",
    "test",
    "__tests__",
    "spec",
}
DOMAIN_STATE_PATTERN = re.compile(r"['\"]([a-z][a-z0-9_-]{2,})['\"]")
DOMAIN_RULE_KEYWORDS = ("must", "should", "require", "required", "if ", "when ", ">=", "<=", "==", "!=")


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


@dataclass
class RequirementCandidate:
    req_id: str
    title: str
    text: str
    prd_ref: str


@dataclass
class ModuleProfile:
    total_files: int
    inspected_files: int
    languages: list[tuple[str, int]]
    focus_areas: list[tuple[str, int]]
    category_refs: dict[str, list[str]]
    category_counts: dict[str, int]
    frameworks: list[tuple[str, int]]
    key_refs: list[str]
    entrypoints: list[str]
    tests: list[str]
    area_refs: dict[str, list[str]]


@dataclass
class FeatureProfile:
    total_files: int
    inspected_files: int
    languages: list[tuple[str, int]]
    focus_areas: list[tuple[str, int]]
    category_refs: dict[str, list[str]]
    category_counts: dict[str, int]
    frameworks: list[tuple[str, int]]
    key_refs: list[str]
    entrypoints: list[str]
    tests: list[str]
    area_refs: dict[str, list[str]]


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


def load_multi_sources(code_dir: Path) -> list[dict] | None:
    config_path = None
    for filename in MULTI_SOURCE_FILENAMES:
        candidate = code_dir / filename
        if candidate.exists():
            config_path = candidate
            break
    if not config_path:
        return None
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(f"Invalid multi-source config at {config_path}: {exc}") from exc
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SyncError(f"Multi-source config at {config_path} must include a non-empty 'sources' list.")
    normalized = []
    seen_names = set()
    for item in sources:
        if not isinstance(item, dict):
            raise SyncError("Each source entry in multi-source config must be an object.")
        name = str(item.get("name", "")).strip()
        path_raw = str(item.get("path", "")).strip()
        if not name or not path_raw:
            raise SyncError("Each source entry must include 'name' and 'path'.")
        if name in seen_names:
            raise SyncError(f"Duplicate source name '{name}' in multi-source config.")
        source_path = Path(path_raw).expanduser().resolve()
        if not source_path.exists():
            raise SyncError(f"Source path does not exist for '{name}': {source_path}")
        modules = item.get("modules")
        if modules is not None:
            if not isinstance(modules, list) or not modules:
                raise SyncError(f"Source '{name}' modules must be a non-empty list when provided.")
            try:
                modules = normalize_source_modules(modules, name)
            except ValueError as exc:
                raise SyncError(str(exc)) from exc
        normalized.append({
            "name": name,
            "path": source_path,
            "modules": modules,
        })
        seen_names.add(name)
    return normalized


def multi_source_last_synced_head(previous_state: dict, source_name: str) -> str | None:
    multi_state = previous_state.get("multi_sources")
    if not isinstance(multi_state, dict):
        return None
    source_state = multi_state.get(source_name)
    if not isinstance(source_state, dict):
        return None
    last_synced_head = source_state.get("last_synced_head")
    if not isinstance(last_synced_head, str):
        return None
    normalized = last_synced_head.strip()
    return normalized or None


def ensure_multi_symlinks(code_dir: Path, sources: list[dict], allow_mutation: bool) -> None:
    for source in sources:
        link_path = code_dir / source["name"]
        target_path = source["path"]
        if link_path.exists():
            continue
        if not allow_mutation:
            raise SyncError(
                f"Missing source link at {link_path}. Create it or rerun without --dry-run."
            )
        link_path.parent.mkdir(parents=True, exist_ok=True)
        link_path.symlink_to(target_path, target_is_directory=True)


def infer_modules_from_sources(sources: list[dict]) -> list[str]:
    modules: set[str] = set()
    for source in sources:
        # Keep first-layer modules code-driven for multi-source projects.
        source_modules = infer_detected_modules(source["path"])
        for module in source_modules:
            if module:
                modules.add(module)
    return ensure_project_modules(modules)


def build_module_map_from_sources(sources: list[dict]) -> tuple[dict[str, list[str]], list[str]]:
    module_map: dict[str, list[str]] = {}
    global_paths: list[str] = []
    for source in sources:
        source_name = str(source["name"]).strip("/")
        source_root = source["path"]
        source_modules = infer_detected_modules(source_root)
        normalized_modules = [module for module in source_modules if module and module != "reviewer"]
        for module in normalized_modules:
            module_map.setdefault(module, [])

        source_module_map, source_global_paths, _ = discover_module_map(source_root, source_modules)
        for module in normalized_modules:
            roots = source_module_map.get(module, [])
            prefixed_roots = [f"{source_name}/{root}" for root in roots if root]
            if prefixed_roots:
                module_map[module].extend(prefixed_roots)
                continue
            # Only fall back to source root when that source maps to one module.
            if len(normalized_modules) == 1 and source_name:
                module_map[module].append(source_name)

        global_paths.extend(f"{source_name}/{path}" for path in source_global_paths if path)

    normalized_map: dict[str, list[str]] = {}
    if not module_map:
        for module in CORE_TECH_MODULES:
            module_map.setdefault(module, [])
    for module, roots in module_map.items():
        normalized_map[module] = sorted(dict.fromkeys(roots))
    normalized_global_paths = sorted(dict.fromkeys(global_paths))
    return normalized_map, normalized_global_paths


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


def module_feature_targets(
    module_targets: list[str],
    feature_map: dict[str, dict[str, list[str]]],
) -> dict[str, list[str]]:
    targets: dict[str, list[str]] = {}
    for module in module_targets:
        targets[module] = sorted(feature_map.get(module, {}).keys())
    return targets


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
    feature_targets: dict[str, list[str]],
    include_global: bool,
) -> list[tuple[Path, str]]:
    targets: list[tuple[Path, str]] = []
    if include_global:
        targets.extend(
            [
                (layout.skill_path(project_root), "l1"),
                (layout.entrypoints_path(project_root), "entrypoints"),
                (layout.feature_map_path(project_root), "feature-map"),
                (layout.requirements_map_path(project_root), "requirements-map"),
                (layout.domain_model_path(project_root), "domain-model"),
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
        for feature in feature_targets.get(module, []):
            targets.append((layout.module_feature_path(project_root, module, feature), "feature-detail"))
    targets.append((layout.project_status_path(project_root), "sync-status"))
    return targets


def detect_context_scope_mismatch(
    project_root: Path,
    module_targets: list[str],
    agent_targets: list[str],
    feature_targets: dict[str, list[str]],
    include_global: bool,
) -> list[str]:
    missing: list[str] = []
    for file_path, block_name in expected_generated_targets(project_root, module_targets, agent_targets, feature_targets, include_global):
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
    manual_text = pattern.sub("", text).strip()
    if manual_text:
        return f"{block}\n\n{manual_text}\n"
    return block + "\n"


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


def first_meaningful_line_from_lines(file_path: Path, lines: list[str]) -> int | None:
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
    return 1 if file_path.exists() else None


def first_meaningful_line(file_path: Path) -> int | None:
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    return first_meaningful_line_from_lines(file_path, lines)


def normalize_symbol_token(value: str) -> str | None:
    token = value.strip().strip("'\"`[](){}")
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", token).strip("-")
    return token or None


def first_symbol_anchor(file_path: Path, lines: list[str]) -> tuple[str, int] | None:
    patterns = SYMBOL_PATTERNS_BY_SUFFIX.get(file_path.suffix.lower(), ())
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "//", "/*", "*", "--", ";", "<!--")):
            continue
        for pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            symbol = normalize_symbol_token(match.group(1))
            if symbol:
                return symbol, line_number
    for hint in LINE_HINTS_BY_FILENAME.get(file_path.name, ()):
        for line_number, line in enumerate(lines, start=1):
            if hint not in line:
                continue
            symbol = normalize_symbol_token(hint)
            if symbol:
                return symbol, line_number
    return None


def first_evidence_file(path: Path) -> Path | None:
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    for candidate in walk_files(path):
        return candidate
    return None


def format_line_ref(relative_path: str, symbol: str | None, line_number: int | None) -> str:
    if symbol and line_number:
        return f"`{relative_path}#{symbol}:{line_number}`"
    if symbol:
        return f"`{relative_path}#{symbol}`"
    if line_number:
        return f"`{relative_path}:{line_number}`"
    return f"`{relative_path}`"


def path_line_ref(code_dir: Path, relative_path: str) -> str:
    candidate = code_dir / relative_path
    evidence_file = first_evidence_file(candidate)
    if not evidence_file:
        return format_line_ref(relative_path, None, None)
    relative = evidence_file.relative_to(code_dir).as_posix()
    try:
        lines = evidence_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return format_line_ref(relative, None, None)
    symbol_anchor = first_symbol_anchor(evidence_file, lines)
    if symbol_anchor:
        symbol, line_number = symbol_anchor
        return format_line_ref(relative, symbol, line_number)
    return format_line_ref(relative, None, first_meaningful_line_from_lines(evidence_file, lines))


def line_refs_for_paths(code_dir: Path, paths: list[str], limit: int = MAX_LISTED_ITEMS) -> list[str]:
    refs = [path_line_ref(code_dir, path) for path in paths]
    return limited_paths(list(dict.fromkeys(refs)), limit)


def collect_symbol_anchors(file_path: Path, lines: list[str], limit: int = 3) -> list[tuple[str, int]]:
    patterns = SYMBOL_PATTERNS_BY_SUFFIX.get(file_path.suffix.lower(), ())
    anchors: list[tuple[str, int]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "//", "/*", "*", "--", ";", "<!--")):
            continue
        for pattern in patterns:
            match = pattern.search(line)
            if not match:
                continue
            symbol = normalize_symbol_token(match.group(1))
            if not symbol or symbol in seen:
                continue
            anchors.append((symbol, line_number))
            seen.add(symbol)
            if len(anchors) >= limit:
                return anchors
    if anchors:
        return anchors
    for hint in LINE_HINTS_BY_FILENAME.get(file_path.name, ()):
        for line_number, line in enumerate(lines, start=1):
            if hint not in line:
                continue
            symbol = normalize_symbol_token(hint)
            if symbol:
                return [(symbol, line_number)]
    return anchors


def normalize_feature_token(value: str) -> str:
    token = value.lower()
    if "." in token:
        token = token.rsplit(".", 1)[0]
    token = re.sub(r"[_\s/]+", "-", token)
    token = re.sub(r"[^a-z0-9-]+", "-", token)
    token = re.sub(r"-{2,}", "-", token).strip("-")
    return token


def symbol_matches_feature(symbol: str, feature: str, feature_parts: list[str]) -> bool:
    symbol_norm = normalize_feature_token(symbol)
    if not symbol_norm:
        return False
    if symbol_norm == feature:
        return True
    compact = feature.replace("-", "")
    if compact and compact in symbol_norm:
        return True
    if feature_parts and all(part in symbol_norm for part in feature_parts):
        return True
    return False


def text_matches_feature(text_lower: str, feature: str, feature_parts: list[str]) -> bool:
    variants = {
        feature,
        feature.replace("-", "_"),
        feature.replace("-", " "),
        feature.replace("-", ""),
    }
    for variant in variants:
        if variant and variant in text_lower:
            return True
    strong_parts = [part for part in feature_parts if len(part) >= 3]
    if strong_parts and all(part in text_lower for part in strong_parts):
        return True
    return False


def has_feature_code_evidence(file_path: Path, feature: str) -> bool:
    if not file_path.is_file():
        return False
    feature_norm = normalize_feature_token(feature)
    if not feature_norm:
        return False
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False

    feature_parts = [part for part in feature_norm.split("-") if part]
    for symbol, _ in collect_symbol_anchors(file_path, lines, limit=8):
        if symbol_matches_feature(symbol, feature_norm, feature_parts):
            return True

    text_lower = "\n".join(lines).lower()
    return text_matches_feature(text_lower, feature_norm, feature_parts)


def module_scoped_files(code_dir: Path, module_paths: list[str]) -> list[str]:
    matches: list[str] = []
    for root in module_paths:
        candidate = code_dir / root
        if candidate.is_file():
            matches.append(root)
            continue
        if not candidate.exists():
            continue
        for file_path in walk_files(candidate):
            matches.append(file_path.relative_to(code_dir).as_posix())
    return sorted(dict.fromkeys(matches))


def relative_within_module_root(relative_path: str, module_paths: list[str]) -> str:
    rel = PurePosixPath(relative_path)
    for root in sorted(module_paths, key=len, reverse=True):
        root_path = PurePosixPath(root)
        try:
            return rel.relative_to(root_path).as_posix()
        except ValueError:
            continue
    return relative_path


def feature_candidate_for_path(relative_path: str, module: str) -> str | None:
    path = PurePosixPath(relative_path)
    segment_candidates = [normalize_feature_token(part) for part in path.parts[:-1]]
    segment_candidates = [part for part in segment_candidates if part]

    if not segment_candidates:
        return None

    while segment_candidates and segment_candidates[0] in ROOT_CONTAINER_SEGMENTS:
        segment_candidates = segment_candidates[1:]
    if not segment_candidates:
        return None

    candidate = ""
    for segment in segment_candidates:
        if segment in GENERIC_TECHNICAL_SEGMENTS:
            continue
        candidate = segment
        break
    if not candidate:
        return None

    if candidate in {module, f"{module}s", "test", "tests", "__tests__", "spec", "specs", "index", "main"}:
        return None
    return candidate


def discover_module_features(code_dir: Path, module: str, module_paths: list[str]) -> dict[str, list[str]]:
    scoped_files = module_scoped_files(code_dir, module_paths)
    if not scoped_files:
        return {}

    grouped: dict[str, list[str]] = {}
    for relative_path in scoped_files:
        local_path = relative_within_module_root(relative_path, module_paths)
        candidate = feature_candidate_for_path(local_path, module)
        if not candidate:
            continue
        if not has_feature_code_evidence(code_dir / relative_path, candidate):
            continue
        grouped.setdefault(candidate, []).append(relative_path)

    feature_map: dict[str, list[str]] = {}
    ranked = sorted(grouped.items(), key=lambda item: (-len(set(item[1])), item[0]))
    for feature, paths in ranked:
        unique_paths = sorted(dict.fromkeys(paths))
        feature_map[feature] = unique_paths[:MAX_DISCOVERED_FILES]
        if len(feature_map) >= MAX_LISTED_ITEMS:
            break
    return feature_map


def discover_feature_map(code_dir: Path, module_map: dict[str, list[str]]) -> dict[str, dict[str, list[str]]]:
    feature_map: dict[str, dict[str, list[str]]] = {}
    for module, module_paths in sorted(module_map.items()):
        if module == "reviewer":
            continue
        feature_map[module] = discover_module_features(code_dir, module, module_paths)
    return feature_map


def shared_feature_modules(feature_map: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    shared: dict[str, list[str]] = {}
    for module, module_features in sorted(feature_map.items()):
        for feature in sorted(module_features):
            shared.setdefault(feature, []).append(module)
    return shared


def feature_key_signature(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        return {}
    signature: dict[str, tuple[str, ...]] = {}
    for raw_module, raw_features in value.items():
        module = str(raw_module).strip()
        if not module:
            continue
        if isinstance(raw_features, dict):
            features = tuple(sorted({str(raw_feature).strip() for raw_feature in raw_features if str(raw_feature).strip()}))
        else:
            features = ()
        signature[module] = features
    return dict(sorted(signature.items()))


def discover_prd_paths(project_root: Path) -> list[Path]:
    references_root = layout.references_dir(project_root)
    paths: list[Path] = []
    for filename in PRD_FILENAME_CANDIDATES:
        candidate = references_root / filename
        if candidate.exists() and candidate.is_file():
            paths.append(candidate)
    prd_dir = references_root / PRD_DIRNAME
    if prd_dir.exists() and prd_dir.is_dir():
        for candidate in sorted(prd_dir.rglob("*.md")):
            if candidate.is_file():
                paths.append(candidate)
    return sorted(dict.fromkeys(path.resolve() for path in paths))


def clean_markdown_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[`*_~]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def normalize_match_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[_/.-]+", " ", lowered)
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def match_tokens(value: str) -> set[str]:
    normalized = normalize_match_text(value)
    tokens = set(re.findall(r"[a-z0-9]{2,}", normalized))
    return {token for token in tokens if token not in MATCH_STOPWORDS}


def req_id_from_text(raw_text: str, fallback_key: str) -> str:
    match = REQ_ID_PATTERN.search(raw_text)
    if match:
        return match.group(1)
    digest = hashlib.sha1(f"{fallback_key}|{raw_text}".encode("utf-8")).hexdigest()[:8].upper()
    return f"AUTO-{digest}"


def parse_prd_requirements(project_root: Path) -> tuple[list[Path], list[RequirementCandidate]]:
    prd_paths = discover_prd_paths(project_root)
    if not prd_paths:
        return [], []

    candidates: list[RequirementCandidate] = []
    seen: set[tuple[str, str]] = set()

    for prd_path in prd_paths:
        relative = prd_path.relative_to(project_root).as_posix()
        try:
            lines = prd_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        active_heading = ""
        for line_number, line in enumerate(lines, start=1):
            heading_match = PRD_HEADING_PATTERN.match(line)
            if heading_match:
                heading_level = len(heading_match.group(1))
                heading_text = clean_markdown_text(heading_match.group(2))
                heading_normalized = normalize_match_text(heading_text)
                if heading_text:
                    active_heading = heading_text
                if heading_level >= 3 and len(heading_text) >= 8 and heading_normalized not in PRD_SECTION_IGNORE:
                    req_id = req_id_from_text(heading_text, f"{relative}:{line_number}")
                    record_key = (req_id, f"{relative}:{line_number}")
                    if record_key not in seen:
                        candidates.append(
                            RequirementCandidate(
                                req_id=req_id,
                                title=heading_text[:120],
                                text=heading_text,
                                prd_ref=f"{relative}:{line_number}",
                            )
                        )
                        seen.add(record_key)
                continue

            list_match = PRD_LIST_PATTERN.match(line)
            line_text = clean_markdown_text(list_match.group(1) if list_match else line)
            if len(line_text) < 8:
                continue

            if not list_match and not REQ_ID_PATTERN.search(line_text):
                continue

            merged_text = f"{active_heading}; {line_text}" if active_heading else line_text
            req_id = req_id_from_text(line_text, f"{relative}:{line_number}")
            record_key = (req_id, f"{relative}:{line_number}")
            if record_key in seen:
                continue
            candidates.append(
                RequirementCandidate(
                    req_id=req_id,
                    title=line_text[:120],
                    text=merged_text,
                    prd_ref=f"{relative}:{line_number}",
                )
            )
            seen.add(record_key)

    return prd_paths, candidates


def summarize_refs(refs: list[str], limit: int = 3) -> str:
    if not refs:
        return "-"
    if len(refs) <= limit:
        return ", ".join(refs)
    return ", ".join(refs[:limit]) + f", +{len(refs) - limit} more"


def format_table_cell(value: str) -> str:
    if not value:
        return "-"
    return value.replace("|", "\\|")


def score_requirement_feature(req_text: str, req_tokens: set[str], profile: dict[str, object]) -> float:
    normalized_text = normalize_match_text(req_text)
    score = 0.0
    feature_name = str(profile.get("feature_norm") or "")
    module_name = str(profile.get("module_norm") or "")
    profile_tokens = set(profile.get("tokens") or set())

    if feature_name and feature_name in normalized_text:
        score += 0.55
    elif feature_name:
        feature_parts = [part for part in feature_name.split() if part]
        if feature_parts and all(part in normalized_text for part in feature_parts):
            score += 0.35

    if module_name and module_name in normalized_text:
        score += 0.1

    if req_tokens and profile_tokens:
        overlap = req_tokens & profile_tokens
        if overlap:
            score += min(0.35, len(overlap) / max(len(req_tokens), 1) * 0.6)

    return min(score, 1.0)


def build_feature_profiles(
    code_dir: Path,
    feature_map: dict[str, dict[str, list[str]]],
) -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    for module, features in sorted(feature_map.items()):
        for feature, paths in sorted(features.items()):
            code_refs = limited_paths(line_refs_for_paths(code_dir, paths), 8)
            test_paths = [
                path
                for path in paths
                if any(token in path.lower() for token in ("test", "spec", "__tests__", "playwright", "cypress"))
            ]
            test_refs = limited_paths(line_refs_for_paths(code_dir, test_paths), 6)
            tokens = set()
            tokens.update(match_tokens(module))
            tokens.update(match_tokens(feature.replace("-", " ").replace("_", " ")))
            for path in paths:
                for segment in PurePosixPath(path).parts:
                    tokens.update(match_tokens(segment))
            profiles.append(
                {
                    "module": module,
                    "module_norm": normalize_match_text(module),
                    "feature": feature,
                    "feature_norm": normalize_match_text(feature.replace("-", " ").replace("_", " ")),
                    "tokens": tokens,
                    "code_refs": code_refs,
                    "test_refs": test_refs,
                }
            )
    return profiles


def generate_requirements_map_rows(
    requirements: list[RequirementCandidate],
    profiles: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for requirement in requirements:
        req_tokens = match_tokens(requirement.text)
        scored: list[tuple[float, dict[str, object]]] = []
        for profile in profiles:
            score = score_requirement_feature(requirement.text, req_tokens, profile)
            if score > 0:
                scored.append((score, profile))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("module")), str(item[1].get("feature"))))

        selected: list[tuple[float, dict[str, object]]] = []
        top_score = 0.0
        if scored:
            top_score = scored[0][0]
            if top_score >= 0.2:
                selected.append(scored[0])
                if len(scored) > 1 and scored[1][0] >= max(0.2, top_score - 0.08):
                    selected.append(scored[1])

        features = [str(item[1]["feature"]) for item in selected]
        modules = sorted({str(item[1]["module"]) for item in selected})
        code_refs = limited_paths(
            list(
                dict.fromkeys(
                    ref
                    for _, profile in selected
                    for ref in profile.get("code_refs") or []
                )
            ),
            8,
        )
        test_refs = limited_paths(
            list(
                dict.fromkeys(
                    ref
                    for _, profile in selected
                    for ref in profile.get("test_refs") or []
                )
            ),
            6,
        )

        status = "unresolved"
        if top_score >= 0.55:
            status = "mapped"
        elif top_score >= 0.2:
            status = "partial"

        rows.append(
            {
                "req_id": requirement.req_id,
                "prd_ref": requirement.prd_ref,
                "title": requirement.title,
                "feature_keys": features,
                "modules": modules,
                "code_refs": code_refs,
                "test_refs": test_refs,
                "confidence": round(top_score, 3),
                "status": status,
            }
        )
    return rows


def derive_requirement_rows(
    project_root: Path,
    code_dir: Path,
    feature_map: dict[str, dict[str, list[str]]],
) -> tuple[list[Path], list[RequirementCandidate], list[dict[str, object]]]:
    prd_paths, requirements = parse_prd_requirements(project_root)
    profiles = build_feature_profiles(code_dir, feature_map)
    rows = generate_requirements_map_rows(requirements, profiles)
    return prd_paths, requirements, rows


def safe_read_lines(file_path: Path) -> list[str]:
    try:
        return file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []


def extract_domain_states_from_lines(lines: list[str]) -> list[str]:
    states: set[str] = set()
    for line in lines:
        lowered = line.lower()
        if "status" not in lowered and "state" not in lowered and "phase" not in lowered:
            continue
        for token in DOMAIN_STATE_PATTERN.findall(line):
            normalized = normalize_feature_token(token)
            if not normalized:
                continue
            if normalized in DOMAIN_ENTITY_SKIP_TOKENS:
                continue
            if len(normalized) < 3:
                continue
            states.add(normalized)
            if len(states) >= MAX_LISTED_ITEMS:
                return sorted(states)
    return sorted(states)


def extract_domain_rules_from_lines(lines: list[str]) -> list[str]:
    rules: list[str] = []
    for line in lines:
        normalized = " ".join(line.strip().split())
        if len(normalized) < 10:
            continue
        lowered = normalized.lower()
        if not any(keyword in lowered for keyword in DOMAIN_RULE_KEYWORDS):
            continue
        cleaned = clean_markdown_text(normalized)
        if not cleaned:
            continue
        if len(cleaned) > 140:
            cleaned = cleaned[:137] + "..."
        rules.append(cleaned)
        if len(rules) >= MAX_LISTED_ITEMS:
            break
    return list(dict.fromkeys(rules))


def infer_entity_label(module: str, feature: str, feature_paths: list[str]) -> str:
    prioritized_segments: list[str] = []
    for path in feature_paths:
        parts = PurePosixPath(path).parts[:-1]
        for segment in parts:
            token = normalize_feature_token(segment)
            if not token:
                continue
            if token in DOMAIN_ENTITY_SKIP_TOKENS:
                continue
            if token in {module, feature}:
                continue
            prioritized_segments.append(token)
    if prioritized_segments:
        return sorted(dict.fromkeys(prioritized_segments))[0]
    return feature


def generate_domain_model_rows(
    code_dir: Path,
    feature_map: dict[str, dict[str, list[str]]],
    requirement_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    requirement_index: dict[tuple[str, str], set[str]] = {}
    for row in requirement_rows:
        req_id = str(row.get("req_id") or "").strip()
        if not req_id:
            continue
        feature_keys = [str(item).strip() for item in row.get("feature_keys") or [] if str(item).strip()]
        modules = [str(item).strip() for item in row.get("modules") or [] if str(item).strip()]
        for module in modules:
            for feature in feature_keys:
                requirement_index.setdefault((module, feature), set()).add(req_id)

    shared_features = shared_feature_modules(feature_map)
    rows: list[dict[str, object]] = []
    for module, features in sorted(feature_map.items()):
        for feature, feature_paths in sorted(features.items()):
            code_refs = limited_paths(line_refs_for_paths(code_dir, feature_paths), 8)
            test_paths = [
                path
                for path in feature_paths
                if any(token in path.lower() for token in ("test", "spec", "__tests__", "playwright", "cypress"))
            ]
            test_refs = limited_paths(line_refs_for_paths(code_dir, test_paths), 6)
            linked_requirements = sorted(requirement_index.get((module, feature), set()))

            lines: list[str] = []
            for relative in feature_paths[:MAX_DISCOVERED_FILES]:
                lines.extend(safe_read_lines(code_dir / relative))

            states = extract_domain_states_from_lines(lines)
            rules = extract_domain_rules_from_lines(lines)
            entity = infer_entity_label(module, feature, feature_paths)
            relations = [f"shared-feature-with:{item}" for item in shared_features.get(feature, []) if item != module]
            relations = sorted(dict.fromkeys(relations))

            confidence = 0.0
            if linked_requirements:
                confidence += 0.25
            if states:
                confidence += 0.3
            if rules:
                confidence += 0.3
            if test_refs:
                confidence += 0.15
            confidence = round(min(confidence, 1.0), 3)

            status = "unresolved"
            if confidence >= 0.6:
                status = "mapped"
            elif confidence >= 0.25:
                status = "partial"

            rows.append(
                {
                    "entity": entity,
                    "module": module,
                    "feature_key": feature,
                    "linked_requirements": linked_requirements,
                    "states": states,
                    "rules": rules,
                    "relations": relations,
                    "code_refs": code_refs,
                    "test_refs": test_refs,
                    "confidence": confidence,
                    "status": status,
                }
            )
    return rows


def generate_domain_model_block(
    project_root: Path,
    code_dir: Path,
    feature_map: dict[str, dict[str, list[str]]],
    prd_paths: list[Path],
    requirement_rows: list[dict[str, object]],
) -> str:
    domain_rows = generate_domain_model_rows(code_dir, feature_map, requirement_rows)

    mapped = len([row for row in domain_rows if row["status"] == "mapped"])
    partial = len([row for row in domain_rows if row["status"] == "partial"])
    unresolved = len([row for row in domain_rows if row["status"] == "unresolved"])

    lines = [
        "## Generated Domain Model Snapshot",
        "- Captures inferred business entities, states, rules, and requirement links per feature.",
        "- Content inside this AUTO block is managed by `scripts/sync_context_project.py`.",
    ]
    if prd_paths:
        lines.extend(
            [
                "- PRD sources used for requirement linking:",
                *format_list(
                    [path.relative_to(project_root).as_posix() for path in prd_paths],
                    "No PRD source files discovered.",
                    quote=False,
                ),
            ]
        )
    else:
        lines.append("- PRD sources: none found; linked requirements may stay empty.")

    if not domain_rows:
        lines.append("- No feature-level domain rows were inferred automatically.")
        return "\n".join(lines)

    lines.extend(
        [
            f"- Domain rows: `{len(domain_rows)}` (`mapped={mapped}`, `partial={partial}`, `unresolved={unresolved}`).",
            "",
            "### Machine Readable JSON",
            "```json",
            json.dumps(domain_rows, indent=2, ensure_ascii=False),
            "```",
            "",
            "### Domain Table",
            "| entity | module | feature_key | linked_requirements | states | rules | confidence | status |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in domain_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    format_table_cell(str(row["entity"])),
                    format_table_cell(str(row["module"])),
                    format_table_cell(str(row["feature_key"])),
                    format_table_cell(", ".join(row["linked_requirements"]) if row["linked_requirements"] else "-"),
                    format_table_cell(", ".join(row["states"]) if row["states"] else "-"),
                    format_table_cell(", ".join(row["rules"][:2]) if row["rules"] else "-"),
                    format_table_cell(f"{float(row['confidence']):.3f}"),
                    format_table_cell(str(row["status"])),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def generate_requirements_map_block(
    project_root: Path,
    prd_paths: list[Path],
    requirements: list[RequirementCandidate],
    rows: list[dict[str, object]],
) -> str:
    lines = [
        "## Generated Requirements Trace Map",
        "- Links PRD requirements to inferred features, modules, and code/test references.",
        "- Content inside this AUTO block is managed by `scripts/sync_context_project.py`.",
    ]

    if not prd_paths:
        lines.extend(
            [
                "- No PRD docs found under `references/prd.md`, `references/requirements.md`, or `references/prd/*.md`.",
                "- Add PRD docs there and rerun sync to build the trace map.",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            "- PRD sources:",
            *format_list(
                [path.relative_to(project_root).as_posix() for path in prd_paths],
                "No PRD source files discovered.",
                quote=False,
            ),
        ]
    )

    if not requirements:
        lines.append("- No requirement candidates were extracted from the current PRD docs.")
        return "\n".join(lines)

    mapped = len([row for row in rows if row["status"] == "mapped"])
    partial = len([row for row in rows if row["status"] == "partial"])
    unresolved = len([row for row in rows if row["status"] == "unresolved"])

    lines.extend(
        [
            f"- Requirement candidates: `{len(rows)}` (`mapped={mapped}`, `partial={partial}`, `unresolved={unresolved}`).",
            "",
            "### Machine Readable JSON",
            "```json",
            json.dumps(rows, indent=2, ensure_ascii=False),
            "```",
            "",
            "### Trace Table",
            "| req_id | prd_ref | feature_keys | modules | code_refs | test_refs | confidence | status |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    format_table_cell(str(row["req_id"])),
                    format_table_cell(str(row["prd_ref"])),
                    format_table_cell(", ".join(row["feature_keys"]) if row["feature_keys"] else "-"),
                    format_table_cell(", ".join(row["modules"]) if row["modules"] else "-"),
                    format_table_cell(summarize_refs(row["code_refs"])),
                    format_table_cell(summarize_refs(row["test_refs"])),
                    format_table_cell(f"{float(row['confidence']):.3f}"),
                    format_table_cell(str(row["status"])),
                ]
            )
            + " |"
        )

    return "\n".join(lines)
