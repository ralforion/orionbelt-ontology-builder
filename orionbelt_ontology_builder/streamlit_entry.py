"""Streamlit entry script used by the console launcher (``cli.run``).

Streamlit executes this file as ``__main__``, so it uses an absolute import of
the package (the package's own ``app.py`` uses relative imports and therefore
cannot be handed to ``streamlit run`` directly). This mirrors the top-level
``app.py`` shim but lives inside the package so the launcher can locate it
reliably via ``Path(__file__)``.
"""

from orionbelt_ontology_builder.app import main

if __name__ == "__main__":
    main()
