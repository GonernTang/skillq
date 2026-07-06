---
name: local-pypi-hosting
description: Step-by-step procedure for building a Python package from source and hosting it on a local PyPI server using pypiserver. Use when the task requires creating a Python package, exposing it on a local index URL, or verifying install via `pip install --index-url`.
---

# Local PyPI Hosting

End-to-end procedure to build a Python package and serve it through a local `pypiserver` instance so other environments can `pip install` it from a custom `index-url`.

## Prerequisites

- Python with `pip` available.
- A source package directory containing:
  - The package source with an `__init__.py` that exposes the public API in `__all__`.
  - All required module files inside the same package.

## Procedure

### 1. Author `pyproject.toml`

At the package root, create `pyproject.toml` declaring the project metadata and the build backend:

```toml
[project]
name = "<package-name>"
version = "<version>"

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"
```

### 2. Build the distribution

From the project root, run:

```bash
python -m build
```

This produces `dist/<package-name>-<version>.tar.gz` and `dist/<package-name>-<version>-py3-none-any.whl`.

### 3. Install the local server

```bash
pip install pypiserver
```

### 4. Prepare the served packages directory

Create (or pick) an empty directory that will hold the artifacts:

```bash
mkdir -p <packages-dir>
cp dist/* <packages-dir>/
```

`pypiserver` serves any `.tar.gz` / `.whl` files placed in this directory.

### 5. Start `pypiserver`

Run it in the background, binding to the desired port:

```bash
pypi-server run -p <port> <packages-dir> &
```

Verify it is reachable by fetching the simple index (it should respond with an HTML listing of available packages).

### 6. Verify installation from the local index

In an isolated environment (a fresh `python -m venv` is recommended to avoid contamination from other indexes), install the package by exact version:

```bash
python -m venv /tmp/verify-venv
source /tmp/verify-venv/bin/activate
pip install --index-url http://localhost:<port>/simple <package-name>==<version>
```

Then sanity-check that the public API works:

```bash
python -c "from <package-name> import <symbol>; assert <symbol>(... ) == <expected>"
```

If the import succeeds and the smoke test passes, the local PyPI is serving the package correctly.

## Tips

- Pin the version in the verification step (`==<version>`) to confirm the exact artifact served, not just whatever `pip` resolves to.
- Use a separate venv for verification so system packages don't shadow the local one.
- If `pypi-server` complains about the packages directory, confirm the `.whl` / `.tar.gz` files are directly inside it (not nested in subfolders) and readable.
- The simple index path is `/simple/` — pip uses `<index-url>/simple/<normalized-name>/` to look up versions.