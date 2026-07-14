---
name: local-pypi-server
description: Build, publish, and serve a Python package from a local PyPI server using pypiserver. Use when the task requires packaging Python code, hosting it on a private/local PyPI repository, and verifying installation via pip from a custom index URL.
---

# Local PyPI Server Workflow

End-to-end procedure for packaging a Python project and hosting it on a private local PyPI server, then verifying that another environment can install and use it.

## Steps

1. **Lay out the package.** Create a project directory containing a package subdirectory with an `__init__.py` exposing the desired functions or classes.

2. **Write `setup.py`** using `setuptools` at the project root. Include `name`, `version`, `packages=find_packages()`, and any `install_requires` dependencies.

3. **Install the build tool** (one-time per environment): `pip install build`.

4. **Build the distributions.** From the project root, run `python -m build`. This produces both `.whl` and `.tar.gz` artifacts in a `dist/` directory.

5. **Install the server**: `pip install pypiserver`.

6. **Start the server** in the background, serving the `dist/` directory on a chosen port:
   ```
   pypi-server --port <port> <path-to-dist> &
   ```
   Example: `pypi-server --port 8080 ./dist &`

7. **Verify the server.** Curl the simple index — `curl http://localhost:<port>/simple/` — and confirm the package name appears in the listing.

8. **Test installation in a fresh environment.**
   - Create a venv: `python -m venv <venv_dir>`
   - Activate it.
   - Install from the local index: `pip install --index-url http://localhost:<port>/simple/ <package>==<version>`

9. **Validate functionality.** In the fresh venv, import the package and exercise its public API to confirm it works end-to-end.

## Notes

- The simple index URL (path `/simple/`) is the PEP 503 standard endpoint pip queries.
- Run `pypi-server` in the background with `&` (or a process manager) so subsequent commands can use the same shell.
- Pin a version in the install command (`==x.y.z`) to make the test deterministic.
- If the server logs requests, a successful `pip install` against it is the strongest end-to-end signal.