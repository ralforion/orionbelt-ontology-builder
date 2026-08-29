# Third-party notices

OrionBelt Ontology Builder is distributed under the [Business Source License 1.1](LICENSE).
It redistributes the third-party works below. Each is listed with its upstream source, the
licence it is offered under, and where the licence text lives in this repository.

Licence texts are in `orionbelt_ontology_builder/licenses/`, except where a work already
carries its own file next to the data (gist and gUFO do). Everything listed here ships in the
wheel; nothing here is a build-time or development-only dependency.

## Bundled software

| Shipped as | Upstream | Version | Licence | Text |
|---|---|---|---|---|
| `orionbelt_ontology_builder/lib/graph_viewer/vis-network.min.js` | [vis-network](https://visjs.github.io/vis-network/) | 9.1.2 | MIT | [`licenses/MIT-vis-network.txt`](orionbelt_ontology_builder/licenses/MIT-vis-network.txt) |

vis-network is offered under Apache-2.0 **or** MIT, at the recipient's choice. We take MIT.
Copyright (c) 2011-2017 Almende B.V.; (c) 2017-2019 visjs contributors.

## Bundled ontologies and vocabularies

These are sample and reference vocabularies loaded from the Import/Export page. They are
third-party works redistributed unmodified.

| Shipped as | Upstream | Licence | Text |
|---|---|---|---|
| `samples/foaf.rdf` | [FOAF](http://xmlns.com/foaf/spec/) | CC BY 1.0 | [`licenses/CC-BY-1.0.txt`](orionbelt_ontology_builder/licenses/CC-BY-1.0.txt) |
| `samples/goodrelations.owl` | [GoodRelations](http://purl.org/goodrelations/v1) | CC BY 3.0 | [`licenses/CC-BY-3.0.txt`](orionbelt_ontology_builder/licenses/CC-BY-3.0.txt) |
| `samples/pizza.owl` | [Stanford/Manchester pizza](https://protege.stanford.edu/ontologies/pizza/pizza.owl) | CC BY 3.0 | [`licenses/CC-BY-3.0.txt`](orionbelt_ontology_builder/licenses/CC-BY-3.0.txt) |
| `samples/prov-o.ttl` | [W3C PROV-O](https://www.w3.org/TR/prov-o/) | W3C Document License | [`licenses/W3C-Document-License.txt`](orionbelt_ontology_builder/licenses/W3C-Document-License.txt) |
| `samples/wine.owl` | [W3C OWL Guide](https://www.w3.org/TR/owl-guide/) | W3C Document License | [`licenses/W3C-Document-License.txt`](orionbelt_ontology_builder/licenses/W3C-Document-License.txt) |
| `samples/gist/*.ttl` | [Semantic Arts gist](https://github.com/semanticarts/gist) | CC BY 4.0 | `samples/gist/LICENSE-CC-BY-4.0.txt` |
| `samples/gufo/gufo.ttl` | [gUFO](https://nemo-ufes.github.io/gufo/) | CC BY 4.0 | `samples/gufo/LICENSE-CC-BY-4.0.txt` |

Copyright notices, as stated by the works themselves:

- **FOAF** — Copyright © 2000-2014 Dan Brickley and Libby Miller.
- **GoodRelations** — `dcterms:license` in the file names CC BY 3.0.
- **pizza.owl** — `dcterms:license` in the file reads "Creative Commons Attribution 3.0 (CC BY 3.0)".
- **PROV-O** — Copyright © 2011-2013 W3C® (MIT, ERCIM, Keio, Beihang).
- **wine.owl** — published with the OWL Guide, Copyright © 2004 W3C® (MIT, ERCIM, Keio).

`samples/geography-thesaurus.ttl` and `samples/skos-showcase.ttl` are our own work and are
covered by this project's licence.

## Where these terms came from

`foaf.rdf`, `prov-o.ttl` and `wine.owl` state no licence inside the file, so their terms are
taken from the publisher's specification page rather than from the artifact. The FOAF
specification states CC BY 1.0 directly. PROV-O and the OWL Guide carry the standard W3C
document-use rules, which is the W3C Document License. The other files state their licence in
their own metadata, and gist and gUFO ship their licence text alongside the data.

Verified 2026-08-29.

## Python dependencies

Runtime dependencies (streamlit, rdflib, owlrl, networkx, streamlit-local-storage) are
declared in `pyproject.toml` and installed from PyPI. They are not redistributed here, so
their licences are not reproduced. That changes if a bundle ever ships them inside an
artifact, such as the PyInstaller build in issue #54, and this file should be revisited then.
