"""Compatibility shim — re-exports the OntologyManager package module.

Existing code (and tests) that imports `from ontology_manager import ...`
keeps working. New code should prefer
`from orionbelt_ontology_builder.ontology_manager import ...`.
"""

from orionbelt_ontology_builder.ontology_manager import *
from orionbelt_ontology_builder.ontology_manager import (  # noqa: F401
    _DOMAIN_INCLUDES,
    _GIST,
    _RANGE_INCLUDES,
    _SCHEMA,
    IMPORT_MERGE,
    IMPORT_MERGE_OVERWRITE,
    IMPORT_REPLACE,
    PATH_EDGE_KINDS,
    PATH_ENTITY_KINDS,
    PATH_MAX_VISITED,
    SKOSXL,
    OntologyManager,
    PathSearchLimitError,
    UndoManager,
    bfs_path,
)
