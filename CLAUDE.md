# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

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
├── app.py              # Streamlit UI (~4k lines, all pages)
├── ontology_manager.py # Core OWL/SKOS engine on rdflib (OntologyManager, UndoManager)
├── templates.py        # Built-in templates, upper & reference ontologies
├── samples/            # Bundled ontologies (gist, gUFO, FOAF, PROV-O, …)
├── lib/                # Vendored frontend libs (vis-network, Tom Select)
├── assets/             # Logos, screenshots
└── favicon.png
tests/                  # pytest suite (~22 test_*.py files)
```

The real code lives in the **package**. The three top-level shims
(`app.py`, `ontology_manager.py`, `templates.py`) only re-export from it so that
`streamlit run app.py` and existing `from ontology_manager import ...` imports
keep working. When editing logic, edit the package modules — not the shims. If you
add a new public symbol to a package module that the shim re-exports explicitly,
update the shim's import list too.

## Common commands

```bash
# Install (dev)
pip install -r requirements.txt          # or: pip install -e ".[dev]"

# Run the app locally
streamlit run app.py                     # opens http://localhost:8501

# Run tests
pytest                                    # testpaths/pythonpath configured in pyproject.toml
pytest tests/test_classes.py -q           # a single file
```

Dependencies: streamlit, rdflib, owlrl, networkx, pyvis. Python >= 3.10.

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
A push webhook (`share.streamlit.io/hook`) auto-rebuilds the app on every push to
`main` — no manual redeploy needed.
