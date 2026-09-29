import importlib.util
import os
import zipfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_package_module():
    path = os.path.join(REPO_ROOT, "infra", "package.py")
    spec = importlib.util.spec_from_file_location("package", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def package_module():
    return _load_package_module()


def _build(package_module, tmp_path, lambda_subdir, py_filename, json_filename):
    canonical_json_path = os.path.join(REPO_ROOT, "data", json_filename)
    output_zip_path = str(tmp_path / f"{lambda_subdir}.zip")
    package_module.build_package(lambda_subdir, py_filename, json_filename, canonical_json_path, output_zip_path)
    return output_zip_path


def test_calculate_premium_zip_has_expected_files_at_root(package_module, tmp_path):
    zip_path = _build(package_module, tmp_path, "calculate_premium", "calculate_premium.py", "rate_table.json")
    with zipfile.ZipFile(zip_path) as zf:
        assert set(zf.namelist()) == {"calculate_premium.py", "rate_table.json"}


def test_check_eligibility_zip_has_expected_files_at_root(package_module, tmp_path):
    zip_path = _build(package_module, tmp_path, "check_eligibility", "check_eligibility.py", "policies.json")
    with zipfile.ZipFile(zip_path) as zf:
        assert set(zf.namelist()) == {"check_eligibility.py", "policies.json"}


def test_out_of_sync_bundled_json_fails_with_clear_message(package_module, tmp_path):
    # Point "canonical" at claims.json instead of rate_table.json so the
    # byte comparison genuinely fails, proving the check is real, not a
    # no-op.
    wrong_canonical = os.path.join(REPO_ROOT, "data", "claims.json")
    output_zip_path = str(tmp_path / "calculate_premium.zip")
    with pytest.raises(SystemExit, match="out of sync"):
        package_module.build_package(
            "calculate_premium", "calculate_premium.py", "rate_table.json", wrong_canonical, output_zip_path
        )


def test_extracted_zip_handler_runs_and_returns_expected_premium(package_module, tmp_path):
    zip_path = _build(package_module, tmp_path, "calculate_premium", "calculate_premium.py", "rate_table.json")
    extract_dir = tmp_path / "extracted"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)

    # Load the extracted handler exactly as it would run inside Lambda:
    # calculate_premium.py alongside rate_table.json, flat, no package.
    handler_path = str(extract_dir / "calculate_premium.py")
    spec = importlib.util.spec_from_file_location("calculate_premium", handler_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.lambda_handler(
        {"age": 35, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {"smoker": True}},
        None,
    )
    assert result["premium_estimate"] == 487.5
