"""The picker whose search ranks by the case you type (issue #468).

The ranking lives in the browser (``lib/case_picker/case_picker.js``), so it is
run under Node, and skipped where Node is not installed. The Python half, what
the page sends and how a pick comes back into session state, runs through
AppTest.
"""

import json
import shutil
import subprocess

import pytest
import sources
from case_pickers import rendered_picker
from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder import case_picker

JS = sources.PKG / "lib" / "case_picker" / "case_picker.js"


def _rank(captions, query, tmp_path):
    """``rankOptions`` from the component, applied to ``captions``."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    module = tmp_path / "case_picker.mjs"
    module.write_text(JS.read_text("utf-8"), "utf-8")
    script = (
        f"import {{ rankOptions }} from {json.dumps(module.as_uri())};"
        f"const captions = {json.dumps(captions)};"
        f"console.log(JSON.stringify("
        f"rankOptions(captions, {json.dumps(query)}).map((i) => captions[i])));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


# In option_sort_key order, as every picker supplies them.
CASE_VARIANTS = ["Class: fn", "Class: fN", "Class: Fn", "Class: FN", "Class: fnord"]


def test_the_case_typed_comes_first(tmp_path):
    """The point of the picker: ``FN`` lists ``FN`` above ``fn``, and the other
    way round, where Streamlit's search listed ``fn`` first for both."""
    assert _rank(CASE_VARIANTS, "FN", tmp_path)[0] == "Class: FN"
    assert _rank(CASE_VARIANTS, "fn", tmp_path)[0] == "Class: fn"
    assert _rank(CASE_VARIANTS, "Fn", tmp_path)[0] == "Class: Fn"


def test_other_cases_follow_in_the_supplied_order(tmp_path):
    """Only the exact case is lifted; the rest keep the app's order, and a
    longer name holding the query as a prefix comes after the whole words."""
    assert _rank(CASE_VARIANTS, "FN", tmp_path) == [
        "Class: FN",
        "Class: fn",
        "Class: fN",
        "Class: Fn",
        "Class: fnord",
    ]


def test_a_whole_word_outranks_a_longer_word_it_starts(tmp_path):
    """The #461 case: searching ``va`` must not put ``value`` above ``va``."""
    captions = ["Class: vl · value", "Class: va · variable"]
    assert _rank(captions, "va", tmp_path)[0] == "Class: va · variable"


def test_letters_in_order_still_match(tmp_path):
    """Streamlit's fuzzy search found ``prsn`` in ``Person``; this one still
    does, below every real substring match."""
    captions = ["Class: Person", "Class: prsn"]
    assert _rank(captions, "prsn", tmp_path) == ["Class: prsn", "Class: Person"]
    assert _rank(captions, "qqq", tmp_path) == []


def test_an_empty_query_lists_everything_in_the_supplied_order(tmp_path):
    assert _rank(CASE_VARIANTS, "", tmp_path) == CASE_VARIANTS


def _picker_script():
    import streamlit as st

    from orionbelt_ontology_builder.case_picker import case_selectbox

    chosen = case_selectbox(
        "Pick",
        ["Class: fn", "Class: FN"],
        key="pick",
        format_func=lambda o: o.ljust(40),
    )
    st.session_state["returned"] = chosen


def test_the_page_sends_unpadded_captions_and_the_seeded_value():
    """Seeding ``st.session_state[key]`` is how the page preselects, and the
    padding meant for Streamlit's scorer is no use to this search."""
    at = AppTest.from_function(_picker_script)
    at.session_state["pick"] = "Class: FN"
    at.run()
    assert not at.exception, at.exception
    data = rendered_picker(at, "pick")
    assert data["options"] == ["Class: fn", "Class: FN"]
    assert data["captions"] == ["Class: fn", "Class: FN"]
    assert data["value"] == "Class: FN"
    assert at.session_state["returned"] == "Class: FN"


def test_a_value_that_is_no_longer_an_option_is_dropped():
    at = AppTest.from_function(_picker_script)
    at.session_state["pick"] = "Class: gone"
    at.run()
    assert not at.exception, at.exception
    assert rendered_picker(at, "pick")["value"] is None
    assert at.session_state["pick"] is None


def test_a_pick_lands_in_session_state_and_calls_on_change(monkeypatch):
    """What the component's change callback does with ``[option, nonce]``."""
    state = {"pick_case_picker": {"value": ["Class: FN", 1]}}
    monkeypatch.setattr(case_picker.st, "session_state", state)
    calls = []
    case_picker._picked("pick", lambda: calls.append(state["pick"]))
    assert state["pick"] == "Class: FN"
    assert calls == ["Class: FN"]

    state["pick_case_picker"] = {"value": [None, 2]}
    case_picker._picked("pick", None)
    assert state["pick"] is None


def test_chosen_options_are_left_out_of_the_list(tmp_path):
    """The multi-picker lists what is still to pick; ranking skips the rest."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    module = tmp_path / "case_picker.mjs"
    module.write_text(JS.read_text("utf-8"), "utf-8")
    script = (
        f"import {{ rankOptions }} from {json.dumps(module.as_uri())};"
        f"console.log(JSON.stringify(rankOptions("
        f"{json.dumps(CASE_VARIANTS)}, 'FN', new Set([3]))));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    # Class: FN (index 3) is chosen, so the other cases lead, in order.
    assert json.loads(result.stdout) == [0, 1, 2, 4]


def _multi_script():
    import streamlit as st

    from orionbelt_ontology_builder.case_picker import case_multiselect

    if st.session_state.get("show", True):
        kwargs = {}
        if st.session_state.get("with_default"):
            kwargs["default"] = ["Class: fn"]
        st.session_state["returned"] = case_multiselect(
            "Pick", ["Class: fn", "Class: FN", "Class: Fn"], key="many", **kwargs
        )


def test_the_multi_picker_keeps_the_picked_order_and_drops_stale_options():
    """The order is what a property chain means, so it is kept as picked."""
    at = AppTest.from_function(_multi_script)
    at.session_state["many"] = ["Class: FN", "Class: gone", "Class: fn"]
    at.run()
    assert not at.exception, at.exception
    data = rendered_picker(at, "many")
    assert data["multi"] is True
    assert data["value"] == ["Class: FN", "Class: fn"]
    assert at.session_state["returned"] == ["Class: FN", "Class: fn"]


def test_a_default_comes_back_once_the_multi_picker_was_away(monkeypatch):
    """As a multiselect's did: an editor left with unsaved picks shows what it
    holds when it is opened again."""
    import streamlit as st

    from orionbelt_ontology_builder import case_picker

    st.session_state.clear()
    monkeypatch.setattr(case_picker, "_mount", lambda *a, **k: None)
    case_picker.new_run()
    assert case_picker.case_multiselect("P", ["a", "b"], key="m", default=["a"]) == [
        "a"
    ]
    st.session_state["m"] = ["a", "b"]  # picked, not saved
    case_picker.new_run()
    assert case_picker.case_multiselect("P", ["a", "b"], key="m", default=["a"]) == [
        "a",
        "b",
    ]
    case_picker.new_run()  # a run elsewhere
    case_picker.new_run()
    assert case_picker.case_multiselect("P", ["a", "b"], key="m", default=["a"]) == [
        "a"
    ]


def test_without_a_default_the_page_owns_the_value(monkeypatch):
    """The graph filters restore their value from saved settings before they
    draw; a picker without a default must not overwrite that on return."""
    import streamlit as st

    from orionbelt_ontology_builder import case_picker

    st.session_state.clear()
    monkeypatch.setattr(case_picker, "_mount", lambda *a, **k: None)
    case_picker.new_run()
    case_picker.new_run()
    st.session_state["m"] = ["b"]  # restored by the page
    assert case_picker.case_multiselect("P", ["a", "b"], key="m") == ["b"]


HARNESS = sources.PKG.parent / "tests" / "case_picker_dom.mjs"


def _drive(steps, tmp_path):
    """Run the component through ``steps`` on a stand-in DOM; one dict per
    ``look`` step with what the field, list and reports showed."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    module = tmp_path / "case_picker.mjs"
    module.write_text(JS.read_text("utf-8"), "utf-8")
    result = subprocess.run(
        [node, str(HARNESS), module.as_uri(), json.dumps(steps)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _data(**overrides):
    data = {
        "label": "Pick",
        "labelVisibility": "visible",
        "help": None,
        "placeholder": "Choose",
        "disabled": False,
        "options": ["a", "b", "c"],
        "captions": ["a", "b", "c"],
        "value": None,
    }
    return {**data, **overrides}


def test_the_keys_still_pick_after_a_rerun_lands_on_an_open_list(tmp_path):
    """A pick reruns the page while the list stays open; the rows drawn before
    that rerun must not be what Enter works on (Codex review of PR #474)."""
    multi = _data(multi=True, selectAll=True, value=[])
    (seen,) = _drive(
        [
            ["render", multi],
            ["focus"],
            ["key", "Enter"],  # the first real option, not "Select all"
            ["render", {**multi, "value": ["a"]}],  # the pick's rerun
            ["key", "Enter"],
            ["look"],
        ],
        tmp_path,
    )
    assert seen["reports"] == [["a"], ["a", "b"]]
    assert seen["chips"] == ["a", "b"]
    assert seen["open"]


def test_a_typed_value_stays_shown_until_the_form_is_submitted(tmp_path):
    """Inside a form the pick only reaches the server on submit, so leaving the
    field, or an unrelated rerun, must not blank what will be submitted."""
    single = _data(acceptNewOptions=True)
    left, rerun, taken_over = _drive(
        [
            ["render", single],
            ["focus"],
            ["type", "pt-BR"],
            ["key", "Enter"],
            ["blur"],
            ["look"],
            ["render", {**single, "label": "Pick again"}],  # the server still has None
            ["look"],
            ["render", {**single, "value": "b"}],  # the server moved on
            ["look"],
        ],
        tmp_path,
    )
    assert left["value"] == "pt-BR" and left["clear"]
    assert rerun["value"] == "pt-BR" and rerun["clear"]
    assert taken_over["value"] == "b"


def test_a_pick_in_a_form_survives_an_unrelated_rerun(tmp_path):
    single = _data()
    (seen,) = _drive(
        [
            ["render", single],
            ["focus"],
            ["type", "c"],
            ["key", "Enter"],
            ["blur"],
            ["render", {**single, "help": "rerun"}],  # the server still has None
            ["look"],
        ],
        tmp_path,
    )
    assert seen["value"] == "c"
    assert seen["reports"] == ["c"]
