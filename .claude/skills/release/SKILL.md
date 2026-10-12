---
name: release
description: Cut a gcam-mvsdk-py release - bump the version in pyproject.toml, run the tests on Python 3.9 and the current Python, build the wheel and sdist, prove they contain no vendor bytes, smoke-test the wheel in a fresh venv, tag, and (later) publish to PyPI. Use when asked to release, version, tag, build for distribution, or publish the package.
---

# Release procedure

Commit, tag, push, and upload only when the user explicitly asks. Follow the user's git
conventions (no Claude attribution in commits or tags).

## Step 1: preconditions

```bash
git status --short                   # clean, or only the intended release changes
./scripts/check-no-vendor-files.sh   # nothing vendor-derived is tracked
```

## Step 2: bump the version (single source)

Edit `version = "X.Y.Z"` in `[project]` of `pyproject.toml`. `gcam_mvsdk_py.__version__`
is read from the installed metadata, so reinstall the development environment afterwards:

```bash
pip install -e ".[dev]"
python -c "import gcam_mvsdk_py; print(gcam_mvsdk_py.__version__)"   # must print X.Y.Z
```

`tests/test_cli_parsing.py::test_version_matches_pyproject` fails if they disagree.

## Step 3: test on the minimum and the current Python

```bash
pytest -q                                                     # current Python
export UV_PYTHON_INSTALL_DIR=/tmp/uv-python UV_CACHE_DIR=/tmp/uv-cache   # scratch locations
uv python install 3.9 && uv venv -p 3.9 /tmp/venv-py39
uv pip install -p /tmp/venv-py39/bin/python -e ".[dev]"
/tmp/venv-py39/bin/python -m pytest -q
ruff check --select F,E9,B src tests
uvx --from shellcheck-py shellcheck -x install.bash scripts/*.sh .claude/skills/*/*.sh
```

If cameras are available, also run the hardware-test skill.

## Step 4: build

```bash
rm -rf dist && python -m build       # dist/gcam_mvsdk_py-X.Y.Z-py3-none-any.whl and .tar.gz
```

## Step 5: prove the artifacts are clean

```bash
python .claude/skills/release/check_wheel.py dist/*
```

The checker requires the `py3-none-any` tag, a pure-Python file list, no shared libraries,
executables, archives, vendor headers, or `mvsdk.py`, no ELF/PE/Mach-O content in any file,
an `sdk-manifest.toml` identical to the repository root, and metadata version equal to
`pyproject.toml`. Do not release if it reports anything.

## Step 6: smoke-test the wheel in a fresh environment

```bash
python3 -m venv /tmp/wheel-check && /tmp/wheel-check/bin/pip install dist/*.whl
/tmp/wheel-check/bin/gcam-mvsdk-py --version
/tmp/wheel-check/bin/gcam-mvsdk-py --help
bash install.bash --wheel --from <verified SDK archive> --no-sudo    # optional, with GCAM_MVSDK_HOME and HOME pointed at scratch dirs
```

## Step 7: record and tag (only when asked)

Update the Status section of PLAN_PYTHON_WRAPPER.md and IMPLEMENTATION_NOTES.md if behaviour
changed. Then:

```bash
git add -A && git commit -m "Release X.Y.Z"
git tag -a vX.Y.Z -m "gcam-mvsdk-py X.Y.Z"
git push origin main vX.Y.Z
```

Consumers can then use `pip install git+https://github.com/swarmbotix/gcam-mvsdk-py@vX.Y.Z`.

## Step 8: publish to PyPI (later, when the user decides)

```bash
python -m pip install --upgrade twine
twine check dist/*
twine upload --repository testpypi dist/*    # rehearsal
twine upload dist/*                          # PyPI project name: gcam-mvsdk-py
```

Only the wheel and sdist from Step 4, after Step 5 passed, may be uploaded.
