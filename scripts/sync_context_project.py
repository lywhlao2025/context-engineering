#!/usr/bin/env python3
"""Synchronize a team-style project context directory.

This file contains orchestration and CLI flow.
Scanning/mapping logic lives in `sync_context_scan.py`.
Block generation logic lives in `sync_context_generation.py`.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from sync_context_generation import *  # noqa: F401,F403
from sync_context_scan import *  # noqa: F401,F403


def build_updates(
    project_root: Path,
    project: str,
    code_dir: Path,
    modules: list[str],
    module_map: dict[str, list[str]],
    feature_map: dict[str, dict[str, list[str]]],
    global_paths: list[str],
    mode: SyncMode,
    manifests: list[str],
    repo_root: Path | None,
    branch: str | None,
    head: str | None,
    changed_paths: list[str],
    review_plan: ReviewPlan,
    review_record: ReviewRecord,
    multi_git: dict[str, dict[str, str | None]] | None = None,
) -> list[tuple[Path, str, str]]:
    updates: list[tuple[Path, str, str]] = []
    module_profiles = {
        module: build_module_profile(module, code_dir, module_map.get(module, []))
        for module in modules
        if module != "reviewer"
    }
    feature_profiles = {
        module: {
            feature: build_feature_profile(module, feature, code_dir, module_map.get(module, []), paths)
            for feature, paths in sorted(feature_map.get(module, {}).items())
        }
        for module in modules
        if module != "reviewer"
    }
    prd_paths, requirements, requirement_rows = derive_requirement_rows(project_root, code_dir, feature_map)
    if mode.update_global or mode.name == "full":
        updates.append(
            (
                layout.skill_path(project_root),
                "l1",
                generate_skill_block(project, code_dir, modules, module_map, feature_map, global_paths, mode, manifests, repo_root, branch, head, multi_git),
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
                layout.feature_map_path(project_root),
                "feature-map",
                generate_feature_map_block(feature_map),
            )
        )
        updates.append(
            (
                layout.modules_index_path(project_root),
                "module-index",
                generate_modules_index_block(modules, module_map, feature_map),
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
    feature_targets = module_feature_targets(module_targets, feature_map)

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
        module_features = feature_map.get(module, {})
        profile = module_profiles.get(module) or build_module_profile(module, code_dir, module_paths)
        updates.append(
            (
                layout.module_overview_path(project_root, module),
                "module-overview",
                generate_module_overview_block(module, profile, module_features),
            )
        )
        updates.append(
            (
                layout.module_detail_path(project_root, module),
                "module-detail",
                generate_module_detail_block(module, module_paths, profile, module_map, module_features),
            )
        )
        for feature in feature_targets.get(module, []):
            feature_profile = feature_profiles.get(module, {}).get(feature) or build_feature_profile(
                module,
                feature,
                code_dir,
                module_paths,
                module_features.get(feature, []),
            )
            updates.append(
                (
                    layout.module_feature_path(project_root, module, feature),
                    "feature-detail",
                    generate_feature_detail_block(module, feature, feature_profile),
                )
            )

    updates.append(
        (
            layout.requirements_map_path(project_root),
            "requirements-map",
            generate_requirements_map_block(project_root, prd_paths, requirements, requirement_rows),
        )
    )
    updates.append(
        (
            layout.domain_model_path(project_root),
            "domain-model",
            generate_domain_model_block(project_root, code_dir, feature_map, prd_paths, requirement_rows),
        )
    )

    updates.append(
        (
            layout.project_status_path(project_root),
            "sync-status",
            generate_status_block(mode, review_plan, review_record, repo_root, branch, head, changed_paths, multi_git),
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
    has_git: bool,
    current_state: dict,
    module_map: dict[str, list[str]],
    feature_map: dict[str, dict[str, list[str]]],
    changed_paths: list[str],
    changed_modules: list[str],
    update_global: bool,
    unmatched_changes: list[str],
    sync_base_issue: str | None,
) -> SyncMode:
    if not has_git:
        return SyncMode("full", [], True, "Non-Git project; full sync only.")
    if not current_state:
        return SyncMode("full", [], True, "No previous sync state found.")
    if current_state.get("state_version") != STATE_VERSION:
        return SyncMode("full", [], True, "Sync state version changed.")
    if current_state.get("module_map") != module_map:
        return SyncMode("full", [], True, "Module map changed since the last sync.")
    if feature_key_signature(current_state.get("feature_map")) != feature_key_signature(feature_map):
        return SyncMode("full", [], True, "Feature key set changed since the last sync.")
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
    has_git: bool,
    previous_state: dict,
    module_map: dict[str, list[str]],
    feature_map: dict[str, dict[str, list[str]]],
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

    if not has_git:
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

    if feature_key_signature(previous_state.get("feature_map")) != feature_key_signature(feature_map):
        return ReviewPlan(
            "broad-source-review",
            "Feature key set changed since the last sync.",
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
    scoped_features = module_feature_targets(scoped_modules, feature_map)
    scope_mismatch = detect_context_scope_mismatch(
        project_root,
        scoped_modules,
        scoped_agents,
        scoped_features,
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
    feature_map: dict[str, dict[str, list[str]]],
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
        "feature_map": feature_map,
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

    multi_sources = load_multi_sources(Path(args.code_dir).expanduser().resolve()) if args.code_dir else None

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

    if multi_sources:
        ensure_multi_symlinks(code_dir, multi_sources, allow_mutation=not args.dry_run)

    if not args.dry_run:
        run_init_scaffold(args.project, code_dir, target_root)

    if multi_sources:
        modules = infer_modules_from_sources(multi_sources)
        module_map, global_paths = build_module_map_from_sources(multi_sources)
        feature_map = discover_feature_map(code_dir, module_map)
    else:
        modules = infer_modules(code_dir)
        module_map, global_paths, _ = discover_module_map(code_dir, modules)
        feature_map = discover_feature_map(code_dir, module_map)
    git_repo_root = is_git_repo(code_dir)
    validate_source_identity(previous_state, source, git_repo_root)

    multi_git_meta = None
    has_git = bool(git_repo_root)
    multi_mode = bool(multi_sources)
    multi_git = None
    if multi_sources:
        multi_git_meta = {}
        for source_item in multi_sources:
            repo_root = is_git_repo(source_item["path"])
            has_git = has_git or bool(repo_root)
            branch = None
            head = None
            if repo_root:
                head = run_command(["git", "-C", str(repo_root), "rev-parse", "HEAD"])
                branch = run_command(["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"])
            multi_git_meta[source_item["name"]] = {
                "repo_root": str(repo_root) if repo_root else None,
                "branch": branch,
                "head": head,
            }
        multi_git = multi_git_meta

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
    elif multi_sources:
        # Aggregate changed paths from each source repo if available
        changed_paths = []
        multi_sync_base_issues: list[str] = []
        for source_item in multi_sources:
            repo_root = is_git_repo(source_item["path"])
            if not repo_root:
                continue
            source_name = source_item["name"]
            source_last_head = multi_source_last_synced_head(previous_state, source_name)
            src_changed, src_head, src_branch, src_issue = git_changed_files(
                repo_root,
                source_item["path"],
                source_last_head,
                bool(previous_state),
            )
            if src_issue:
                multi_sync_base_issues.append(f"Source `{source_name}`: {src_issue}")
            prefix = source_name.strip("/")
            changed_paths.extend([f"{prefix}/{path}" for path in src_changed])
        changed_paths = sorted(dict.fromkeys(changed_paths))
        if multi_sync_base_issues:
            sync_base_issue = "; ".join(multi_sync_base_issues)

    changed_modules: list[str] = []
    update_global = True
    unmatched_changes: list[str] = []
    if has_git and previous_state.get("state_version") == STATE_VERSION:
        changed_modules, update_global, unmatched_changes = map_changed_paths(changed_paths, module_map, global_paths)

    mode = determine_sync_mode(
        has_git,
        previous_state,
        module_map,
        feature_map,
        changed_paths,
        changed_modules,
        update_global,
        unmatched_changes,
        sync_base_issue,
    )

    if has_git and mode.name == "incremental" and not changed_paths:
        mode = SyncMode("noop", [], False, "No code changes detected since the last successful sync.")

    review_plan = determine_review_plan(
        project_root,
        code_dir,
        has_git,
        previous_state,
        module_map,
        feature_map,
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
        feature_map,
        global_paths,
        mode if mode.name != "noop" else SyncMode("noop", [], False, mode.reason),
        manifests,
        git_repo_root,
        branch,
        current_head,
        changed_paths,
        review_plan,
        review_record,
        multi_git_meta,
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
        feature_map,
        global_paths,
        generated_hashes,
        mode,
        review_plan,
        review_record,
    )
    if multi_mode:
        next_state["source_mode"] = "multi"
        next_state["multi_sources"] = {
            src["name"]: {
                "code_dir": str(src["path"]),
                "repo_root": (multi_git or {}).get(src["name"], {}).get("repo_root"),
                "last_synced_head": (multi_git or {}).get(src["name"], {}).get("head"),
                "last_synced_branch": (multi_git or {}).get(src["name"], {}).get("branch"),
                "modules": src.get("modules"),
            }
            for src in multi_sources
        }
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
