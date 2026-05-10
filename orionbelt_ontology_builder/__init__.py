"""OrionBelt Ontology Builder package.

This package bundles the Streamlit application, the ``OntologyManager`` core,
the ontology / template registries, and all required data files (sample
ontologies, vis-network JS bundle, UI assets) so that ``pip install`` produces
a fully self-contained installation.
"""

from .ontology_manager import OntologyManager, UndoManager

__all__ = ["OntologyManager", "UndoManager"]
