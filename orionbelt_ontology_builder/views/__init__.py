"""One module per Streamlit page.

Each page renders on its own and shares nothing with its siblings: they call
into :mod:`orionbelt_ontology_builder.ui` and never into each other, which is
what makes them separable at all. ``app.py`` imports them for the navigation
table and re-exports them, so ``app.render_classes`` still resolves.

Do not rename this package back to ``pages``: ``pages`` is a magic directory
name to Streamlit. When one sits next to the entry script, Streamlit switches
to its legacy multipage mode and renders an automatic sidebar nav built from
the filenames in it (issue #269). The console and desktop launchers run
``streamlit_entry.py`` from this very directory, so they would pick it up. The
pages here are relative-import modules, not standalone scripts, so every entry
in that phantom nav was dead. ``tests/test_no_streamlit_pages_dir.py`` guards
the invariant.
"""
