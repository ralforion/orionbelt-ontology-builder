"""The desktop save path offered by ``ui._download_or_save``.

On the desktop the helper shows a path to save to instead of a download. That
path sits under a fixed key while its file name can change: the Node options
file is named after the ontology, and loading another ontology left the first
one's path in place, so saving the second one's options overwrote the first
one's file (review of PR #534).
"""

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import ui

    ui._download_or_save(
        "Download node options",
        "{}",
        st.session_state.get("name", "first-node-options.json"),
        mime="application/json",
        key="viz_node_file_save_test",
    )


def _app(monkeypatch, tmp_path):
    monkeypatch.setenv("ORIONBELT_LOCAL_PERSIST", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    at = AppTest.from_function(_script)
    at.run()
    return at


def test_an_untouched_path_follows_the_new_file_name(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert at.text_input[0].value == str(
        tmp_path / "Downloads" / "first-node-options.json"
    )

    at.session_state["name"] = "second-node-options.json"
    at.run()

    assert at.text_input[0].value == str(
        tmp_path / "Downloads" / "second-node-options.json"
    )


def test_a_path_the_user_typed_is_kept(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    mine = str(tmp_path / "mine.json")
    at.text_input[0].input(mine).run()

    at.session_state["name"] = "second-node-options.json"
    at.run()

    assert at.text_input[0].value == mine
