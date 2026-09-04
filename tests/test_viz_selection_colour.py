"""A selected node keeps a readable colour (issue #400).

vis-network paints a selected node in its own default highlight — a pale
``#D2E5FF`` fill — for any node that does not name one, and a colour given as an
object inherits nothing from that object's own background. The builder gives
every node a background and a border and nothing else, so clicking one washed
the type colour out from under a near-white label and the label disappeared,
most obviously in dark mode.

Each node now carries the selected state it should have had: its own colour,
moved away from its label.
"""

import json

from streamlit.testing.v1 import AppTest

from orionbelt_ontology_builder.ui import (
    SELECTED_FILL_SHIFT,
    SELECTED_FILL_SHIFT_MAX,
    SELECTED_LABEL_CONTRAST,
    _hex_rgb,
    _luminance,
    add_selection_colours,
    selected_fill,
)

VIS_DEFAULT_HIGHLIGHT = "#D2E5FF"
CLASS_GREEN = "#4CAF50"
NEAR_WHITE = "#f0f0f0"


def _contrast(a, b):
    la, lb = _luminance(_hex_rgb(a)), _luminance(_hex_rgb(b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# --- the colour rule --------------------------------------------------------


def test_a_light_label_darkens_the_fill():
    assert _luminance(_hex_rgb(selected_fill(CLASS_GREEN, NEAR_WHITE))) < _luminance(
        _hex_rgb(CLASS_GREEN)
    )


def test_a_dark_label_lightens_it_instead():
    """The literal nodes are the one place the palette writes in dark ink."""
    lit = "#B0BEC5"
    assert _luminance(_hex_rgb(selected_fill(lit, "#333333"))) > _luminance(
        _hex_rgb(lit)
    )


PALETTE = [
    ("#4CAF50", NEAR_WHITE),  # class
    ("#2196F3", NEAR_WHITE),  # object property
    ("#9C27B0", NEAR_WHITE),  # data property
    ("#FF9800", NEAR_WHITE),  # individual
    ("#795548", NEAR_WHITE),  # annotation
    ("#00897B", NEAR_WHITE),  # SKOS concept
    ("#90A4AE", NEAR_WHITE),  # triple subject
    ("#B0BEC5", "#333333"),  # literal
]


def test_every_label_the_graph_draws_clears_the_target():
    """Every fill the graph uses, against the label it is written in."""
    for fill, label in PALETTE:
        selected = selected_fill(fill, label)
        assert _contrast(label, selected) > _contrast(label, fill), fill
        assert _contrast(label, selected) >= SELECTED_LABEL_CONTRAST, fill
        if label == NEAR_WHITE:
            # The reported case: a near-white label on the pale default is 1.12,
            # which is no contrast at all. (A dark label reads fine on it, which
            # is why the one node written in dark ink was never the complaint.)
            assert _contrast(label, VIS_DEFAULT_HIGHLIGHT) < 1.2


def test_a_fill_that_needs_more_of_a_move_gets_it():
    """The individuals' orange starts far worse off than the class green.

    One shift for both left it at 3.91 while the green cleared 4.5 comfortably,
    which is what the review of PR #403 found. The move now runs until the
    label reads, so the orange simply travels further.
    """
    orange, green = "#FF9800", CLASS_GREEN
    assert _contrast(NEAR_WHITE, orange) < _contrast(NEAR_WHITE, green)

    def moved(fill):
        return _contrast(fill, selected_fill(fill, NEAR_WHITE))

    assert moved(orange) > moved(green)


def test_a_fill_already_dark_enough_only_moves_the_minimum():
    """The target is a floor, not a look: nothing moves further than it must."""
    annotation = "#795548"  # 5.75 unselected, so the floor alone clears it
    assert selected_fill(annotation, NEAR_WHITE) == selected_fill(
        annotation, NEAR_WHITE, shift=SELECTED_FILL_SHIFT
    )


def test_an_unreachable_target_stops_at_the_ceiling():
    """A mid grey under a mid grey label can't get there by darkening alone.

    It takes the best colour within the ceiling rather than running on to black
    and losing the colour the node is recognised by.
    """
    grey = "#7F7F7F"
    capped = tuple(round(c * (1 - SELECTED_FILL_SHIFT_MAX)) for c in _hex_rgb(grey))
    assert _hex_rgb(selected_fill(grey, "#808080")) == capped


def test_the_selected_fill_is_visibly_a_different_colour():
    """Readable is not enough — the click has to show."""
    assert _contrast(CLASS_GREEN, selected_fill(CLASS_GREEN, NEAR_WHITE)) > 1.5


def test_a_colour_it_cannot_read_is_left_alone():
    assert selected_fill("rgba(1, 2, 3, 0.4)", NEAR_WHITE) == "rgba(1, 2, 3, 0.4)"


# --- what the pass writes onto the nodes ------------------------------------


def test_every_node_is_given_its_own_selected_colour():
    nodes = [{"id": "a", "color": {"background": CLASS_GREEN, "border": "#388E3C"}}]
    add_selection_colours(nodes)
    highlight = nodes[0]["color"]["highlight"]
    assert highlight["background"] == selected_fill(CLASS_GREEN, NEAR_WHITE)
    # The border is named too: vis falls back to its own blue for that as well.
    assert highlight["border"] == "#388E3C"


def test_the_node_s_own_label_colour_decides_the_direction():
    nodes = [
        {
            "id": "lit",
            "color": {"background": "#B0BEC5", "border": "#78909C"},
            "font": {"size": 9, "color": "#333333"},
        }
    ]
    add_selection_colours(nodes)
    assert nodes[0]["color"]["highlight"]["background"] == selected_fill(
        "#B0BEC5", "#333333"
    )


def test_a_node_that_names_its_selected_state_keeps_it():
    """A node with validation issues stays ringed in red while selected."""
    nodes = [
        {
            "id": "a",
            "color": {
                "background": CLASS_GREEN,
                "border": "#F44336",
                "highlight": {"border": "#F44336"},
            },
        }
    ]
    add_selection_colours(nodes)
    highlight = nodes[0]["color"]["highlight"]
    assert highlight["border"] == "#F44336"
    assert highlight["background"] == selected_fill(CLASS_GREEN, NEAR_WHITE)


def test_a_node_without_a_colour_object_is_left_alone():
    nodes = [{"id": "a"}, {"id": "b", "color": "#4CAF50"}]
    add_selection_colours(nodes)
    assert nodes == [{"id": "a"}, {"id": "b", "color": "#4CAF50"}]


# --- and on a real graph ----------------------------------------------------


def _script():
    import streamlit as st

    from orionbelt_ontology_builder import app
    from orionbelt_ontology_builder.ontology_manager import OntologyManager

    if "ontology" not in st.session_state:
        om = OntologyManager()
        om.add_class("Bicycle")
        om.add_class("Wheel")
        om.add_object_property("hasPart", domain="Bicycle", range_="Wheel")
        om.add_data_property("serial", domain="Bicycle")
        om.add_individual("bike1", "Bicycle")
        om.add_annotation("Bicycle", "wikidataId", "Q-bike")
        om.add_concept_scheme("Parts")
        om.add_concept("Frame", scheme="Parts")
        st.session_state.ontology = om
        st.session_state["_autosave_restored"] = True
        st.session_state["_viz_settings_restored"] = True
        for kind in ("annotations", "individuals", "data_props", "skos"):
            st.session_state[f"_viz_cfg_show_{kind}"] = True
    app.render_visualization()


def _nodes():
    at = AppTest.from_function(_script)
    at.run(timeout=300)
    assert not at.exception, at.exception
    return json.loads(at.session_state["last_graph_data"]["nodes"])


def test_no_node_of_a_real_graph_falls_back_to_the_pale_default():
    nodes = _nodes()
    # A class, a data property, an individual, an annotation and a concept:
    # every kind that carries a colour of its own.
    assert len({n["color"]["background"] for n in nodes}) >= 5, nodes
    for node in nodes:
        highlight = node["color"]["highlight"]
        assert highlight["background"] != VIS_DEFAULT_HIGHLIGHT, node["id"]
        assert highlight["background"] == selected_fill(
            node["color"]["background"],
            (node.get("font") or {}).get("color") or NEAR_WHITE,
        ), node["id"]
        assert highlight["border"] == node["color"]["border"], node["id"]
