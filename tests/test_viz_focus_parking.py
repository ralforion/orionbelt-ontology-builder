"""Switching an entity type off sets its focus seeds aside (issue #396).

They used to be deleted. The focus block prunes its seeds to what ``focus_targets``
can resolve and writes the pruned list back, and ``focus_targets`` only carries
the types whose switch is on, so unticking Classes destroyed a focus built on
classes. Ticking it back on left the user to rebuild it by hand.

The prune stays as it is: a seed that resolves to nothing cannot be left in play
(the Codex review of PR #336). What changed is that the switch itself, which is
the one place that knows a *switch* is what happened rather than a deletion,
keeps a copy to put back.
"""

import pytest
import sources

from orionbelt_ontology_builder import app, ui

PERSON = "Class: Person"
ORG = "Class: Org"
ALICE = "Individual: alice"


class _State(dict):
    """A session_state stand-in: dict access plus the attribute access ui uses."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - mirrors Streamlit's error
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


@pytest.fixture
def session(monkeypatch):
    state = _State()
    monkeypatch.setattr(ui.st, "session_state", state)
    return state


def _switch_off(
    session, kind="Class", cfg="_viz_cfg_show_classes", wid="viz_show_classes"
):
    session[wid] = False
    ui.viz_show_kind_toggled(cfg, wid, kind)


def _switch_on(
    session, kind="Class", cfg="_viz_cfg_show_classes", wid="viz_show_classes"
):
    session[wid] = True
    ui.viz_show_kind_toggled(cfg, wid, kind)


def test_switching_a_type_off_keeps_its_seeds_to_one_side(session):
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON, ORG]

    _switch_off(session)

    assert session["_viz_cfg_show_classes"] is False
    parked = session[ui.VIZ_PARKED_SEEDS_KEY]["Class"]
    assert parked["seeds"] == [PERSON, ORG]
    assert parked["focus_mode"] is True


def test_switching_it_back_on_restores_the_focus(session):
    """The whole point: the same focus, mode included, without rebuilding it."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON, ORG]

    _switch_off(session)
    # The render prune empties the live seeds while the type is off, and takes
    # the mode with them, which is what the user sees before ticking it back.
    ui.viz_set_focus_seeds([])
    session["_viz_cfg_focus_mode"] = False

    _switch_on(session)

    assert session["_viz_cfg_focus_seeds"] == [PERSON, ORG]
    assert session["_viz_cfg_focus_mode"] is True
    assert session["_viz_settings_dirty"] is True
    assert session[ui.VIZ_PARKED_SEEDS_KEY] == {}


def test_only_the_switched_type_is_parked(session):
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON, ALICE]

    _switch_off(session)

    assert session[ui.VIZ_PARKED_SEEDS_KEY]["Class"]["seeds"] == [PERSON]
    assert "Individual" not in session[ui.VIZ_PARKED_SEEDS_KEY]


def test_seeds_picked_while_a_type_was_off_are_kept(session):
    """What the user chose in the meantime is their current focus, so the
    restored seeds join it rather than replacing it."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]

    _switch_off(session)
    ui.viz_set_focus_seeds([ALICE])

    _switch_on(session)

    assert session["_viz_cfg_focus_seeds"] == [ALICE, PERSON]


def test_a_seed_is_not_restored_twice(session):
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]

    _switch_off(session)
    ui.viz_set_focus_seeds([PERSON])  # the prune left it alone this time

    _switch_on(session)

    assert session["_viz_cfg_focus_seeds"] == [PERSON]


def test_a_restored_seed_carries_no_identity_so_the_prune_can_judge_it(session):
    """A seed comes back with no entry in the label -> id map, which is the state
    of one the user has just picked: the next prune keeps it if it resolves and
    drops it if its entity has gone in the meantime (see viz_set_focus_seeds)."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]
    session["_viz_cfg_focus_seed_ids_by_label"] = {PERSON: "class-person"}

    _switch_off(session)
    ui.viz_set_focus_seeds([])  # the prune drops the seed, and its id with it
    assert session["_viz_cfg_focus_seed_ids_by_label"] == {}

    _switch_on(session)

    assert session["_viz_cfg_focus_seeds"] == [PERSON]
    assert PERSON not in session["_viz_cfg_focus_seed_ids_by_label"]


def test_switching_focus_off_by_hand_forgets_what_was_parked(session):
    """Turning the mode off is a decision about the focus. A type coming back
    afterwards must not switch it on again behind the user."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]
    _switch_off(session)
    ui.viz_set_focus_seeds([])  # the render prune, as in the test above

    session["viz_focus_mode"] = False
    ui.viz_focus_toggle()
    assert ui.VIZ_PARKED_SEEDS_KEY not in session

    _switch_on(session)
    assert session["_viz_cfg_focus_mode"] is False
    assert not session["_viz_cfg_focus_seeds"]


def test_the_focus_reset_forgets_what_was_parked(session):
    """viz_drop_focus_seeds is also the focus half of the reset that runs when
    the linked file changes, and a parked seed names the entities of the file it
    was parked in. Left behind, switching the type back on in the next file
    would restore that label into it, and a restored seed carries no id, so a
    file that happens to have a class of the same name would be focused, and
    saved, as though the user had asked for it (Codex review of PR #397)."""
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [PERSON]
    _switch_off(session)
    assert session[ui.VIZ_PARKED_SEEDS_KEY]["Class"]["seeds"] == [PERSON]

    ui.viz_drop_focus_seeds()

    assert ui.VIZ_PARKED_SEEDS_KEY not in session
    _switch_on(session)
    assert not session.get("_viz_cfg_focus_seeds")


def test_a_type_with_no_seeds_parks_nothing(session):
    session["_viz_cfg_focus_mode"] = True
    session["_viz_cfg_focus_seeds"] = [ALICE]

    _switch_off(session)

    assert not session.get(ui.VIZ_PARKED_SEEDS_KEY)


def test_switching_a_type_off_still_persists_the_setting(session):
    """It is a display switch first; parking rides along with it."""
    session["viz_show_skos"] = False
    ui.viz_show_kind_toggled("_viz_cfg_show_skos", "viz_show_skos", "Concept")
    assert session["_viz_cfg_show_skos"] is False
    assert session["_viz_settings_dirty"] is True


def test_every_focusable_type_switch_goes_through_the_parking_callback():
    """A type whose entities can be focused but whose switch still calls plain
    viz_sync would go on deleting its seeds. Pinned at the source: the page
    cannot be driven this far under AppTest."""
    src = sources.viz_text()
    for cfg_key, kind in (
        ("_viz_cfg_show_classes", "Class"),
        ("_viz_cfg_show_individuals", "Individual"),
        ("_viz_cfg_show_data_props", "Data Property"),
        ("_viz_cfg_show_skos", "Concept"),
    ):
        assert f'"{cfg_key}"' in src
        assert f'"{kind}"' in src
        block = src[src.index(f'"{cfg_key}",') :].split(")", 1)[0]
        assert kind in block, f"{cfg_key} does not name its focus kind"
    assert src.count("on_change=viz_show_kind_toggled") == 4


def test_the_kinds_map_matches_what_the_page_registers():
    """The map keys are the kind words _focus_target labels seeds with. A word
    that drifts here would park nothing and quietly restore nothing."""
    src = sources.viz_text()
    for kind, cfg_key in app.VIZ_FOCUS_SEED_KINDS.items():
        assert (
            f'_focus_target(\n                    "{kind}"' in src
            or f'"{kind}",' in src
        )
        assert cfg_key in src
