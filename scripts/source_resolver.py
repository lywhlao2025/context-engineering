#!/usr/bin/env python3
"""Resolve local or Git-backed code sources for context analysis."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import context_layout as layout


MANAGED_BRANCHES = ("main", "master")


class SourceResolutionError(RuntimeError):
    """Raised when a code source cannot be prepared safely."""


@dataclass(frozen=True)
class ResolvedSource:
    code_dir: Path
    source_type: str
    git_url: str | None = None
    managed: bool = False


def _run_command(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SourceResolutionError(result.stderr.strip() or "Command failed: " + " ".join(args))
    return result.stdout.strip()


def _try_command(args: list[str], cwd: Path | None = None) -> str | None:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _command_succeeds(args: list[str], cwd: Path | None = None) -> bool:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    return result.returncode == 0


def normalize_source_locator(value: str) -> str:
    candidate = Path(value).expanduser()
    if candidate.exists():
        return str(candidate.resolve())
    return value.rstrip("/")


def _ensure_clean_checkout(code_dir: Path) -> None:
    status_output = _run_command(
        ["git", "-C", str(code_dir), "status", "--porcelain", "--untracked-files=all"]
    )
    if status_output:
        raise SourceResolutionError(
            f"Managed source checkout is dirty: `{code_dir}`. "
            "Clean or remove it before refreshing from Git."
        )


def _detect_managed_branch(code_dir: Path) -> str:
    origin_head = _try_command(["git", "-C", str(code_dir), "symbolic-ref", "refs/remotes/origin/HEAD"])
    if origin_head and origin_head.startswith("refs/remotes/origin/"):
        branch = origin_head.removeprefix("refs/remotes/origin/")
        if branch in MANAGED_BRANCHES:
            return branch

    for branch in MANAGED_BRANCHES:
        if _command_succeeds(["git", "-C", str(code_dir), "show-ref", "--verify", f"refs/remotes/origin/{branch}"]):
            return branch
        if _command_succeeds(["git", "-C", str(code_dir), "show-ref", "--verify", f"refs/heads/{branch}"]):
            return branch

    raise SourceResolutionError(
        "Managed Git source requires a `main` or `master` branch to analyze."
    )


def _refresh_managed_clone(code_dir: Path) -> None:
    _ensure_clean_checkout(code_dir)
    _run_command(["git", "-C", str(code_dir), "fetch", "--prune", "origin"])

    branch = _detect_managed_branch(code_dir)
    current_branch = _run_command(["git", "-C", str(code_dir), "rev-parse", "--abbrev-ref", "HEAD"])

    if current_branch != branch:
        if _command_succeeds(["git", "-C", str(code_dir), "show-ref", "--verify", f"refs/heads/{branch}"]):
            _run_command(["git", "-C", str(code_dir), "checkout", branch])
        else:
            _run_command(["git", "-C", str(code_dir), "checkout", "-b", branch, f"origin/{branch}"])

    if _command_succeeds(["git", "-C", str(code_dir), "show-ref", "--verify", f"refs/remotes/origin/{branch}"]):
        _run_command(["git", "-C", str(code_dir), "merge", "--ff-only", f"origin/{branch}"])


def _prepare_managed_clone(project_name: str, target_root: Path, git_url: str, allow_mutation: bool) -> Path:
    managed_dir = layout.managed_source_path(target_root, project_name)
    normalized_target = normalize_source_locator(git_url)

    if not managed_dir.exists():
        if not allow_mutation:
            raise SourceResolutionError(
                "Dry-run with `--git-url` requires an existing managed checkout at "
                f"`{managed_dir}` because dry-run will not clone or fetch sources."
            )
        managed_dir.parent.mkdir(parents=True, exist_ok=True)
        _run_command(["git", "clone", git_url, str(managed_dir)])
        if allow_mutation:
            _refresh_managed_clone(managed_dir)
        return managed_dir

    if not (managed_dir / ".git").exists():
        raise SourceResolutionError(
            f"Managed source path exists but is not a Git checkout: `{managed_dir}`."
        )

    existing_remote = _try_command(["git", "-C", str(managed_dir), "remote", "get-url", "origin"])
    if not existing_remote:
        raise SourceResolutionError(
            f"Managed source checkout is missing the `origin` remote: `{managed_dir}`."
        )

    if normalize_source_locator(existing_remote) != normalized_target:
        raise SourceResolutionError(
            "Managed source checkout already exists with a different origin remote. "
            f"Expected `{git_url}`, found `{existing_remote}`."
        )

    if allow_mutation:
        _refresh_managed_clone(managed_dir)
    return managed_dir


def resolve_code_source(
    project_name: str,
    target_root: Path,
    *,
    code_dir: str | None,
    git_url: str | None,
    allow_mutation: bool = True,
) -> ResolvedSource:
    if bool(code_dir) == bool(git_url):
        raise SourceResolutionError("Provide exactly one of `--code-dir` or `--git-url`.")

    if code_dir:
        resolved = Path(code_dir).expanduser().resolve()
        if not resolved.exists():
            raise SourceResolutionError(f"Code directory does not exist: {resolved}")
        return ResolvedSource(code_dir=resolved, source_type="local", managed=False)

    assert git_url is not None
    managed_dir = _prepare_managed_clone(project_name, target_root, git_url, allow_mutation)
    return ResolvedSource(
        code_dir=managed_dir,
        source_type="git",
        git_url=git_url,
        managed=True,
    )
