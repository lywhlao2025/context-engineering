from __future__ import annotations

"""Block/profile generators for context sync."""

from sync_context_scan import *  # noqa: F401,F403


def display_review_outcome(value: str) -> str:
    return value.replace("_", " ")


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


BACKEND_CORE_FLOW_KEYWORDS = {
    "http": (
        "@requestmapping",
        "@getmapping",
        "@postmapping",
        "@putmapping",
        "@deletemapping",
        "@restcontroller",
        "@controller",
        "@router.",
        "@app.route",
        "express.router",
        "route(",
        "controller",
        "handler",
        "http",
        "api",
    ),
    "rpc": (
        "thrift",
        ".thrift",
        "grpc",
        ".proto",
        "protobuf",
        "idl",
        "rpc",
        "processor",
        "stub",
        "transport",
        "serviceclient",
    ),
    "job": (
        "@scheduled",
        "cron",
        "scheduler",
        "job",
        "queue",
        "worker",
        "consumer",
        "listener",
        "task",
        "pipeline",
    ),
    "service": (
        "@service",
        "service",
        "usecase",
        "domain",
        "manager",
        "orchestr",
    ),
    "data": (
        "@repository",
        "repository",
        "dao",
        "mapper",
        "sql",
        "jdbc",
        "mybatis",
        "jpa",
        "prisma",
        "orm",
        "schema",
        "migration",
        "redis",
    ),
    "output": (
        "response",
        "stream",
        "event",
        "publisher",
        "producer",
        "send",
        "emit",
        "return",
        "webhook",
        "notification",
    ),
}


def backend_flow_hits(relative_path: str, lines: list[str]) -> set[str]:
    probe = normalize_match_text(relative_path + "\n" + "\n".join(lines[:220]))
    hits: set[str] = set()
    for flow_type, keywords in BACKEND_CORE_FLOW_KEYWORDS.items():
        for keyword in keywords:
            normalized_keyword = normalize_match_text(keyword)
            if normalized_keyword and normalized_keyword in probe:
                hits.add(flow_type)
                break
    return hits


def collect_backend_flow_refs(code_dir: Path, module_paths: list[str]) -> dict[str, list[str]]:
    scoped_files = module_scoped_files(code_dir, module_paths)
    if not scoped_files:
        return {}

    buckets: dict[str, list[str]] = defaultdict(list)
    inspected = 0
    for relative_path in prioritize_summary_paths("backend", scoped_files):
        if inspected >= MAX_SUMMARY_SCAN_FILES:
            break
        if not should_scan_summary_file(relative_path):
            continue
        try:
            lines = (code_dir / relative_path).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        inspected += 1
        for flow_type in backend_flow_hits(relative_path, lines):
            if len(buckets[flow_type]) < MAX_SUMMARY_REFS * 2:
                buckets[flow_type].append(relative_path)

    return {
        flow_type: line_refs_for_paths(code_dir, paths, MAX_SUMMARY_REFS)
        for flow_type, paths in buckets.items()
        if paths
    }


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
    matches = [path for path in all_tests if any(path_matches_root(path, root) for root in module_paths)]
    if matches:
        return matches
    fallback_roots: list[str] = []
    for root in module_paths:
        root_path = PurePosixPath(root)
        root_name = root_path.name
        if root_name not in SUMMARY_AREA_CONTAINER_SEGMENTS | {"src", "app"}:
            continue
        parent = root_path.parent.as_posix()
        if parent and parent != ".":
            fallback_roots.extend([f"{parent}/test", f"{parent}/tests", f"{parent}/e2e"])
        else:
            fallback_roots.extend(["test", "tests", "e2e"])
    if fallback_roots:
        return [path for path in all_tests if any(path_matches_root(path, root) for root in fallback_roots)]
    return []


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


def feature_title(feature: str) -> str:
    return feature.replace("-", " ").replace("_", " ").title()


def should_scan_summary_file(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    suffix = path.suffix.lower()
    if suffix in SUMMARY_BINARY_SUFFIXES:
        return False
    if suffix in SUMMARY_TEXT_SUFFIXES:
        return True
    if path.name in GLOBAL_CONFIG_FILES or path.name in ENTRYPOINT_FILE_NAMES:
        return True
    return not suffix and path.name.lower() in {"dockerfile", "makefile", "justfile"}


def language_name_for_path(relative_path: str) -> str | None:
    path = PurePosixPath(relative_path)
    if path.name == "Dockerfile":
        return "Dockerfile"
    if path.name == "Makefile":
        return "Makefile"
    if path.name == "justfile":
        return "Justfile"
    return LANGUAGE_NAMES.get(path.suffix.lower())


def summary_area_for_local_path(local_path: str) -> str:
    path = PurePosixPath(local_path)
    directory_parts = [part for part in path.parts[:-1] if part]
    if not directory_parts:
        return "module-root"
    if directory_parts[0].lower() in SUMMARY_AREA_CONTAINER_SEGMENTS and len(directory_parts) > 1:
        return "/".join(directory_parts[:2])
    return directory_parts[0]


def module_category_hits(module: str, text: str) -> set[str]:
    normalized = normalize_match_text(text)
    categories: set[str] = set()
    for category, keywords in MODULE_CATEGORY_KEYWORDS.get(module, {}).items():
        for keyword in keywords:
            normalized_keyword = normalize_match_text(keyword)
            if normalized_keyword and normalized_keyword in normalized:
                categories.add(category)
                break
    return categories


def framework_hits(module: str, relative_path: str, lines: list[str]) -> set[str]:
    lowered_path = relative_path.lower()
    lowered_text = "\n".join(lines[:160]).lower()
    hits: set[str] = set()
    for framework, patterns in MODULE_FRAMEWORK_PATTERNS.get(module, {}).items():
        for pattern in patterns:
            lowered_pattern = pattern.lower()
            if lowered_pattern in lowered_path or lowered_pattern in lowered_text:
                hits.add(framework)
                break
    return hits


def prioritize_summary_paths(module: str, relative_paths: list[str]) -> list[str]:
    def priority(relative_path: str) -> tuple[int, int, str]:
        score = 100
        lower = relative_path.lower()
        name = PurePosixPath(relative_path).name
        if name in ENTRYPOINT_FILE_NAMES or is_entrypoint_sensitive_path(relative_path):
            score -= 60
        score -= 12 * len(module_category_hits(module, relative_path))
        if any(token in lower for token in ("test", "spec", "__tests__", "playwright", "cypress")):
            score -= 6
        if not should_scan_summary_file(relative_path):
            score += 40
        if PurePosixPath(relative_path).suffix.lower() in {".md", ".txt"}:
            score += 20
        return (score, len(relative_path), relative_path)

    return sorted(relative_paths, key=priority)


def format_counter_items(items: list[tuple[str, int]]) -> str:
    if not items:
        return "no dominant code pattern detected"
    return ", ".join(f"{name} ({count})" for name, count in items)


def format_inline_refs(refs: list[str]) -> str:
    if not refs:
        return ""
    return ", ".join(refs[:MAX_SUMMARY_REFS])


def first_ref(*ref_groups: list[str]) -> str | None:
    for refs in ref_groups:
        if refs:
            return refs[0]
    return None


def compose_flow_line(label: str, input_ref: str | None, processing_ref: str | None, output_ref: str | None) -> str | None:
    stages: list[str] = []
    if input_ref:
        stages.append(f"input {input_ref}")
    if processing_ref:
        stages.append(f"processing {processing_ref}")
    if output_ref:
        stages.append(f"output {output_ref}")
    if len(stages) < 2:
        return None
    return f"- {label}: " + " -> ".join(stages) + "."


def backend_core_flow_lines(code_dir: Path, module_paths: list[str], profile: ModuleProfile) -> list[str]:
    flow_refs = collect_backend_flow_refs(code_dir, module_paths)
    http_refs = flow_refs.get("http", []) or profile.category_refs.get("http", [])
    rpc_refs = flow_refs.get("rpc", [])
    job_refs = flow_refs.get("job", []) or profile.category_refs.get("job", [])
    service_refs = profile.category_refs.get("service", []) or flow_refs.get("service", [])
    data_refs = profile.category_refs.get("data", []) or flow_refs.get("data", [])
    output_refs = flow_refs.get("output", [])
    integration_refs = profile.category_refs.get("integration", [])
    auth_refs = profile.category_refs.get("auth", [])

    lines: list[str] = []
    if http_refs:
        http_line = compose_flow_line(
            "HTTP/API flow",
            first_ref(http_refs),
            first_ref(service_refs, integration_refs, auth_refs, data_refs),
            first_ref(output_refs, data_refs, integration_refs),
        )
        if http_line:
            lines.append(http_line)

    if rpc_refs:
        rpc_line = compose_flow_line(
            "RPC/IDL flow (including gRPC/Thrift when present)",
            first_ref(rpc_refs),
            first_ref(service_refs, integration_refs, auth_refs, data_refs),
            first_ref(output_refs, data_refs, integration_refs),
        )
        if rpc_line:
            lines.append(rpc_line)

    if job_refs:
        job_line = compose_flow_line(
            "Async job/queue flow",
            first_ref(job_refs),
            first_ref(service_refs, integration_refs, data_refs),
            first_ref(output_refs, data_refs, integration_refs),
        )
        if job_line:
            lines.append(job_line)

    if lines:
        return lines

    fallback_line = compose_flow_line(
        "Fallback runtime flow",
        first_ref(profile.entrypoints, http_refs, rpc_refs, job_refs),
        first_ref(service_refs, integration_refs, auth_refs, data_refs),
        first_ref(output_refs, data_refs, integration_refs),
    )
    if fallback_line:
        return [fallback_line]

    return ["- No stable runtime flow chain was inferred automatically; add manual flow notes when runtime wiring is implicit."]


def module_core_flow_lines(module: str, code_dir: Path, module_paths: list[str], profile: ModuleProfile) -> list[str]:
    if module == "backend":
        return backend_core_flow_lines(code_dir, module_paths, profile)
    return []


def build_module_profile(module: str, code_dir: Path, module_paths: list[str]) -> ModuleProfile:
    scoped_files = module_scoped_files(code_dir, module_paths)
    if not scoped_files:
        return ModuleProfile(0, 0, [], [], {}, {}, [], [], [], [], {})

    language_counts: Counter[str] = Counter()
    area_counts: Counter[str] = Counter()
    area_paths: dict[str, list[str]] = defaultdict(list)
    category_counts: Counter[str] = Counter()
    category_paths: dict[str, list[str]] = defaultdict(list)

    for relative_path in scoped_files:
        language = language_name_for_path(relative_path)
        if language:
            language_counts[language] += 1

        local_path = relative_within_module_root(relative_path, module_paths)
        area = summary_area_for_local_path(local_path)
        area_counts[area] += 1
        if len(area_paths[area]) < MAX_SUMMARY_REFS:
            area_paths[area].append(relative_path)

        for category in module_category_hits(module, relative_path):
            category_counts[category] += 1
            if len(category_paths[category]) < MAX_SUMMARY_REFS:
                category_paths[category].append(relative_path)

    framework_counts: Counter[str] = Counter()
    inspected_files = 0
    for relative_path in prioritize_summary_paths(module, scoped_files)[:MAX_SUMMARY_SCAN_FILES]:
        if not should_scan_summary_file(relative_path):
            continue
        try:
            lines = (code_dir / relative_path).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        inspected_files += 1

        content_probe = relative_path + "\n" + "\n".join(lines[:160])
        for category in module_category_hits(module, content_probe):
            category_counts[category] += 1
            if len(category_paths[category]) < MAX_SUMMARY_REFS:
                category_paths[category].append(relative_path)

        for framework in framework_hits(module, relative_path, lines):
            framework_counts[framework] += 1

    top_areas = area_counts.most_common(MAX_SUMMARY_AREA_ITEMS)
    area_refs = {
        area: line_refs_for_paths(code_dir, area_paths.get(area, []), MAX_SUMMARY_REFS)
        for area, _ in top_areas
    }
    ranked_categories = sorted(
        category_counts.items(),
        key=lambda item: (-item[1], MODULE_CATEGORY_LABELS.get(module, {}).get(item[0], item[0])),
    )[:MAX_SUMMARY_CATEGORY_ITEMS]
    category_refs = {
        category: line_refs_for_paths(code_dir, category_paths.get(category, []), MAX_SUMMARY_REFS)
        for category, _ in ranked_categories
    }

    key_paths: list[str] = []
    key_paths.extend(module_entrypoints(code_dir, module_paths)[:MAX_SUMMARY_REFS])
    for category, _ in ranked_categories:
        key_paths.extend(category_paths.get(category, [])[:1])
    for area, _ in top_areas:
        key_paths.extend(area_paths.get(area, [])[:1])
    if not key_paths:
        key_paths.extend(scoped_files[:MAX_LISTED_ITEMS])
    key_refs = limited_paths(line_refs_for_paths(code_dir, list(dict.fromkeys(key_paths))), MAX_LISTED_ITEMS)

    return ModuleProfile(
        total_files=len(scoped_files),
        inspected_files=inspected_files,
        languages=language_counts.most_common(4),
        focus_areas=top_areas,
        category_refs=category_refs,
        category_counts={category: count for category, count in ranked_categories},
        frameworks=framework_counts.most_common(4),
        key_refs=key_refs,
        entrypoints=limited_paths(line_refs_for_paths(code_dir, module_entrypoints(code_dir, module_paths))),
        tests=limited_paths(line_refs_for_paths(code_dir, module_test_paths(code_dir, module_paths))),
        area_refs=area_refs,
    )


def module_summary_lines(module: str, profile: ModuleProfile, module_features: dict[str, list[str]]) -> list[str]:
    if not profile.total_files:
        return ["- No module-scoped files were discovered automatically."]

    lines = [
        (
            f"- Code footprint: `{profile.total_files}` files in this module; "
            f"representative code inspection covered `{profile.inspected_files}` files. "
            f"Dominant languages/config types: {format_counter_items(profile.languages)}."
        )
    ]

    if profile.focus_areas:
        area_parts = []
        for area, count in profile.focus_areas:
            refs = format_inline_refs(profile.area_refs.get(area, []))
            if refs:
                area_parts.append(f"`{area}` ({count}; {refs})")
            else:
                area_parts.append(f"`{area}` ({count})")
        lines.append("- Code organization: " + ", ".join(area_parts) + ".")

    if profile.frameworks:
        lines.append(f"- Framework/runtime signals found in code: {format_counter_items(profile.frameworks)}.")

    if module_features:
        feature_names = ", ".join(f"`{feature}`" for feature in sorted(module_features)[:6])
        lines.append(f"- Functional slices inferred from code layout: {feature_names}.")
    else:
        lines.append("- Functional slices are not strongly separated by path names; the module appears organized mainly by technical layers.")

    labels = MODULE_CATEGORY_LABELS.get(module, {})
    ranked_categories = sorted(profile.category_counts.items(), key=lambda item: (-item[1], labels.get(item[0], item[0])))
    for category, count in ranked_categories:
        refs = format_inline_refs(profile.category_refs.get(category, []))
        label = labels.get(category, category.replace("-", " "))
        if refs:
            lines.append(f"- {label}: `{count}` matching code signals. Representative refs: {refs}.")
        else:
            lines.append(f"- {label}: `{count}` matching code signals.")

    if profile.entrypoints:
        lines.append("- Module-local entrypoints or startup-sensitive files: " + format_inline_refs(profile.entrypoints) + ".")
    else:
        lines.append("- No common module-local entrypoint files were discovered automatically.")

    if profile.tests:
        lines.append("- Module-local tests and verification hooks: " + format_inline_refs(profile.tests) + ".")
    else:
        lines.append("- No module-local tests were detected automatically.")

    return lines


def feature_common_dir_prefix(feature_paths: list[str]) -> str:
    if not feature_paths:
        return ""
    path_parts = [list(PurePosixPath(path).parts[:-1]) for path in feature_paths]
    if not path_parts:
        return ""
    common = path_parts[0]
    for parts in path_parts[1:]:
        index = 0
        max_index = min(len(common), len(parts))
        while index < max_index and common[index] == parts[index]:
            index += 1
        common = common[:index]
        if not common:
            break
    return "/".join(common)


def feature_local_path(relative_path: str, common_prefix: str) -> str:
    path = PurePosixPath(relative_path)
    if common_prefix:
        try:
            return path.relative_to(PurePosixPath(common_prefix)).as_posix()
        except ValueError:
            return relative_path
    return relative_path


def build_feature_profile(
    module: str,
    feature: str,
    code_dir: Path,
    module_paths: list[str],
    feature_paths: list[str],
) -> FeatureProfile:
    scoped_files = sorted(dict.fromkeys(feature_paths))
    if not scoped_files:
        return FeatureProfile(0, 0, [], [], {}, {}, [], [], [], [], {})

    common_prefix = feature_common_dir_prefix(scoped_files)
    language_counts: Counter[str] = Counter()
    area_counts: Counter[str] = Counter()
    area_paths: dict[str, list[str]] = defaultdict(list)
    category_counts: Counter[str] = Counter()
    category_paths: dict[str, list[str]] = defaultdict(list)

    for relative_path in scoped_files:
        language = language_name_for_path(relative_path)
        if language:
            language_counts[language] += 1

        local_path = feature_local_path(relative_path, common_prefix)
        area = summary_area_for_local_path(local_path)
        area_counts[area] += 1
        if len(area_paths[area]) < MAX_SUMMARY_REFS:
            area_paths[area].append(relative_path)

        for category in module_category_hits(module, relative_path):
            category_counts[category] += 1
            if len(category_paths[category]) < MAX_SUMMARY_REFS:
                category_paths[category].append(relative_path)

    framework_counts: Counter[str] = Counter()
    inspected_files = 0
    for relative_path in prioritize_summary_paths(module, scoped_files)[:MAX_SUMMARY_SCAN_FILES]:
        if not should_scan_summary_file(relative_path):
            continue
        try:
            lines = (code_dir / relative_path).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        inspected_files += 1

        content_probe = relative_path + "\n" + "\n".join(lines[:160])
        for category in module_category_hits(module, content_probe):
            category_counts[category] += 1
            if len(category_paths[category]) < MAX_SUMMARY_REFS:
                category_paths[category].append(relative_path)

        for framework in framework_hits(module, relative_path, lines):
            framework_counts[framework] += 1

    top_areas = area_counts.most_common(MAX_SUMMARY_AREA_ITEMS)
    area_refs = {
        area: line_refs_for_paths(code_dir, area_paths.get(area, []), MAX_SUMMARY_REFS)
        for area, _ in top_areas
    }
    ranked_categories = sorted(
        category_counts.items(),
        key=lambda item: (-item[1], MODULE_CATEGORY_LABELS.get(module, {}).get(item[0], item[0])),
    )[:MAX_SUMMARY_CATEGORY_ITEMS]
    category_refs = {
        category: line_refs_for_paths(code_dir, category_paths.get(category, []), MAX_SUMMARY_REFS)
        for category, _ in ranked_categories
    }

    entrypoint_paths = [
        path
        for path in scoped_files
        if is_entrypoint_sensitive_path(path) or PurePosixPath(path).name in ENTRYPOINT_FILE_NAMES
    ]
    test_paths_for_feature = [
        path
        for path in scoped_files
        if any(token in path.lower() for token in ("test", "spec", "__tests__", "playwright", "cypress"))
    ]
    feature_terms = [term for term in normalize_feature_token(feature).split("-") if term]
    if module_paths and feature_terms:
        for path in module_test_paths(code_dir, module_paths):
            lowered = path.lower()
            if any(term in lowered for term in feature_terms):
                test_paths_for_feature.append(path)
    test_paths_for_feature = sorted(dict.fromkeys(test_paths_for_feature))

    key_paths: list[str] = []
    key_paths.extend(entrypoint_paths[:MAX_SUMMARY_REFS])
    key_paths.extend(test_paths_for_feature[:1])
    for category, _ in ranked_categories:
        key_paths.extend(category_paths.get(category, [])[:1])
    for area, _ in top_areas:
        key_paths.extend(area_paths.get(area, [])[:1])
    if not key_paths:
        key_paths.extend(scoped_files[:MAX_LISTED_ITEMS])
    key_refs = limited_paths(line_refs_for_paths(code_dir, list(dict.fromkeys(key_paths))), MAX_LISTED_ITEMS)

    return FeatureProfile(
        total_files=len(scoped_files),
        inspected_files=inspected_files,
        languages=language_counts.most_common(4),
        focus_areas=top_areas,
        category_refs=category_refs,
        category_counts={category: count for category, count in ranked_categories},
        frameworks=framework_counts.most_common(4),
        key_refs=key_refs,
        entrypoints=limited_paths(line_refs_for_paths(code_dir, entrypoint_paths)),
        tests=limited_paths(line_refs_for_paths(code_dir, test_paths_for_feature)),
        area_refs=area_refs,
    )


def feature_summary_lines(module: str, feature: str, profile: FeatureProfile) -> list[str]:
    if not profile.total_files:
        return [f"- No code paths were grouped into the `{feature}` feature automatically."]

    lines = [
        (
            f"- Code footprint: `{profile.total_files}` files are mapped to `{feature}`; "
            f"representative code inspection covered `{profile.inspected_files}` files. "
            f"Dominant languages/config types: {format_counter_items(profile.languages)}."
        )
    ]

    if profile.focus_areas:
        area_parts = []
        for area, count in profile.focus_areas:
            refs = format_inline_refs(profile.area_refs.get(area, []))
            if refs:
                area_parts.append(f"`{area}` ({count}; {refs})")
            else:
                area_parts.append(f"`{area}` ({count})")
        lines.append("- Feature-local organization: " + ", ".join(area_parts) + ".")

    if profile.frameworks:
        lines.append(f"- Framework/runtime signals found in this feature: {format_counter_items(profile.frameworks)}.")

    labels = MODULE_CATEGORY_LABELS.get(module, {})
    ranked_categories = sorted(profile.category_counts.items(), key=lambda item: (-item[1], labels.get(item[0], item[0])))
    if not ranked_categories:
        lines.append("- No strong layer split was inferred for this feature; it appears as a compact implementation slice.")
        return lines

    for category, count in ranked_categories:
        refs = format_inline_refs(profile.category_refs.get(category, []))
        label = labels.get(category, category.replace("-", " "))
        if refs:
            lines.append(f"- {label}: `{count}` matching code signals. Representative refs: {refs}.")
        else:
            lines.append(f"- {label}: `{count}` matching code signals.")
    return lines


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


def agent_non_goals(agent: str) -> list[str]:
    goals = [
        "Do not assert behavior from filenames alone when line-level evidence is available.",
        "Do not widen to unrelated modules without a concrete trigger from diff, runtime boundaries, or failing verification.",
    ]
    if agent == "reviewer":
        goals.append("Do not rewrite large module docs unless a concrete inconsistency blocks review quality.")
    return goals


def agent_principles(agent: str) -> list[str]:
    principles = [
        "Start from the agent scope before loading deeper module detail.",
        "Support important claims with file/symbol evidence (line hints when available) from the current code snapshot.",
        "Escalate to broader review when entrypoints, boundaries, or diff-to-context mapping are ambiguous.",
    ]
    if agent == "reviewer":
        principles.append("Prefer risk surfacing and boundary checks over rewriting large amounts of text.")
    return principles


def agent_operating_invariants(agent: str) -> list[str]:
    invariants = [
        "Diff-first inspection before broad source reading whenever Git baseline is available.",
        "Every meaningful claim should have at least one concrete file/symbol reference.",
        "After each fix, run at least one scoped verification command before declaring progress.",
        "Record durable decisions and repeated misses in system-of-record files, not transient chat context.",
    ]
    if agent == "reviewer":
        invariants.append("Prioritize risk discovery and misleading context corrections over adding more narrative text.")
    return invariants


def agent_task_loop(agent: str) -> list[str]:
    return [
        "Observe: inspect current diff/sync scope, module roots, and relevant entrypoints.",
        "Plan: define the smallest safe check/edit set and expected verification signal.",
        "Act: execute scoped inspection or edits only inside the declared scope.",
        "Verify: run targeted commands/tests and compare outputs against context claims.",
        "Record: update findings, decisions, and unresolved risks with concrete evidence refs.",
    ]


def agent_escalation_triggers(agent: str) -> list[str]:
    triggers = [
        "Entrypoint-sensitive files changed while multiple runtime candidates exist.",
        "Diff scope cannot be mapped cleanly to current module roots.",
        "Verification output contradicts generated context claims.",
        "High-impact changes touch release/data/security/test boundaries without sufficient evidence.",
    ]
    if agent == "reviewer":
        triggers.append("Cross-module regressions or architecture drift are suspected from combined signals.")
    return triggers


def agent_system_of_record_paths(agent: str) -> list[str]:
    paths = [layout.SKILL_FILENAME, layout.PROJECT_STATUS_FILENAME, layout.ENTRYPOINTS_FILENAME, layout.FEATURE_MAP_FILENAME]
    if agent == "reviewer":
        paths.extend(
            [
                layout.REQUIREMENTS_MAP_FILENAME,
                layout.DOMAIN_MODEL_FILENAME,
                layout.AGENTS_INDEX_FILENAME,
            ]
        )
        mapped: list[str] = []
        reference_files = {
            layout.ENTRYPOINTS_FILENAME,
            layout.FEATURE_MAP_FILENAME,
            layout.REQUIREMENTS_MAP_FILENAME,
            layout.DOMAIN_MODEL_FILENAME,
        }
        for path in paths:
            if path in reference_files:
                mapped.append(f"`{layout.REFERENCES_DIRNAME}/{path}`")
            elif path == layout.AGENTS_INDEX_FILENAME:
                mapped.append(f"`{layout.AGENTS_DIRNAME}/{path}`")
            else:
                mapped.append(f"`{path}`")
        return mapped

    return [
        f"`{layout.relative_module_overview(agent)}`",
        f"`{layout.relative_module_detail(agent)}`",
        f"`{layout.REFERENCES_DIRNAME}/{layout.ENTRYPOINTS_FILENAME}`",
        f"`{layout.REFERENCES_DIRNAME}/{layout.FEATURE_MAP_FILENAME}`",
        f"`{layout.PROJECT_STATUS_FILENAME}`",
    ]


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
    scope_line = (
        ", ".join(f"`{path}`" for path in limited_paths(scope_paths))
        if scope_paths
        else "No stable code roots were inferred automatically for this agent."
    )
    lines = [
        "## Generated Agent Profile",
        f"- Role: {agent_role(agent)}",
        "",
        "## Harness Contract",
        f"- Scope boundary: {scope_line}",
        "- Non-goals:",
        *[f"- {item}" for item in agent_non_goals(agent)],
        "",
        "## Operating Invariants",
        *[f"- {item}" for item in agent_operating_invariants(agent)],
        "",
        "## Task Loop (Observe -> Plan -> Act -> Verify -> Record)",
        *[f"- {item}" for item in agent_task_loop(agent)],
        "",
        "## Escalation And Stop Conditions",
        *[f"- {item}" for item in agent_escalation_triggers(agent)],
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
        f"- Start with `{layout.AGENT_README_FILENAME}`, load `{layout.AGENT_TOOLS_FILENAME}` and `{layout.AGENT_MEMORY_FILENAME}` only when needed, then move into the module docs and any matching feature docs.",
        "- Keep the review scoped to the mapped module roots unless the diff or evidence says that is unsafe.",
        "",
        "## System Of Record",
        *format_list(agent_system_of_record_paths(agent), "No system-of-record paths were inferred automatically.", quote=False),
        "",
        "## Scope Evidence",
        *format_list(evidence_refs, "No representative symbol-level evidence was discovered automatically.", quote=False),
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
        "- Harness tooling surface (scoped first, then broaden only when escalation triggers fire).",
        "- Preferred commands:",
        *format_list(commands, "No common commands discovered automatically."),
        "- Verification loop:",
        "- Run the smallest scoped check first, then widen only if signals are inconclusive.",
        "- Re-run at least one relevant command after each material edit.",
        "- Command manifest evidence:",
        *format_list(manifest_refs, "No build or runtime manifests discovered automatically.", quote=False),
        "- Entrypoint evidence:",
        *format_list(entrypoint_refs, "No scoped entrypoint evidence discovered automatically.", quote=False),
        "- Testing evidence:",
        *format_list(test_refs, "No scoped testing evidence discovered automatically.", quote=False),
        "- Feedback hooks:",
        f"- Record durable corrections in `{layout.AGENT_DECISIONS_FILENAME}` or `{layout.DECISIONS_FILENAME}`.",
        f"- Record repeated misses in `{layout.AGENT_FAILS_FILENAME}` so future runs can avoid them.",
    ]
    return "\n".join(lines)


def generate_agent_memory_block(agent: str, code_dir: Path, module_map: dict[str, list[str]]) -> str:
    scope_paths = agent_scope_paths(agent, module_map)
    evidence_refs = limited_paths(module_line_refs(code_dir, scope_paths))
    if agent == "reviewer":
        entrypoint_refs = limited_paths(line_refs_for_paths(code_dir, entrypoint_candidates(code_dir)))
    else:
        entrypoint_refs = limited_paths(line_refs_for_paths(code_dir, module_entrypoints(code_dir, scope_paths)))
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
            "- System-of-record docs:",
            *format_list(agent_system_of_record_paths(agent), "No system-of-record docs inferred automatically.", quote=False),
            "- Drift watchlist (entrypoint/runtime-sensitive refs):",
            *format_list(entrypoint_refs, "No runtime-sensitive refs inferred automatically.", quote=False),
            "- Re-entry evidence:",
            *format_list(evidence_refs, "No representative evidence recorded automatically.", quote=False),
            "- Escalation triggers:",
            *[f"- {item}" for item in agent_escalation_triggers(agent)],
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
    feature_map: dict[str, dict[str, list[str]]],
    global_paths: list[str],
    mode: SyncMode,
    manifests: list[str],
    repo_root: Path | None,
    branch: str | None,
    head: str | None,
    multi_git: dict[str, dict[str, str | None]] | None = None,
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
    elif multi_git:
        lines.append("- Git sources:")
        for name, meta in sorted(multi_git.items()):
            repo = meta.get("repo_root") or "unknown"
            branch = meta.get("branch") or "unknown"
            head = meta.get("head") or "unknown"
            lines.append(f"  - `{name}` -> root `{repo}`, branch `{branch}`, head `{head}`")
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
        feature_names = sorted(feature_map.get(module, {}).keys())
        feature_text = ""
        if feature_names:
            feature_text = (
                " Feature docs: "
                + ", ".join(f"`{layout.relative_module_feature(module, feature)}`" for feature in feature_names[:4])
            )
        lines.append(
            f"- `{module}`: load `{layout.relative_module_overview(module)}` first, "
            f"then `{layout.relative_module_detail(module)}`.{feature_text}"
        )

    lines.extend(
        [
            "",
            "## Progressive Loading Model",
            f"- L1: `{layout.SKILL_FILENAME}` for global overview, routing rules, loading order, and runtime notes.",
            f"- L2: `{layout.AGENTS_DIRNAME}/` and module overview files such as "
            f"`{layout.MODULES_DIRNAME}/<module>/{layout.MODULE_OVERVIEW_FILENAME}`.",
            f"- L3: module detail files such as `{layout.MODULES_DIRNAME}/<module>/<module>.md`, "
            f"feature files such as `{layout.MODULES_DIRNAME}/<module>/<feature>.md`, and detailed `{layout.REFERENCES_DIRNAME}/` docs.",
            "",
            "### Preferred Load Order",
            f"- Load `{layout.SKILL_FILENAME}` first.",
            f"- Route to the relevant agent under `{layout.AGENTS_DIRNAME}/<agent>/`.",
            "- Let that agent choose which module to inspect.",
            f"- Load `{layout.MODULES_DIRNAME}/<module>/{layout.MODULE_OVERVIEW_FILENAME}` before "
            f"`{layout.MODULES_DIRNAME}/<module>/<module>.md`.",
            f"- If the module has stable business features, load `{layout.MODULES_DIRNAME}/<module>/<feature>.md` after the module index.",
            f"- Load `{layout.REFERENCES_DIRNAME}/` only for evidence-level checks and requirement trace checks.",
            f"- Use `{layout.REFERENCES_DIRNAME}/{layout.REQUIREMENTS_MAP_FILENAME}` to map PRD requirements to features/modules/code refs.",
            f"- Use `{layout.REFERENCES_DIRNAME}/{layout.DOMAIN_MODEL_FILENAME}` for inferred domain entities/states/rules before drafting technical plans.",
            "",
            "## Spec-Driven Development",
            "- Keep spec-first changes outside this AUTO block if the project needs custom policy.",
            "- Minimum spec fields: scope, interfaces, edge cases, acceptance criteria, and tests.",
            f"- Record major spec changes in `{layout.DECISIONS_FILENAME}` or the relevant agent `{layout.AGENT_DECISIONS_FILENAME}`.",
        ]
    )
    return "\n".join(lines)


def generate_feature_map_block(feature_map: dict[str, dict[str, list[str]]]) -> str:
    lines = [
        "## Generated Feature Map",
        "- Shared business features grouped by technical module.",
    ]
    shared = shared_feature_modules(feature_map)
    if not shared:
        lines.append("- No stable feature-level docs were inferred automatically.")
        return "\n".join(lines)

    for feature, modules in sorted(shared.items()):
        lines.append(f"- `{feature}`")
        for module in modules:
            lines.append(f"  - `{module}` -> `{layout.relative_module_feature(module, feature)}`")
    return "\n".join(lines)


def generate_modules_index_block(
    modules: list[str],
    module_map: dict[str, list[str]],
    feature_map: dict[str, dict[str, list[str]]],
) -> str:
    lines = [
        "## Generated Module Index",
        "- Load the module README before the detailed module note.",
    ]
    for module in modules:
        mapped_paths = module_map.get(module, [])
        if module == "reviewer":
            lines.append("- `reviewer`: review-only module; does not map to a single code path.")
            continue
        feature_names = sorted(feature_map.get(module, {}).keys())
        feature_text = ""
        if feature_names:
            feature_text = " Feature docs: " + ", ".join(f"`{feature}`" for feature in feature_names[:4]) + "."
        if mapped_paths:
            lines.append(
                f"- `{module}`: covers {', '.join(f'`{path}`' for path in limited_paths(mapped_paths))}.{feature_text}"
            )
        else:
            lines.append(f"- `{module}`: no stable path mapping inferred yet.{feature_text}")
    return "\n".join(lines)


def generate_module_overview_block(
    module: str,
    profile: ModuleProfile,
    module_features: dict[str, list[str]],
) -> str:
    tasks = module_tasks(module)
    lines = [
        "## Generated Overview",
        f"- Responsibility: {module_responsibility(module)}",
        "- Code-derived summary:",
        *module_summary_lines(module, profile, module_features),
        "- Representative implementation files:",
        *format_list(profile.key_refs, "No representative symbol-level references discovered automatically.", quote=False),
        "- Linked feature docs:",
        *format_list(
            [f"`{feature}` -> `{layout.relative_module_feature(module, feature)}`" for feature in sorted(module_features)],
            "No stable feature docs inferred for this module yet.",
            quote=False,
        ),
        "- Typical tasks:",
        *[f"- {task}" for task in tasks],
    ]
    return "\n".join(lines)


def generate_module_detail_block(
    module: str,
    code_dir: Path,
    module_paths: list[str],
    profile: ModuleProfile,
    module_map: dict[str, list[str]],
    module_features: dict[str, list[str]],
) -> str:
    sibling_modules = [name for name, paths in module_map.items() if name != module and paths]
    core_flow_lines = module_core_flow_lines(module, code_dir, module_paths, profile)
    lines = [
        "## Generated Code Summary",
        "- Content inside this AUTO block is managed by `scripts/sync_context_project.py`.",
        "- Add durable manual notes outside the AUTO block so sync can preserve them.",
        "- If this block is edited manually, future syncs stop unless `--force-generated` is used.",
        "",
        "### Scope Evidence",
        f"- Covers: {', '.join(f'`{path}`' for path in module_paths) if module_paths else 'No stable path mapping inferred yet.'}",
        f"- Summary mode: code-derived module summary with representative references, not a file-only inventory.",
        "",
        "### Implementation Summary",
        *module_summary_lines(module, profile, module_features),
        "",
        "### Representative Files",
        *format_list(profile.key_refs, "No representative symbol-level references discovered automatically.", quote=False),
        "",
        "### Functional Subdomains",
        *format_list(
            [f"`{feature}` -> `{layout.relative_module_feature(module, feature)}`" for feature in sorted(module_features)],
            "No stable business subdomains were inferred automatically for this module.",
            quote=False,
        ),
        "",
        "### Responsibility And Dependency Notes",
        f"- {module_responsibility(module)}",
    ]
    if sibling_modules:
        lines.extend(f"- See `{name}` module for adjacent behavior." for name in sibling_modules[:4])
    else:
        lines.append("- No adjacent module hints inferred.")
    lines.extend(
        [
            "",
            "### Runtime And Tests",
            "- Candidate entrypoints with symbol evidence (line hint when available):",
            *format_list(profile.entrypoints, "No common entrypoint line references discovered inside this module.", quote=False),
        ]
    )
    if core_flow_lines:
        lines.extend(
            [
                "",
                "### Core Flows",
                *core_flow_lines,
            ]
        )
    lines.extend(
        [
            "",
            "### Testing Hooks",
            *format_list(profile.tests, "No module-local test evidence discovered automatically.", quote=False),
        ]
    )
    return "\n".join(lines)


def generate_feature_detail_block(
    module: str,
    feature: str,
    profile: FeatureProfile,
) -> str:
    lines = [
        f"## Generated {feature_title(feature)} Summary",
        f"- Parent module: `{module}`",
        "- Content inside this AUTO block is managed by `scripts/sync_context_project.py`.",
        "- Summary mode: code-derived feature summary with representative references.",
        "",
        "### Implementation Summary",
        *feature_summary_lines(module, feature, profile),
        "",
        "### Representative Files",
        *format_list(profile.key_refs, "No representative symbol-level evidence discovered automatically for this feature.", quote=False),
        "",
        "### Responsibilities",
        f"- Captures the `{feature}` business slice inside the `{module}` technical module.",
        "- Add manual notes outside this AUTO block if the feature needs richer domain context.",
        "",
        "### Entrypoints",
        *format_list(profile.entrypoints, "No obvious entrypoints were inferred automatically for this feature.", quote=False),
        "",
        "### Testing Hooks",
        *format_list(profile.tests, "No feature-local tests were inferred automatically.", quote=False),
    ]
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
    multi_git: dict[str, dict[str, str | None]] | None = None,
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
    elif multi_git:
        lines.append("- Git sources:")
        for name, meta in sorted(multi_git.items()):
            repo = meta.get("repo_root") or "unknown"
            branch = meta.get("branch") or "unknown"
            head = meta.get("head") or "unknown"
            lines.append(f"  - `{name}` -> root `{repo}`, branch `{branch}`, head `{head}`")
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
