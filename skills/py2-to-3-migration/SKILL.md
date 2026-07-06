---
name: py2-to-3-migration
description: Step-by-step checklist for migrating Python 2 scientific computing scripts to Python 3. Use when asked to modernize, port, or upgrade legacy Python 2 code that uses numpy, pandas, matplotlib, scipy, configparser, urllib2, cPickle, StringIO, or similar scientific/data libraries.
---

# Python 2 → 3 Migration for Scientific Computing

Apply this checklist in order when modernizing a legacy Python 2 scientific script.

## 1. Audit the original script
- Read the full source first; list every import and every external API call.
- Note any `from __future__ import ...` lines — these are Py2-only and must be removed.
- Identify runtime dependencies (numpy, pandas, matplotlib, scipy, etc.) and their rough versions.

## 2. Replace Py2-only imports and builtins
| Py2 | Py3 |
|---|---|
| `ConfigParser` | `configparser` |
| `cPickle` | `pickle` (optionally `pickle.PickleByte) |
| `urllib2` | `urllib.request` (+ `urllib.parse`, `urllib.error`) |
| `StringIO.StringIO` | `io.StringIO` / `io.BytesIO` |
| `future_builtins` | drop entirely |
| `__future__` imports | remove |
| `unicode(...)` | `str(...)` or drop |
| `basestring`, `xrange`, `long` | `str`, `range`, `int` |
| `itertools.imap/ifilter/izip` | `map/filter/zip` (builtins) |

## 3. Update library APIs
- **pandas**: `pd.datetime` → `pd.to_datetime`; remove deprecated args like `pd.read_csv(..., squeeze=True)` quirks; check `DataFrame.from_dict` orientation changes.
- **NumPy**: drop `dtype` argument from `np.mean`/`np.sum` when passing Python scalars; use `np.float64`, `np.int64` explicitly when needed.
- **matplotlib**: replace deprecated color names (e.g. `'gray'` is fine, but check old `seaborn-*` palettes); switch `plt.cm.get_cmap('name')` to `matplotlib.colormaps['name']` (≥3.7); `subplot`/`subplots` signatures stable.
- **scipy**: confirm `scipy.stats` and `scipy.signal` call signatures for moved/renamed functions.

## 4. Switch to pathlib for paths
- Replace `os.path.join(...)`, `os.path.dirname`, `os.path.basename`, `os.path.splitext` with `pathlib.Path` operations (`.parent`, `.name`, `.stem`, `.suffix`, `Path('a') / 'b'`).
- Wrap string arguments going to library APIs in `Path` only where the API accepts it; otherwise convert with `str(p)`.
- Use `Path.read_text(encoding='utf-8')` / `Path.write_text(data, encoding='utf-8')` instead of manual `open()` + close.

## 5. Fix encoding and text handling
- All `open()` calls that read text must pass `encoding='utf-8'` (or another explicit encoding). Same for `configparser.ConfigParser(...)` — pass `encoding='utf-8'` to its constructor or `read()` calls.
- Replace `u"..."` string literals with plain `"..."` (Python 3 source defaults to UTF-8).
- Replace `b"..."` bytes patterns only when the consuming API truly wants bytes.

## 6. Update config parsing
```python
from configparser import ConfigParser
cfg = ConfigParser()
cfg.read(path, encoding='utf-8')   # encoding kwarg on read()
value = cfg.get('section', 'key')  # returns str
```

## 7. Rewrite the script with modern Python hygiene
- Add module docstring describing purpose and required inputs.
- Wrap executable code in `def main() -> int: ...` with `if __name__ == "__main__": sys.exit(main())`.
- Use `argparse` (or `click`/`typer` if already a dependency) for CLI args; do not rely on `sys.argv` indexing.
- Add type hints on public functions (`from __future__ import annotations` not needed; just annotate).
- Catch narrow exceptions; prefer `ValueError`/`KeyError`/`FileNotFoundError` over bare `except`.

## 8. Pin dependencies
Create or update a dependency manifest with explicit floors:
```
# requirements.txt
numpy>=1.24
pandas>=2.0
matplotlib>=3.7
scipy>=1.10
```
Or use `pyproject.toml` `[project] dependencies` with the same `>=` constraints. Pin only the floor; let pip resolve patch/minor.

## 9. Verify
- Run the new script end-to-end against a sample input; confirm outputs match Py2 behavior (modulo intentional fixes).
- Run `python -Wall -m py_compile path/to/script.py` to catch syntax/import issues.
- Run any existing test suite; if none exists, add a smoke test that imports every module function.