# AGENTS.md

Guidance for AI assistants working in this repository.

## What this is

OrionBelt Ontology Builder — a Streamlit application for building, editing, and
managing OWL/SKOS ontologies. The core engine is built on `rdflib`. Hosted demo:
https://orionbelt.streamlit.app

## Architecture

The app is an installable Python package (`orionbelt_ontology_builder/`) with
thin top-level shim modules kept for backward compatibility.

```
app.py                  # Streamlit entry point — re-exports package main()
ontology_manager.py     # Backward-compat shim → package module
templates.py            # Backward-compat shim → package module
orionbelt_ontology_builder/
├── app.py              # The shell: nav, sidebar, page dispatch; re-exports the pages
├── ui.py               # Shared UI helpers every page renders through
├── views/              # One module per page (classes, properties, visualization, …)
├── streamlit_entry.py  # Entry script for the console & desktop launchers
├── cli.py, desktop.py  # `orionbelt-ontology-builder[-desktop]` console entry points
├── ontology_manager.py # Core OWL/SKOS engine on rdflib (OntologyManager, UndoManager)
├── templates.py        # Built-in templates, upper & reference ontologies
├── sparql.py           # Read-only SPARQL execution (deadline + row cap)
├── samples/            # Bundled ontologies (gist, gUFO, FOAF, PROV-O, …)
├── lib/                # The graph component (vendored vis-network)
├── assets/             # Logos, screenshots
└── favicon.png
tests/                  # pytest suite (~22 test_*.py files)
```

The page modules live in `views/`, **not** `pages/`: Streamlit treats a `pages`
directory next to an entry script as a legacy multipage app and renders an
automatic sidebar nav from its filenames, which is what issue #269 was. Both
launchers run `streamlit_entry.py` from inside the package, so the name is load
bearing there; `tests/test_no_streamlit_pages_dir.py` guards it.

The real code lives in the **package**. The three top-level shims
(`app.py`, `ontology_manager.py`, `templates.py`) only re-export from it so that
`streamlit run app.py` and existing `from ontology_manager import ...` imports
keep working. When editing logic, edit the package modules — not the shims. If you
add a new public symbol to a package module that the shim re-exports explicitly,
update the shim's import list too.

## Common commands

```bash
# Install (dev)
uv sync --extra dev                      # or: pip install -e ".[dev]"

# Run the app locally
streamlit run app.py                     # opens http://localhost:8501

# Run tests
pytest                                    # testpaths/pythonpath configured in pyproject.toml
pytest tests/test_classes.py -q           # a single file
```

Dependencies: streamlit, rdflib, owlrl, networkx, streamlit-ace. Python >= 3.12.

The floor is 3.12 because that is the oldest runtime CI keeps green, and
because both deployment targets are at or above it (Streamlit Community
Cloud defaults to 3.12, the Docker image ships 3.14). Raising it is a
three-file change guarded by a test: `pyproject.toml`, the README badge,
and the CI matrix in `.github/workflows/ci.yml` must agree, and
`tests/test_python_floor.py` fails if they drift.

## Conventions

- **Never commit to `main`.** Create a `feature/` or `fix/` branch and open a PR.
  Recent history is all squash-merged PRs.
- **Version bumps:** the version lives in `pyproject.toml` (and the README badge).
  Before bumping, grep the entire repo for the old version string so nothing is
  missed.
- Code is reviewed with OpenAI Codex — keep changes clean and minimal.
- Match the surrounding style; add tests under `tests/` for new engine behavior.

## Deployment

Hosted on **Streamlit Community Cloud** at `orionbelt.streamlit.app`, deployed from
this repo (`ralforion/orionbelt-ontology-builder`), branch `main`, entry `app.py`.
A push webhook (`share.streamlit.io/hook`) is meant to rebuild the app on every
push to `main`, but it does not fire reliably: after the v1.21.2 release the
hosted app still served the previous version half an hour later. Treat a manual
**Manage app → Reboot** at share.streamlit.io as part of releasing, and check the
version in the app's sidebar (`APP_VERSION` in `orionbelt_ontology_builder/ui.py`)
rather than assuming a merge to `main` reached the hosted app.
