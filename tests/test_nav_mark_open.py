"""Navigation-open marker records the last-opened entity (issue #146 review).

Search, graph-click, and "Open full editor" navigation open a card by its raw
view flag; they must also record _last_opened_entity so the list view's
single-active resolver prefers the freshly requested card over one left open
elsewhere.
"""

from orionbelt_ontology_builder import app


def test_marks_flag_and_last_opened(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)

    app._mark_view_flag_open("view_ind_abc123")
    assert fake["view_ind_abc123"] is True
    assert fake["_last_opened_entity"] == ("ind", "abc123")


def test_skos_hash_key_and_underscored_uid_preserved(monkeypatch):
    fake: dict = {}
    monkeypatch.setattr(app.st, "session_state", fake)

    app._mark_view_flag_open("view_skos_9f8e7d6c")
    assert fake["_last_opened_entity"] == ("skos", "9f8e7d6c")

    # A key that itself contains underscores stays intact (only kind is split off).
    app._mark_view_flag_open("view_objprop_a_b_c")
    assert fake["view_objprop_a_b_c"] is True
    assert fake["_last_opened_entity"] == ("objprop", "a_b_c")
