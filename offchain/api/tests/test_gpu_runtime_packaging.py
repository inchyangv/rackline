"""Regression for the observed Railway /app package import crash (GPU-053.a)."""

from pathlib import Path

from hashcredit_api.gpu.proofs.manifests import load_manifests
from hashcredit_api.gpu.runtime import discover_manifest_dir


def test_monorepo_layout_finds_versioned_artifacts(tmp_path):
    repo = tmp_path / "repository"
    artifacts = repo / "config" / "attestcoin"
    artifacts.mkdir(parents=True)
    module = repo / "offchain" / "api" / "hashcredit_api" / "gpu" / "runtime.py"
    assert discover_manifest_dir(module) == artifacts


def test_container_layout_finds_copied_artifacts(tmp_path):
    app = tmp_path / "app"
    artifacts = app / "config" / "attestcoin"
    artifacts.mkdir(parents=True)
    module = app / "hashcredit_api" / "gpu" / "runtime.py"
    assert discover_manifest_dir(module) == artifacts


def test_shallow_path_never_indexes_a_nonexistent_parent():
    result = discover_manifest_dir(Path("/runtime.py"))
    assert isinstance(result, Path)


def test_missing_artifacts_keep_the_allowlist_empty(tmp_path):
    module = tmp_path / "isolated" / "hashcredit_api" / "gpu" / "runtime.py"
    result = discover_manifest_dir(module)
    assert not result.exists()
    assert load_manifests(result) == {}
