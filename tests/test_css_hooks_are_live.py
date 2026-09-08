"""The stylesheet names no hook that cannot match (issue #368 follow-up).

Streamlit's DOM is internal and moves: the 1.62 pin rebuilt the widgets on
react-aria and five ``[data-baseweb=...]`` selectors in :mod:`ui` stopped
matching in silence. The audit for that is to count each hook against a rendered
page, and it only works if a zero means something. Four selectors matched
nothing on any of the app's pages on either pin, so a zero was ambiguous:

* ``.stTabs [data-baseweb="tab"]`` and ``.stTabs [data-baseweb="tab-list"]``,
  for a widget the app stopped using (the sections are ``st.segmented_control``)
* ``[data-testid="stAppViewBlockContainer"]``, the old name for the element the
  same rule already selects as ``.stMainBlockContainer``
* ``footer, [data-testid="stBottom"]``, a footer Streamlit no longer renders and
  a bottom container this app never mounts

These check the ones that can be checked from the source. The rest is the live
count, which is a step in the pin-bump routine rather than a test.
"""

from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "orionbelt_ontology_builder"
UI = (PKG / "ui.py").read_text(encoding="utf-8")


def _package_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(PKG.rglob("*.py")))


def test_the_tab_rules_are_gone_while_the_widget_is():
    """A rule for ``st.tabs`` is only earned by rendering one."""
    if "st.tabs(" in _package_source():
        return  # the widget is back: the rules may come with it
    assert ".stTabs" not in UI


def test_the_block_container_is_named_once_and_currently():
    assert ".stMainBlockContainer" in UI, "the name the element carries today"
    assert "stAppViewBlockContainer" not in UI, "the name it carried before"


def test_no_rule_hides_chrome_that_is_no_longer_drawn():
    assert "stBottom" not in UI
    assert "\n    footer" not in UI
