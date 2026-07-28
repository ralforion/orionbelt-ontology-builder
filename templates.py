"""Compatibility shim — re-exports the templates package module."""

from orionbelt_ontology_builder.templates import *
from orionbelt_ontology_builder.templates import (  # noqa: F401
    CACHE_DIR,
    REFERENCE_ONTOLOGIES,
    SAMPLES_DIR,
    TEMPLATES,
    UPPER_ONTOLOGIES,
    _fetch_with_cache,
    get_reference_ontology,
    get_reference_ontology_names,
    get_template,
    get_template_names,
    get_upper_ontology,
    get_upper_ontology_names,
    load_reference_ontology_module,
    load_upper_ontology_module,
    render_template,
)
