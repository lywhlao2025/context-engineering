#!/usr/bin/env python3
"""Shared layout constants and path helpers for context projects."""

from __future__ import annotations

from pathlib import Path


DEFAULT_TARGET_ROOT = Path.home() / "clawDir" / "team"
DEFAULT_TARGET_ROOT_DISPLAY = "~/clawDir/team"

ROOT_README_FILENAME = "readme.md"
PROJECTS_DIRNAME = "projects"
PROJECTS_INDEX_FILENAME = "projects.md"

PROJECT_README_FILENAME = "readme.md"
GOALS_FILENAME = "goals.md"
SKILL_FILENAME = "skill.md"
PROJECT_STATUS_FILENAME = "project_status.md"
DECISIONS_FILENAME = "decisions.md"

AGENTS_DIRNAME = "agents"
AGENTS_INDEX_FILENAME = "agents.md"
AGENT_README_FILENAME = "README.md"
AGENT_TOOLS_FILENAME = "tools.md"
AGENT_MEMORY_FILENAME = "memory.md"
AGENT_DECISIONS_FILENAME = "decisions.jsonl"
AGENT_FAILS_FILENAME = "fails.jsonl"

MODULES_DIRNAME = "modules"
MODULE_OVERVIEW_FILENAME = "README.md"

REFERENCES_DIRNAME = "references"
ENTRYPOINTS_FILENAME = "entrypoints.md"
FEATURE_MAP_FILENAME = "feature-map.md"
REQUIREMENTS_MAP_FILENAME = "requirements-map.md"
DOMAIN_MODEL_FILENAME = "domain-model.md"

SOURCES_DIRNAME = "sources"

SYNC_DIRNAME = ".context-sync"
STATE_FILENAME = "state.json"


def projects_dir(target_root: Path) -> Path:
    return target_root / PROJECTS_DIRNAME


def team_readme_path(target_root: Path) -> Path:
    return target_root / ROOT_README_FILENAME


def projects_index_path(target_root: Path) -> Path:
    return projects_dir(target_root) / PROJECTS_INDEX_FILENAME


def project_root(target_root: Path, project_name: str) -> Path:
    return projects_dir(target_root) / project_name


def project_readme_path(project_root: Path) -> Path:
    return project_root / PROJECT_README_FILENAME


def goals_path(project_root: Path) -> Path:
    return project_root / GOALS_FILENAME


def skill_path(project_root: Path) -> Path:
    return project_root / SKILL_FILENAME


def project_status_path(project_root: Path) -> Path:
    return project_root / PROJECT_STATUS_FILENAME


def decisions_path(project_root: Path) -> Path:
    return project_root / DECISIONS_FILENAME


def agents_dir(project_root: Path) -> Path:
    return project_root / AGENTS_DIRNAME


def agents_index_path(project_root: Path) -> Path:
    return agents_dir(project_root) / AGENTS_INDEX_FILENAME


def agent_dir(project_root: Path, agent: str) -> Path:
    return agents_dir(project_root) / agent


def agent_readme_path(project_root: Path, agent: str) -> Path:
    return agent_dir(project_root, agent) / AGENT_README_FILENAME


def agent_tools_path(project_root: Path, agent: str) -> Path:
    return agent_dir(project_root, agent) / AGENT_TOOLS_FILENAME


def agent_memory_path(project_root: Path, agent: str) -> Path:
    return agent_dir(project_root, agent) / AGENT_MEMORY_FILENAME


def agent_decisions_path(project_root: Path, agent: str) -> Path:
    return agent_dir(project_root, agent) / AGENT_DECISIONS_FILENAME


def agent_fails_path(project_root: Path, agent: str) -> Path:
    return agent_dir(project_root, agent) / AGENT_FAILS_FILENAME


def modules_dir(project_root: Path) -> Path:
    return project_root / MODULES_DIRNAME


def modules_index_path(project_root: Path) -> Path:
    return modules_dir(project_root) / MODULE_OVERVIEW_FILENAME


def module_dir(project_root: Path, module: str) -> Path:
    return modules_dir(project_root) / module


def module_detail_filename(module: str) -> str:
    return f"{module}.md"


def module_overview_path(project_root: Path, module: str) -> Path:
    return module_dir(project_root, module) / MODULE_OVERVIEW_FILENAME


def module_detail_path(project_root: Path, module: str) -> Path:
    return module_dir(project_root, module) / module_detail_filename(module)


def module_feature_filename(feature: str) -> str:
    return f"{feature}.md"


def module_feature_path(project_root: Path, module: str, feature: str) -> Path:
    return module_dir(project_root, module) / module_feature_filename(feature)


def references_dir(project_root: Path) -> Path:
    return project_root / REFERENCES_DIRNAME


def entrypoints_path(project_root: Path) -> Path:
    return references_dir(project_root) / ENTRYPOINTS_FILENAME


def feature_map_path(project_root: Path) -> Path:
    return references_dir(project_root) / FEATURE_MAP_FILENAME


def requirements_map_path(project_root: Path) -> Path:
    return references_dir(project_root) / REQUIREMENTS_MAP_FILENAME


def domain_model_path(project_root: Path) -> Path:
    return references_dir(project_root) / DOMAIN_MODEL_FILENAME


def sources_dir(target_root: Path) -> Path:
    return target_root / SOURCES_DIRNAME


def managed_source_path(target_root: Path, project_name: str) -> Path:
    return sources_dir(target_root) / project_name


def sync_state_dir(project_root: Path) -> Path:
    return project_root / SYNC_DIRNAME


def sync_state_path(project_root: Path) -> Path:
    return sync_state_dir(project_root) / STATE_FILENAME


def project_index_entry(project_name: str) -> str:
    return f"- {project_name} → {PROJECTS_DIRNAME}/{project_name}/{PROJECT_README_FILENAME}"


def relative_module_overview(module: str) -> str:
    return f"{MODULES_DIRNAME}/{module}/{MODULE_OVERVIEW_FILENAME}"


def relative_module_detail(module: str) -> str:
    return f"{MODULES_DIRNAME}/{module}/{module_detail_filename(module)}"


def relative_module_feature(module: str, feature: str) -> str:
    return f"{MODULES_DIRNAME}/{module}/{module_feature_filename(feature)}"
