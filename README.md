# smartdiff_li


Static impact analysis for code changes.

SmartDiff analyzes code changes, builds a dependency graph, and identifies
parts of a codebase that may be affected by a change.

## Features

- [x] Git diff analysis
- [x] AST parsing
- [x] Dependency graph
- [x] Impact analysis
- [x] Risk scoring
- [ ] GitHub Pull Request integration
- [ ] Web dashboard

What makes the diff "smart":

- **Semantic, not textual.** Formatting, comments and import order are ignored. Changes are reported
  per symbol: added, removed, body changed, signature changed, docs only.
- **Breaking vs. compatible signatures.** A new optional parameter is fine; a removed, renamed,
  reordered or newly required parameter is flagged as breaking.
- **Moves and renames.** A function that disappeared from one place and showed up unchanged in another
  is reported as moved, not as a removal plus an addition.
- **Impact analysis.** For every changed symbol, shows who uses it (direct and transitive), following
  imports, re-exports and `self.method()` calls. References that cannot be proven statically are marked `possible`.
- **Broken references.** Removed, renamed or moved symbols (and deleted files) that are still referenced are reported.
- **Risk score** (0-100, low / medium / high / critical) and a list of tests that cover the affected code.

## Supported Languages

Python (3.9+). Other files in the diff are listed but not analyzed.

## Installation

```
pip install -e .
```

No runtime dependencies, only the standard library and `git`. If a C compiler is available, the
C core (`smartdiff_li._core`) is built during installation; without one, installation still succeeds
and SmartDiff falls back to the pure-Python core. `smartdiff --version` shows which core is in use.

## Usage

```
smartdiff diff                      # HEAD vs working tree (including untracked files)
smartdiff diff main                 # main vs working tree
smartdiff diff main feature         # main vs feature
smartdiff diff main..feature        # same
smartdiff diff main...feature       # feature vs merge-base (what a PR would change)
```

Options:

| Option | Description |
| --- | --- |
| `-C, --path DIR` | repository to analyze (default: current directory) |
| `--depth N` | how many levels of callers to follow (default: 3) |
| `--format json` | machine-readable output |
| `--all` | print every impacted symbol, not just the first few |
| `--fail-on LEVEL` | exit with code 2 when risk is `LEVEL` or higher (`medium`, `high`, `critical`), for CI |

Example output:

```
SmartDiff  main..working tree
  1 with semantic changes

RISK  CRITICAL (74/100)
  - removed `app.service.helper`, 2 broken references
  - breaking signature change in `app.service.process`, used by 5 symbols

CHANGES
  app/service.py
    ~ process (function)  signature changed [BREAKING]: removed params: legacy
        <- app.api.handle  app/api.py:7
        <- app.service.Service.run  app/service.py:18  (also changed)
    - helper (function)  removed
        !! app.api.other  app/api.py:13
```

`<-` marks a user of the changed symbol, `!!` a reference that is now broken.

`smartdiff analyze PATH` lists the Python files of a project.

## Architecture

Python parses code and talks to git; the C core stores the dependency graphs and runs the
algorithms on them.

```
smartdiff_li/                     Python
  gitutil.py    changed files and file contents at any revision
  symbols.py    AST -> symbols (functions, classes, variables) with normalized fingerprints
  semantic.py   old vs new symbols -> changes, move detection
  graph.py      resolves imports and references, feeds them to the core as nodes and edges
  analysis.py   ties it together: changes -> impact -> risk
  risk.py       aggregates per-change scores into the overall risk
  report.py     text and JSON output
  cli.py        command line
  core.py       entry point to the core: C extension if built, otherwise _pycore.py
  _pycore.py    pure-Python core with the same API

csrc/                             C11, no dependencies
  sd_core.h     core API
  graph.c       reverse dependency graph, breadth-first impact tracing with certainty
  signature.c   breaking vs. compatible signature changes
  risk.c        per-change risk score and risk levels
  pymodule.c    CPython bindings (smartdiff_li._core)
  test_core.c   C unit tests
```

The core exposes a small API (`Graph.add_edge`, `Graph.trace`, `Graph.reachable`,
`signature_break`, `change_score`, `level_for`). Both implementations are tested against each
other on random inputs, and the whole test suite runs once per core. Set
`SMARTDIFF_PURE_PYTHON=1` to force the Python core.

## Limitations

The analysis is static and name-based. It does not infer types, so `obj.method()` on an arbitrary
object is matched by attribute name (reported as `possible`), and local variables that shadow
imported names are not tracked. Dynamic features (`getattr`, `importlib`, decorators that
change signatures) are invisible to it. Treat the output as a map of where to look, not as proof.

## Development

```
python -m venv .venv && .venv/bin/pip install -e '.[dev]' setuptools
make ext PYTHON=.venv/bin/python     # build the C extension in place
make test PYTHON=.venv/bin/python    # C unit tests + pytest (both cores)
make test-c-asan                     # C unit tests under AddressSanitizer and UBSan
```

## License

MIT
