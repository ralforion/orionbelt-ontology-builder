"""Compatibility shim — re-exports the OntologyManager package module.

Existing code (and tests) that imports `from ontology_manager import ...`
keeps working. New code should prefer
`from orionbelt_ontology_builder.ontology_manager import ...`.
"""

from orionbelt_ontology_builder.ontology_manager import *  # noqa: F401, F403
from orionbelt_ontology_builder.ontology_manager import (  # noqa: F401
    IMPORT_REPLACE,
    IMPORT_MERGE,
    IMPORT_MERGE_OVERWRITE,
    OntologyManager,
    UndoManager,
    _SCHEMA,
    _GIST,
    _DOMAIN_INCLUDES,
    _RANGE_INCLUDES,
)
