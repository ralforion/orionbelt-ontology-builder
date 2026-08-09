"""One module per Streamlit page.

Each page renders on its own and shares nothing with its siblings: they call
into :mod:`orionbelt_ontology_builder.ui` and never into each other, which is
what makes them separable at all. ``app.py`` imports them for the navigation
table and re-exports them, so ``app.render_classes`` still resolves.
"""
