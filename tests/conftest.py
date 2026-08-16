import os

import pytest

from ontology_manager import OntologyManager
from orionbelt_ontology_builder.local_store import ENV_FLAG


@pytest.fixture(autouse=True)
def no_leaked_local_persist():
    """Keep ``ORIONBELT_LOCAL_PERSIST`` from leaking out of one test into the rest.

    The launcher tests call ``cli``/``desktop`` ``main()``, which sets that env
    var to opt the *process* into filesystem persistence, and nothing unset it
    again — so every test that ran later (they sort after ``test_c...``)
    believed it was the desktop app. Anything that then saved a setting saved it
    into the developer's real ``~/.orionbelt_ontology_builder/config.json``,
    which is also where it read from on the next run, so tests polluted each
    other through the home directory.
    """
    before = os.environ.get(ENV_FLAG)
    yield
    if before is None:
        os.environ.pop(ENV_FLAG, None)
    else:
        os.environ[ENV_FLAG] = before


@pytest.fixture
def om():
    """Fresh OntologyManager with default namespace."""
    return OntologyManager()


@pytest.fixture
def populated_om():
    """OntologyManager with a small class/property/individual graph."""
    m = OntologyManager(base_uri="http://test.org/ont#")
    m.add_class("Person", label="Person")
    m.add_class("Organization", label="Organization")
    m.add_class("Employee", parent="Person", label="Employee")
    m.add_object_property("worksFor", domain="Person", range_="Organization")
    m.add_data_property("hasName", domain="Person", range_="string")
    m.add_individual("alice", "Employee", label="Alice")
    m.add_individual("acme", "Organization", label="ACME Corp")
    return m


@pytest.fixture
def skos_om():
    """OntologyManager with a SKOS ConceptScheme and sample concepts."""
    m = OntologyManager(base_uri="http://test.org/ont#")
    m.add_concept_scheme("MyScheme", label="My Scheme")
    m.add_concept("Animal", scheme="MyScheme", pref_label="Animal")
    m.add_concept("Dog", scheme="MyScheme", pref_label="Dog", broader="Animal")
    m.add_concept("Cat", scheme="MyScheme", pref_label="Cat", broader="Animal")
    return m


@pytest.fixture
def patch_ui(monkeypatch):
    """Patch a name on every UI module that binds it.

    ``app.py`` was split into ``ui``, a ``views`` package and the shell, and
    ``from ..ui import X`` binds a *copy* in each importing module. Patching one
    module therefore leaves the others' calls untouched, and these names are
    typically read from several — so a test would silently exercise an
    unpatched half and pass.

    Sets the attribute wherever it exists instead, which is what a test written
    against the single module meant by ``setattr(app, ...)``.
    """
    import importlib

    import sources

    modules = []
    for path in sources.ui_sources():
        rel = path.relative_to(sources.PKG.parent).with_suffix("")
        modules.append(importlib.import_module(".".join(rel.parts)))

    def _patch(name, value):
        for module in modules:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, value)

    return _patch
