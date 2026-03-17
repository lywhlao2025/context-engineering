#!/usr/bin/env python3
"""Validate harness-contract markers in generated agent AUTO blocks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import context_layout as layout
from sync_context_project import (
    HARNESS_REQUIRED_LOOP_STEPS,
    HARNESS_REQUIRED_MARKERS_BY_BLOCK,
)
from sync_context_scan import extract_auto_block, read_text


def expected_agent_targets(project_root: Path) -> list[tuple[Path, str]]:
    agents_root = layout.agents_dir(project_root)
    if not agents_root.exists():
        return []
    targets: list[tuple[Path, str]] = []
    for agent_dir in sorted(path for path in agents_root.iterdir() if path.is_dir()):
        targets.extend(
            [
                (layout.agent_readme_path(project_root, agent_dir.name), "agent-readme"),
                (layout.agent_tools_path(project_root, agent_dir.name), "agent-tools"),
                (layout.agent_memory_path(project_root, agent_dir.name), "agent-memory"),
            ]
        )
    return targets


def validate_project(project_root: Path) -> list[str]:
    violations: list[str] = []
    for file_path, block_name in expected_agent_targets(project_root):
        required_markers = HARNESS_REQUIRED_MARKERS_BY_BLOCK.get(block_name)
        if not required_markers:
            continue
        if not file_path.exists():
            violations.append(f"{file_path} [{block_name}] missing file")
            continue
        block = extract_auto_block(read_text(file_path), block_name)
        if block is None:
            violations.append(f"{file_path} [{block_name}] missing AUTO block")
            continue
        for marker in required_markers:
            if marker not in block:
                violations.append(f"{file_path} [{block_name}] missing required marker: {marker}")
        if block_name == "agent-readme":
            for step in HARNESS_REQUIRED_LOOP_STEPS:
                if step not in block:
                    violations.append(f"{file_path} [{block_name}] missing required loop step: {step}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate harness-contract markers for generated agent docs.")
    parser.add_argument(
        "--project-root",
        required=True,
        help="Absolute path to <target_root>/projects/<project_name>.",
    )
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    violations = validate_project(project_root)
    if violations:
        print("Harness contract validation: FAIL")
        for item in violations:
            print(f"- {item}")
        return 1
    print("Harness contract validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
