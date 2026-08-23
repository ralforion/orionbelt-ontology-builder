"""The details panel's heading links to the whole value (issue #313).

An annotation node draws a label cut to 30 characters so it fits on the node.
The panel headed with that cut label as plain markdown, and Streamlit linkifies
a bare URL — so a cut URL became a link to the cut URL, which opens the wrong
page. The heading text may still be short; the link under it must not be.

The AppTest half uses the same harness as ``test_viz_focus_annotations``: the
real page, seeded through the environment because ``AppTest.from_function`` runs
the script source in a fresh namespace.
"""

import json
import os
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.app import panel_heading_html

URL = "https://webeep.polimi.it/course/view.php?id=123456"
CUT = URL[:30] + "..."

_VIEWER = (
    Path(__file__).resolve().parent.parent
    / "orionbelt_ontology_builder"
    / "lib"
    / "graph_viewer"
    / "index.html"
)


def _script():
    import os

    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Course")
        om.add_annotation("Course", "webeep", os.environ["ANN_VALUE"])
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        # The cross-session settings restore mounts the localStorage component,
        # which blocks forever without a browser to answer it. Mark it done, and
        # pin the panel open rather than inheriting whoever ran the tests.
        st.session_state["_viz_settings_restored"] = True
        st.session_state["_viz_cfg_details_panel"] = True
        st.session_state["_viz_cfg_show_annotations"] = True
        if os.environ["SELECT"] == "1":
            ann = next(
                a
                for a in om.get_annotations(om.namespace + "Course")
                if a["predicate"] == "webeep"
            )
            value = ann["value"]
            st.session_state["_viz_last_selection"] = {
                "selected": True,
                "ntype": "Annotation",
                "ename": app.annotation_ename(om.namespace + "Course", ann),
                "label": value[:30] + "..." if len(value) > 30 else value,
                "flabel": value,
                "title": f"webeep: {value}",
            }

    app.render_visualization()


def _run(select=False, value=URL):
    os.environ["ANN_VALUE"] = value
    os.environ["SELECT"] = "1" if select else "0"
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    return at


# --- the node carries what the panel needs ----------------------------------


def test_the_node_keeps_the_whole_value_behind_its_cut_label():
    nodes = json.loads(_run().session_state["last_graph_data"]["nodes"])
    node = next(n for n in nodes if n.get("ntype") == "Annotation")
    assert node["label"] == CUT
    assert node["flabel"] == URL


def test_every_node_selection_the_viewer_sends_carries_it():
    """A click and a Find & centre both fill the panel, so both payloads need
    it: whichever one forgot would put the cut link back."""
    src = _VIEWER.read_text(encoding="utf-8")
    sites = list(re.finditer(r"(?<!f)label: nd\.label", src))
    assert len(sites) == 2, (
        f"expected 2 node selection payloads, found {len(sites)} — "
        "a new one must send flabel too (issue #313)"
    )
    for site in sites:
        assert "flabel: nd.flabel" in src[site.start() : site.start() + 200], (
            "a selection payload sends the drawn label without the whole one"
        )


# --- the heading ------------------------------------------------------------


def _heading(at):
    headings = [m.value for m in at.markdown if m.value.startswith("<p>")]
    assert headings, "the details panel drew no heading"
    return headings[0]


def test_the_heading_links_the_cut_text_to_the_whole_url():
    """The regression: the heading was the cut label as plain text, which
    Streamlit linkified — href and all — to ``https://webeep.polimi.it/cours``.
    The link is built here now: short text, whole destination."""
    assert _heading(_run(select=True)) == (
        f'<p><strong><a href="{URL}" target="_blank">{CUT}</a></strong></p>'
    )


def test_a_value_that_was_never_cut_reads_the_same():
    short = "https://ex.org/a"
    assert _heading(_run(select=True, value=short)) == (
        f'<p><strong><a href="{short}" target="_blank">{short}</a></strong></p>'
    )


def test_a_value_that_only_starts_with_a_url_is_not_linked_at_all():
    """Prose beginning with a URL has no whole URL to link to, and cutting it
    leaves the same bare-URL text that started this. It is a block of HTML, and
    markdown copies a block through raw — so Streamlit's linkifier never sees
    it. Inline HTML would not do: markdown parses the text between inline tags,
    and the linkifier put its own <a> inside ours."""
    prose = f"{URL} notes"
    heading = _heading(_run(select=True, value=prose))
    assert heading == f"<p><strong>{prose[:30]}...</strong></p>"
    assert "<a" not in heading


def test_the_heading_is_a_block_so_markdown_leaves_it_alone():
    """The whole guard rests on this: an HTML block starts the line."""
    for heading in (
        panel_heading_html("x", "x"),
        panel_heading_html("x", "https://ex.org/x"),
    ):
        assert heading.startswith("<p>")
        assert "\n" not in heading


def test_a_plain_label_is_not_a_link():
    assert panel_heading_html("Course", "Course") == "<p><strong>Course</strong></p>"


def test_a_label_is_escaped_not_rendered():
    """The label is the user's own text, and it lands in HTML."""
    assert panel_heading_html("<i>x</i>", "<i>x</i>") == (
        "<p><strong>&lt;i&gt;x&lt;/i&gt;</strong></p>"
    )
    quoted = panel_heading_html("cut", 'https://ex.org/"onmouseover=alert(1)')
    assert '"onmouseover' not in quoted


def test_only_web_urls_become_links():
    """``javascript:`` is not a destination this heading ever offers."""
    assert "<a" not in panel_heading_html("x", "javascript:alert(1)")
    assert "<a" not in panel_heading_html("x", "ftp://ex.org/x")
