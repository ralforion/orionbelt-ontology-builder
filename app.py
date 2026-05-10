"""Top-level Streamlit entry point.

Streamlit Cloud (and `streamlit run app.py` locally) executes this file.
The actual application lives in the ``orionbelt_ontology_builder`` package
so it can be installed via ``pip`` together with its data files.

Streamlit re-executes this script on every rerun, so ``main()`` runs
fresh each time even though the package import is cached after the
first run — that's the same model as before, just one indirection deeper.
"""

from orionbelt_ontology_builder.app import main

if __name__ == "__main__":
    main()
