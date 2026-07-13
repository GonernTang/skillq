---
name: py2-scientific-modernize
description: Port legacy Python 2 scientific computing scripts to Python 3 — fix imports (ConfigParser, cPickle, urllib2, StringIO), unicode, print, xrange/iteritems, deprecated pandas/NumPy APIs, pathlib, f-strings, and produce a modern dependency file.
---

# Modernize a Python 2 Scientific Stack to Python 3

Apply when the task is porting a legacy Python 2 script that uses NumPy / pandas / matplotlib / scipy / similar to a current Python 3 environment. The script may also read CSVs, parse config files, scrape URLs, and pickle objects.

## Workflow

### 1. Audit Python 2 idioms in the source
Scan for and list every Py2-only construct before editing:
- `print` statements without parentheses → `print(...)`
- `except Exception, e:` → `except Exception as e:`
- `xrange` → `range` (in Python 3, `range` is already lazy)
- `.iteritems()` / `.itervalues()` / `.iterkeys()` → `.items()` / `.values()` / `.keys()`
- `unicode(...)` calls and `u""` prefixes — Python 3 strings are already Unicode; usually just delete
- Integer division: `/` between ints → use `//` if you meant floor, or convert to floats explicitly
- `has_key(...)` → `in`
- `map(...)` / `filter(...)` / `zip(...)` without `list(...)` wrappers if you need a list

### 2. Remap the standard-library imports
Direct rename table (drop-in, no behavior change needed):

| Python 2 | Python 3 |
|---|---|
| `ConfigParser.SafeConfigParser` | `configparser.ConfigParser` |
| `cPickle` | `pickle` |
| `urllib2` | `urllib.request` |
| `StringIO.StringIO` / `cStringIO.StringIO` | `io.StringIO` (text) or `io.BytesIO` (bytes) |
| `future_builtins` | remove — builtins already match |

Keep a module-level `# noqa` only if a linter complains after the rename.

### 3. Fix deprecated pandas / NumPy APIs
Common replacements in scientific code:
- `pd.datetime.strptime(...)` → `pd.to_datetime(...)`, or pass a custom parser via `pd.read_csv(..., parse_dates=[col], date_parser=fn)` / `date_format=...`
- `df.apply(func, axis=1)` over per-row logic → vectorize or use `df.groupby(...).agg(...)` / `df.assign(...)`
- `np.int` / `np.float` / `np.bool` → builtins `int` / `float` / `bool`
- `.ix` indexer → `.loc` (label) or `.iloc` (position)
- `DataFrame.from_csv` → `pd.read_csv`
- `Series.iteritems` → `Series.items`

### 4. Always set `encoding="utf-8"` on text file I/O
Py3 does not default to UTF-8 on Windows and may raise `UnicodeDecodeError` on legacy inputs. Pass `encoding="utf-8"` to:
- `open(...)`, `pd.read_csv(...)`, `configparser.ConfigParser.read(...)`, `pickle.load(...)` (use `encoding="bytes"` if you need Py2-compat)

### 5. Prefer pathlib for paths
- `os.path.join(a, b)` → `Path(a) / b`
- `os.path.basename(p)` → `Path(p).name`
- `os.path.dirname(p)` → `Path(p).parent`
- `os.path.exists(p)` → `Path(p).exists()`
- Open via `with path.open("r", encoding="utf-8") as f:` rather than `open(str(path))`.

### 6. Modernize string formatting
- `"%s = %d" % (k, v)` → f-string `f"{k} = {v}"`
- `"{}".format(x)` → `f"{x}"`
- `.format(**locals())` → f-string with the actual names

### 7. Vectorize instead of looping
When the original iterates over groups/rows in Python, replace with:
- `df.groupby(key)[col].mean()` instead of looping over unique keys
- `df.merge(...)` instead of nested-loop joins
- `np.where(cond, a, b)` instead of branching in a loop

### 8. Validate
Run the modernized script on the same inputs as the original. Compare:
- Output files (diff or `cmp`)
- Numerical results (within `np.allclose` tolerance)
- Print/log output (`print()` calls, exception messages)

If output diverges, suspect encoding (`encoding=` kwarg), division semantics (`/` vs `//`), or dict ordering in iteration.

### 9. Emit a modern dependency file
Choose one:
- `pyproject.toml` with `[project]` table: `name`, `version`, `requires-python = ">=3.9"`, `dependencies = ["numpy>=1.24", "pandas>=2.0", ...]`
- `requirements.txt` with pinned or bounded versions: `numpy>=1.24,<3.0`, `pandas>=2.0`, `matplotlib>=3.7`

Pin minimum compatible versions, not exact ones, so users can resolve transitive deps.

## Quick checklist
- [ ] All Py2 imports remapped
- [ ] All `print` statements are function calls
- [ ] All text I/O specifies `encoding="utf-8"`
- [ ] No `xrange` / `.iteritems()` / `unicode()` / `has_key`
- [ ] All paths via `pathlib.Path`
- [ ] f-strings replace `%` / `.format()`
- [ ] Loops over data replaced with pandas/numpy vectorized ops
- [ ] Script runs and produces equivalent output
- [ ] `pyproject.toml` or `requirements.txt` committed with bounded versions