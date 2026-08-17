"""Selectable language codes for annotations (issue #252).

Two halves: the shipped code tables and the pack helpers, which are plain data
and need no app run; and the session/persistence layer in ``ui``, which is
driven the way ``test_viz_settings.py`` drives the viz settings.
"""

import json

import pytest
from rdflib import Literal

from orionbelt_ontology_builder import app, languages
from orionbelt_ontology_builder.views.annotations import _pack_rows_to_entries


class _FakeLS:
    """Minimal stand-in for the streamlit_local_storage handle."""

    def __init__(self, value=None):
        self._value = value
        self.saved = None

    def getItem(self, _key):
        return self._value

    def setItem(self, _key, value, key=None):
        self.saved = value


# --- the shipped packs ------------------------------------------------------


def test_every_shipped_code_is_a_tag_the_graph_accepts():
    """A code no ontology can carry is worse than no code at all: it is offered
    in a dropdown and then raises out of the write."""
    for pack in languages.BUILTIN_PACKS:
        for entry in languages.builtin_pack(pack):
            assert languages.is_valid_tag(entry["code"]), entry
            Literal("v", lang=entry["code"])  # raises if rdflib disagrees


def test_alpha2_pack_is_the_alpha3_pack_minus_what_iso_639_1_cannot_name():
    a3 = {e["code"]: e["label"] for e in languages.builtin_pack(languages.ALPHA3_PACK)}
    a2 = {e["code"]: e["label"] for e in languages.builtin_pack(languages.ALPHA2_PACK)}
    assert all(len(code) == 2 for code in a2)
    assert len(a3) > len(a2)
    # Same language, same name in both packs — they are projections of one table.
    assert a2["de"] == a3["deu"] == "German"
    # The historical languages are the point of alpha-3, and have no alpha-2.
    assert "grc" in a3 and "ang" in a3


def test_no_pack_lists_a_code_twice():
    for pack in languages.BUILTIN_PACKS:
        codes = [e["code"] for e in languages.builtin_pack(pack)]
        assert len(codes) == len(set(codes))


def test_an_unknown_pack_name_falls_back_rather_than_raising():
    # The active pack is persisted; one deleted since must not take every
    # Language field down with it.
    assert languages.builtin_pack("no such pack") == languages.builtin_pack(
        languages.DEFAULT_PACK
    )


# --- options and codes ------------------------------------------------------


def test_an_option_reads_as_code_and_language_and_resolves_back():
    option = languages.format_option("eng", "English")
    assert option == "eng · English"
    assert languages.code_from_option(option) == "eng"


def test_a_typed_tag_survives_the_round_trip_unchanged():
    # Every Language field still takes a tag no pack lists.
    assert languages.code_from_option("pt-BR") == "pt-BR"
    assert languages.code_from_option("") == ""
    assert languages.code_from_option(None) == ""


@pytest.mark.parametrize("tag", ["de", "grc", "pt-BR", "x-inhouse", "qaa"])
def test_tags_the_graph_takes_are_accepted(tag):
    assert languages.invalid_tag_reason(tag) is None
    Literal("v", lang=tag)


@pytest.mark.parametrize("tag", ["xx1", "en_GB", "1de", "de/at"])
def test_tags_the_graph_refuses_come_back_as_advice(tag):
    reason = languages.invalid_tag_reason(tag)
    assert reason and tag in reason
    with pytest.raises(ValueError):
        Literal("v", lang=tag)


def test_an_empty_tag_is_only_an_error_where_one_is_required():
    # The pack editor needs a code in every row; the annotation forms do not.
    assert languages.invalid_tag_reason("") == "A language code is required."
    assert app.language_tag_error("") is None
    assert app.language_tag_error("  ") is None
    assert app.language_tag_error("xx1")


# --- custom packs -----------------------------------------------------------


def test_normalize_drops_empty_rows_and_refuses_the_rest():
    entries, errors = languages.normalize_pack(
        [
            {"code": "x-old", "label": "House Old Norse"},
            {"code": "", "label": ""},  # the editor's spare row
            {"code": " nor ", "label": " Norwegian "},
        ]
    )
    assert errors == []
    assert entries == [
        {"code": "x-old", "label": "House Old Norse"},
        {"code": "nor", "label": "Norwegian"},
    ]

    _, bad = languages.normalize_pack([{"code": "xx1", "label": "Mine"}])
    assert len(bad) == 1
    _, dupe = languages.normalize_pack(
        [{"code": "nor", "label": "A"}, {"code": "nor", "label": "B"}]
    )
    assert dupe == ["'nor' is listed more than once."]


def test_a_pack_file_round_trips():
    entries = [{"code": "x-a", "label": "A"}, {"code": "x-b", "label": "B"}]
    name, read_back = languages.pack_from_json(languages.pack_to_json("Mine", entries))
    assert (name, read_back) == ("Mine", entries)


def test_a_padded_name_in_a_file_is_read_as_the_name_it_saves_under():
    # Saving strips the name, so an import that kept the padding would check the
    # padded string for a clash and then put a name no pack answers to in use.
    name, _ = languages.pack_from_json(
        '{"name": "  Mine  ", "entries": [{"code": "x-a"}]}'
    )
    assert name == "Mine"


def test_a_bare_list_of_entries_is_read_as_a_nameless_pack():
    name, entries = languages.pack_from_json('[{"code": "x-a", "label": "A"}]')
    assert name == ""
    assert entries == [{"code": "x-a", "label": "A"}]


@pytest.mark.parametrize(
    "text", ["not json", "42", '{"name": "Mine"}', "[]", '[{"code": "xx1"}]']
)
def test_a_file_that_is_not_a_pack_is_refused_with_a_reason(text):
    with pytest.raises(ValueError):
        languages.pack_from_json(text)


def test_an_untouched_editor_cell_does_not_become_the_code_nan():
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(
        [{"Code": "x-a", "Language": None}, {"Code": "x-b", "Language": "B"}]
    )
    assert _pack_rows_to_entries(frame) == [
        {"code": "x-a", "label": ""},
        {"code": "x-b", "label": "B"},
    ]


# --- the session layer ------------------------------------------------------


def test_a_custom_pack_is_offered_after_the_built_in_ones(monkeypatch, patch_ui):
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    assert (
        app.save_custom_language_pack("Mine", [{"code": "x-a", "label": "A"}]) is None
    )
    assert app.language_pack_names() == [*languages.BUILTIN_PACKS, "Mine"]
    assert app.language_pack_entries("Mine") == [{"code": "x-a", "label": "A"}]


def test_a_built_in_pack_cannot_be_shadowed(monkeypatch, patch_ui):
    # The built-ins are the way back to a known list of codes.
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    reason = app.save_custom_language_pack(
        languages.ALPHA2_PACK, [{"code": "x-a", "label": "A"}]
    )
    assert reason and languages.ALPHA2_PACK in reason
    assert app.custom_language_packs() == {}


def test_a_pack_is_refused_whole_when_one_row_is_bad(monkeypatch, patch_ui):
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    reason = app.save_custom_language_pack(
        "Mine", [{"code": "x-a", "label": "A"}, {"code": "xx1", "label": "B"}]
    )
    assert reason and "xx1" in reason
    assert app.custom_language_packs() == {}


def test_an_empty_pack_is_allowed(monkeypatch, patch_ui):
    # What starting a pack from scratch looks like before the first row.
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    assert app.save_custom_language_pack("Mine", []) is None
    assert app.language_pack_entries("Mine") == []


def test_the_active_pack_survives_the_pack_it_names_being_deleted(
    monkeypatch, patch_ui
):
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app.save_custom_language_pack("Mine", [{"code": "x-a", "label": "A"}])
    state[app.ACTIVE_LANG_PACK_KEY] = "Mine"
    assert app.active_language_pack() == "Mine"

    app.delete_custom_language_pack("Mine")
    assert app.active_language_pack() == languages.DEFAULT_PACK
    assert app.language_pack_entries()[0]["code"] != "x-a"


def test_a_stale_saved_pack_name_falls_back(monkeypatch, patch_ui):
    state: dict = {app.ACTIVE_LANG_PACK_KEY: "Deleted last week"}
    monkeypatch.setattr(app.st, "session_state", state)
    assert app.active_language_pack() == languages.DEFAULT_PACK


def test_choosing_a_pack_switches_the_codes_and_is_worth_saving(monkeypatch, patch_ui):
    """Issue #293: one call behind every picker, and the choice is persisted."""
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app.save_custom_language_pack("Mine", [{"code": "x-a", "label": "A"}])
    state.pop("_lang_packs_dirty", None)

    app.set_active_language_pack("Mine")
    assert app.active_language_pack() == "Mine"
    assert app.language_pack_entries() == [{"code": "x-a", "label": "A"}]
    assert state["_lang_packs_dirty"]


def test_choosing_a_pack_that_is_not_one_leaves_the_choice_alone(monkeypatch, patch_ui):
    # A picker only offers pack names, so a name that is not one is a stale
    # value rather than a choice — and it would empty every Language field.
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app.set_active_language_pack(languages.ALPHA2_PACK)
    app.set_active_language_pack("Deleted last week")
    assert app.active_language_pack() == languages.ALPHA2_PACK


def test_a_pack_picker_is_seeded_from_the_pack_in_use(monkeypatch, patch_ui):
    """How the sidebar's picker and the tab's stay one choice (issue #293)."""
    state: dict = {app.ACTIVE_LANG_PACK_KEY: languages.ALPHA2_PACK}
    monkeypatch.setattr(app.st, "session_state", state)
    assert app.seed_language_pack_picker("a_picker") == languages.ALPHA2_PACK
    assert state["a_picker"] == languages.ALPHA2_PACK

    # And a pack that has gone is resolved to one the options include, rather
    # than left as a selectbox value with no matching option.
    state[app.ACTIVE_LANG_PACK_KEY] = "Deleted last week"
    assert app.seed_language_pack_picker("a_picker") == languages.DEFAULT_PACK
    assert state["a_picker"] == languages.DEFAULT_PACK


# --- persistence ------------------------------------------------------------


def test_disk_persist_and_restore_roundtrip(monkeypatch, patch_ui, tmp_path):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)

    save_state: dict = {}
    monkeypatch.setattr(app.st, "session_state", save_state)
    app.save_custom_language_pack("Mine", [{"code": "x-a", "label": "A"}])
    save_state[app.ACTIVE_LANG_PACK_KEY] = "Mine"
    app.persist_language_packs()
    stored = json.loads(cfg_file.read_text())[app.LANG_PACKS_KEY]
    assert stored == {
        "active": "Mine",
        "packs": {"Mine": [{"code": "x-a", "label": "A"}]},
    }

    restore_state: dict = {}
    monkeypatch.setattr(app.st, "session_state", restore_state)
    app.restore_language_packs()
    assert restore_state["_lang_packs_restored"] is True
    assert restore_state[app.ACTIVE_LANG_PACK_KEY] == "Mine"
    assert app.language_pack_entries("Mine") == [{"code": "x-a", "label": "A"}]


def test_persist_requires_a_change(monkeypatch, patch_ui, tmp_path):
    # Rendering the sidebar is not a change: on the cloud a reload could
    # otherwise write the defaults over the saved packs before localStorage
    # had answered.
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: True)
    monkeypatch.setattr(app.local_store, "config_file", lambda: cfg_file)
    monkeypatch.setattr(
        app.st, "session_state", {app.ACTIVE_LANG_PACK_KEY: languages.ALPHA2_PACK}
    )
    app.persist_language_packs()
    assert not cfg_file.exists()


def test_browser_restore_retries_until_a_real_value_arrives(monkeypatch, patch_ui):
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(None))
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app.restore_language_packs()
    assert "_lang_packs_restored" not in state


def test_browser_restore_applies_a_real_value(monkeypatch, patch_ui):
    saved = json.dumps(
        {"active": "Mine", "packs": {"Mine": [{"code": "x-a", "label": "A"}]}}
    )
    monkeypatch.setattr(app.local_store, "local_persist_enabled", lambda: False)
    patch_ui("_get_local_storage", lambda: _FakeLS(saved))
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app.restore_language_packs()
    assert state[app.ACTIVE_LANG_PACK_KEY] == "Mine"
    assert state[app.CUSTOM_LANG_PACKS_KEY] == {"Mine": [{"code": "x-a", "label": "A"}]}


def test_a_stored_pack_that_no_longer_validates_is_dropped(monkeypatch, patch_ui):
    # Storage is a file (or a browser) the user can edit.
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app._apply_language_packs(
        {
            "active": "Broken",
            "packs": {
                "Broken": [{"code": "xx1", "label": "no"}],
                "Fine": [{"code": "x-a", "label": "A"}],
                "": [{"code": "x-b", "label": "B"}],
                "Junk": "not a list",
                # Started and not filled in yet — savable, so it comes back.
                "Started": [],
            },
        }
    )
    assert set(state[app.CUSTOM_LANG_PACKS_KEY]) == {"Fine", "Started"}
    assert app.active_language_pack() == languages.DEFAULT_PACK


def test_a_stored_pack_cannot_take_a_built_in_pack_s_name(monkeypatch, patch_ui):
    """Saving one is refused, so only an edited config can get one in — and a
    pack under a built-in's name would be used in its place (custom packs are
    looked up first) while the tab still showed it as read-only."""
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app._apply_language_packs(
        {
            "active": languages.ALPHA3_PACK,
            "packs": {languages.ALPHA3_PACK: [{"code": "x-a", "label": "A"}]},
        }
    )
    assert app.custom_language_packs() == {}
    assert app.language_pack_entries() == languages.builtin_pack(languages.ALPHA3_PACK)
    assert app.language_pack_names() == list(languages.BUILTIN_PACKS)


def test_an_empty_pack_is_still_the_active_one_after_a_restart(monkeypatch, patch_ui):
    # It was dropped on restore, which silently reset the pack in use too.
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app._apply_language_packs({"active": "Started", "packs": {"Started": []}})
    assert app.active_language_pack() == "Started"


def test_apply_ignores_anything_that_is_not_a_payload(monkeypatch, patch_ui):
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)
    app._apply_language_packs(None)
    assert state == {}
