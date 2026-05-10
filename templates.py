"""Compatibility shim — re-exports the templates package module."""

from orionbelt_ontology_builder.templates import *  # noqa: F401, F403
from orionbelt_ontology_builder.templates import (  # noqa: F401
    UPPER_ONTOLOGIES,
    REFERENCE_ONTOLOGIES,
    TEMPLATES,
    SAMPLES_DIR,
    CACHE_DIR,
    get_template_names,
    get_template,
    render_template,
    get_upper_ontology_names,
    get_upper_ontology,
    load_upper_ontology_module,
    get_reference_ontology_names,
    get_reference_ontology,
    load_reference_ontology_module,
    _fetch_with_cache,
)
