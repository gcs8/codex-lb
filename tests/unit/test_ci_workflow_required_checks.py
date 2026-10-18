import re
from pathlib import Path

CI_WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml"


def _ci_workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def _job_block(text: str, job_name: str) -> str:
    start_match = re.search(rf"^  {re.escape(job_name)}:\n", text, re.MULTILINE)
    assert start_match is not None
    next_job_match = re.search(r"^  [A-Za-z0-9_-]+:\n", text[start_match.end() :], re.MULTILINE)
    if next_job_match is None:
        return text[start_match.start() :]
    return text[start_match.start() : start_match.end() + next_job_match.start()]


def test_pytest_matrix_required_contexts_are_created_for_non_backend_prs() -> None:
    test_job = _job_block(_ci_workflow_text(), "test")

    assert "name: Tests (pytest, ${{ matrix.slice.name }})" in test_job
    assert "matrix:" in test_job
    assert "\n    if: needs.changes.outputs.backend == 'true'" not in test_job
    assert "name: Skip backend tests for unrelated changes" in test_job
    assert "if: needs.changes.outputs.backend != 'true'" in test_job
    assert "required pytest context satisfied" in test_job


def test_pytest_matrix_real_test_steps_still_run_only_for_backend_changes() -> None:
    test_job = _job_block(_ci_workflow_text(), "test")

    assert "if: needs.changes.outputs.backend == 'true'\n        run: make test-${{ matrix.slice.name }}" in test_job
    for step_name in (
        "Checkout repository",
        "Set up Bun",
        "Cache Bun dependencies",
        "Set up uv",
    ):
        step = test_job.split(f"- name: {step_name}", maxsplit=1)[1]
        assert step.lstrip().startswith("if: needs.changes.outputs.backend == 'true'")


def test_postgres_required_context_is_created_for_non_backend_prs() -> None:
    pg_job = _job_block(_ci_workflow_text(), "test-postgres")

    assert "name: Tests (pytest, PostgreSQL)" in pg_job
    assert "\n    if: needs.changes.outputs.backend == 'true'" not in pg_job
    assert "name: Skip PostgreSQL tests for unrelated changes" in pg_job
    assert "if: needs.changes.outputs.backend != 'true'" in pg_job
    assert "required PostgreSQL context satisfied" in pg_job


def test_postgres_real_test_steps_still_run_only_for_backend_changes() -> None:
    pg_job = _job_block(_ci_workflow_text(), "test-postgres")

    assert "if: needs.changes.outputs.backend == 'true'\n        run: make test-postgres" in pg_job
    for step_name in (
        "Checkout repository",
        "Set up Bun",
        "Cache Bun dependencies",
        "Set up uv",
    ):
        step = pg_job.split(f"- name: {step_name}", maxsplit=1)[1]
        assert step.lstrip().startswith("if: needs.changes.outputs.backend == 'true'")


def test_dashboard_browser_smoke_covers_both_contract_sides_and_is_required() -> None:
    workflow = _ci_workflow_text()
    browser_job = _job_block(workflow, "dashboard-browser-smoke")
    required_job = _job_block(workflow, "ci-required")

    assert "if: needs.changes.outputs.backend == 'true' || needs.changes.outputs.frontend == 'true'" in browser_job
    assert "bun run playwright install --with-deps chromium" in browser_job
    assert "run: make test-dashboard-browser-smoke" in browser_job
    assert "- dashboard-browser-smoke" in required_job


def test_openspec_validation_is_required_for_spec_only_changes() -> None:
    workflow = _ci_workflow_text()
    trigger_block = workflow.split("concurrency:", maxsplit=1)[0]

    openspec_job = _job_block(workflow, "openspec")
    required_job = _job_block(workflow, "ci-required")

    assert "pull_request:" in trigger_block
    assert "paths:" not in trigger_block
    assert "paths-ignore:" not in trigger_block
    assert "\n    needs:" not in openspec_job
    assert "\n    if:" not in openspec_job
    assert "npx --yes @fission-ai/openspec@1.11.0 validate --specs" in openspec_job
    assert "fetch-depth: 0" in openspec_job
    assert "python3 .github/scripts/validate_changed_openspec.py" in openspec_job
    assert "- openspec" in required_job


def test_rust_job_runs_native_routed_wire_probe_with_built_helper() -> None:
    workflow = _ci_workflow_text()
    rust_job = _job_block(workflow, "rust")
    required_job = _job_block(workflow, "ci-required")

    build = "cargo build --locked -p codex-lb-egress-worker --bin codex-lb-native-egress"
    probe = "uv run pytest -q -ra tests/integration/test_native_routed_egress.py"
    assert build in rust_job
    assert probe in rust_job
    assert rust_job.index(build) < rust_job.index(probe)
    assert "uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7" in rust_job
    assert "uv sync --dev --frozen" in rust_job
    assert (
        "CODEX_LB_NATIVE_EGRESS_TEST_BINARY: ${{ github.workspace }}/target/debug/codex-lb-native-egress"
    ) in rust_job
    assert "- rust" in required_job


RELEASE_GUARDS_WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "release-guards.yml"


def _pull_request_trigger_types(text: str) -> set[str]:
    trigger_block = text.split("concurrency:", maxsplit=1)[0]
    pull_request_block = trigger_block.split("  pull_request:", maxsplit=1)[1]
    types_match = re.search(r"^    types: \[(?P<types>[^\]]*)\]$", pull_request_block, re.MULTILINE)
    assert types_match is not None
    return {item.strip() for item in types_match.group("types").split(",")}


def test_ci_matrix_does_not_restart_on_pr_metadata_edits() -> None:
    workflow = _ci_workflow_text()

    # ci.yml cancels the in-flight run per ref, so any extra trigger type
    # restarts ~30 jobs for an unchanged head. `edited` (title/body PATCH by
    # agents and review bots) must therefore never be a ci.yml trigger.
    assert "cancel-in-progress: true" in workflow
    assert _pull_request_trigger_types(workflow) == {"opened", "reopened", "synchronize", "ready_for_review"}

    # The PR-body-dependent release guards live in release-guards.yml, and the
    # aggregate must not reference a job that no longer exists here.
    assert re.search(r"^  beta-release-guard:\n", workflow, re.MULTILINE) is None
    assert re.search(r"^  stable-release-guard:\n", workflow, re.MULTILINE) is None
    assert "- beta-release-guard" not in _job_block(workflow, "ci-required")


def test_release_guards_revalidate_pr_metadata_edits_in_their_own_workflow() -> None:
    workflow = RELEASE_GUARDS_WORKFLOW.read_text(encoding="utf-8")

    assert _pull_request_trigger_types(workflow) == {"opened", "reopened", "synchronize", "edited", "ready_for_review"}
    assert "group: ${{ github.workflow }}-${{ github.ref }}" in workflow

    beta_job = _job_block(workflow, "beta-release-guard")
    stable_job = _job_block(workflow, "stable-release-guard")
    # Check context names are unchanged from their ci.yml days.
    assert "name: Beta release guard" in beta_job
    assert "python -m scripts.guard_beta_release" in beta_job
    assert "name: Stable release guard" in stable_job
    assert "python -m scripts.guard_stable_release" in stable_job


def test_integration_core_shards_build_and_export_the_native_helper() -> None:
    """issue-1304 wire regressions in integration-core assert the helper exists."""
    workflow = _ci_workflow_text()
    shard_job = _job_block(workflow, "test-integration-core")

    build = "cargo build --locked -p codex-lb-egress-worker --bin codex-lb-native-egress"
    run = "make test-integration-core-${{ matrix.shard }}"
    assert build in shard_job
    assert run in shard_job
    assert shard_job.index(build) < shard_job.index(run)
    assert (
        "CODEX_LB_NATIVE_EGRESS_TEST_BINARY: ${{ github.workspace }}/target/debug/codex-lb-native-egress"
    ) in shard_job


def test_fork_build_branch_push_runs_full_suite_without_cancellation() -> None:
    """#37: pushes to ryoko/integration must run every job with no path-filter skips."""
    workflow = _ci_workflow_text()
    trigger_block = workflow.split("concurrency:", maxsplit=1)[0]
    push_block = trigger_block.split("  push:", maxsplit=1)[1].split("  pull_request:", maxsplit=1)[0]
    branches = re.search(r"^    branches: \[(?P<branches>[^\]]*)\]$", push_block, re.MULTILINE)
    assert branches is not None
    assert {item.strip().strip('"') for item in branches.group("branches").split(",")} == {
        "main",
        "ryoko/integration",
    }

    changes_job = _job_block(workflow, "changes")
    # Every push event forces the full suite, so the filter step never runs on push.
    assert 'if [[ "${{ github.event_name }}" == "push" ||' in changes_job
    assert "if: steps.force.outputs.full_suite != 'true'" in changes_job
    for area in ("frontend", "backend", "rust", "helm", "docker", "migrations", "nix"):
        assert f"{area}: ${{{{ steps.force.outputs.full_suite || steps.filter.outputs.{area} }}}}" in changes_job

    # Each build-branch push has its own concurrency group (keyed by SHA), so a
    # newer push neither cancels a running push run nor replaces a pending one.
    concurrency_block = workflow.split("concurrency:", maxsplit=1)[1].split("permissions:", maxsplit=1)[0]
    assert (
        "group: ${{ github.workflow }}-${{ github.ref == 'refs/heads/ryoko/integration' && github.sha || github.ref }}"
    ) in concurrency_block
