"""Navigation-open helpers set the single active-card value (issue #147).

Search, graph-click, and "Open full editor" navigation open a card directly
rather than through the View/Edit button callbacks. Since issue #147 that means
writing the one ``active_{kind}`` value, so the freshly requested card always
wins over one left open elsewhere (no per-item flag to shadow it).
"""

from orionbelt_ontology_builder import app


def test_open_entity_sets_active_value(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)

    app._open_entity("ind", "abc123")
    assert fake["active_ind"] == ("abc123", "view")
    assert app._get_active("ind") == ("abc123", "view")
    assert app._is_open("ind", "abc123")
    assert app._is_open("ind", "abc123", "view")
    assert not app._is_open("ind", "abc123", "edit")
    assert not app._is_open("ind", "other")


def test_open_entity_overwrites_any_prior_open_card(monkeypatch):
    fake: dict = {"active_ind": ("stale", "edit")}
    monkeypatch.setattr(app.st, "session_state", fake)

    app._open_entity("ind", "fresh")
    # One value, so the fresh request fully replaces the stale one.
    assert fake["active_ind"] == ("fresh", "view")
    assert app._get_active("ind") == ("fresh", "view")


def test_nav_open_entity_maps_display_type_to_kind(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)

    app._nav_open_entity("Individual", "abc123")
    assert fake["active_ind"] == ("abc123", "view")

    # A uid that itself contains underscores stays intact.
    app._nav_open_entity("Object Property", "a_b_c")
    assert fake["active_objprop"] == ("a_b_c", "view")


def test_nav_open_entity_skos_keys_by_uri_hash(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)

    uri = "http://example.org/concepts/Dog"
    expected = str(abs(hash(uri)))[:8]
    app._nav_open_entity("SKOS Concept", "unused_uid", uri)
    assert fake["active_skos"] == (expected, "view")


def test_nav_open_entity_ignores_unknown_type(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)

    app._nav_open_entity("Restriction", "abc123")
    assert fake == {}


def test_get_active_rejects_malformed_values(monkeypatch):
    fake: dict = {"active_class": "not-a-tuple"}
    monkeypatch.setattr(app.st, "session_state", fake)
    assert app._get_active("class") is None

    fake["active_class"] = ("uid", "bogus-mode")
    assert app._get_active("class") is None

    fake["active_class"] = ("uid", "edit")
    assert app._get_active("class") == ("uid", "edit")
