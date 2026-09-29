"""
Builds Lambda deployment zips for both handlers, local only, no AWS
calls. Each zip contains the handler .py and its bundled .json at the
zip root, not inside a folder, so unzipping puts BASE_DIR-relative
loading (os.path.dirname(os.path.abspath(__file__))) right next to the
data file it expects, exactly like Lambda's own unzip-to-/var/task
layout.
"""
import os
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDAS_DIR = os.path.join(REPO_ROOT, "lambdas")
DATA_DIR = os.path.join(REPO_ROOT, "data")
BUILD_DIR = os.path.join(REPO_ROOT, "build")

# (lambda subdir, handler filename, bundled json filename)
PACKAGES = [
    ("calculate_premium", "calculate_premium.py", "rate_table.json"),
    ("check_eligibility", "check_eligibility.py", "policies.json"),
]


def build_package(lambda_subdir, py_filename, json_filename, canonical_json_path, output_zip_path):
    """
    Verifies the bundled json is byte-identical to the canonical copy in
    data/, then writes exactly two files (the handler and the bundled
    json) at the zip root. Writing only these two named files, rather
    than walking the source directory, is what keeps __pycache__/ and
    .pyc out of the zip: there is nothing to filter, they were never
    candidates to begin with.
    """
    bundled_path = os.path.join(LAMBDAS_DIR, lambda_subdir, json_filename)
    py_path = os.path.join(LAMBDAS_DIR, lambda_subdir, py_filename)

    with open(bundled_path, "rb") as f:
        bundled_bytes = f.read()
    with open(canonical_json_path, "rb") as f:
        canonical_bytes = f.read()
    if bundled_bytes != canonical_bytes:
        raise SystemExit(
            f"{bundled_path} is out of sync with {canonical_json_path}. "
            f"Re-copy the canonical file into lambdas/{lambda_subdir}/ before packaging."
        )

    os.makedirs(os.path.dirname(output_zip_path), exist_ok=True)
    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(py_path, arcname=py_filename)
        zf.write(bundled_path, arcname=json_filename)

    return output_zip_path


def _describe(zip_path):
    print(f"\n{zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            print(f"  {info.filename}  {info.file_size} bytes")


def main():
    for lambda_subdir, py_filename, json_filename in PACKAGES:
        canonical_json_path = os.path.join(DATA_DIR, json_filename)
        output_zip_path = os.path.join(BUILD_DIR, f"{lambda_subdir}.zip")
        build_package(lambda_subdir, py_filename, json_filename, canonical_json_path, output_zip_path)
        _describe(output_zip_path)


if __name__ == "__main__":
    main()
