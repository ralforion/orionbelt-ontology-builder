"""One number for "triples" wherever the app reports it (issue #263).

Importing a file flashed "(14 triples)" while Quick Stats read "Triples: 12"
for the same ontology at the same moment. Neither was wrong: the message counted
``len(graph)`` and the sidebar counts ``content_triples``, which excludes the
triples hanging off the ontology URI. Shown side by side, the gap reads as data
lost on the way in.

The template and upper/reference loaders already reported the sidebar's number,
so the two import paths were the outliers rather than the rule.
"""

import ast

import sources

from orionbelt_ontology_builder.ontology_manager import OntologyManager

WITH_HEADER = """
@prefix : <http://example.org/imported#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<http://example.org/imported> a owl:Ontology ; rdfs:label "Imported" .
:Vehicle a owl:Class ; rdfs:label "Vehicle" .
:Bicycle a owl:Class ; rdfs:subClassOf :Vehicle .
"""


def test_the_two_counts_really_do_differ():
    """The premise: without a header they agree, which is why this went unseen."""
    om = OntologyManager()
    om.load_from_string(WITH_HEADER, format="turtle")
    stats = om.get_statistics()

    assert stats["total_triples"] - stats["content_triples"] == 2
    assert stats["content_triples"] < len(om.graph)


def _triple_messages() -> list[str]:
    """Every user-facing string that reports a count of "triples"."""
    found = []
    for path in sources.ui_sources():
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if not isinstance(node, ast.JoinedStr):
                continue
            text = "".join(
                str(v.value) for v in node.values if isinstance(v, ast.Constant)
            )
            if "triples" in text.lower():
                found.append(f"{path.name}:{node.lineno} {ast.unparse(node)}")
    return found


def test_no_reported_count_is_the_raw_graph_length():
    """``len(graph)`` counts the ontology header, which the sidebar does not.

    A metric explicitly labelled "Total Triples" may use it — the import
    preview compares whole files — so this looks at the counts presented as
    plain "triples" alongside everything else.
    """
    offenders = [
        message
        for message in _triple_messages()
        if "len(" in message and ".graph)" in message and "Total" not in message
    ]
    assert not offenders, (
        "these report len(graph) where the sidebar reports content triples:\n  "
        + "\n  ".join(offenders)
    )


def test_the_scan_finds_the_messages_it_is_guarding():
    """Otherwise the test above passes by looking at nothing."""
    messages = _triple_messages()
    assert any("imported successfully" in m for m in messages), messages
    assert len(messages) >= 4, messages
