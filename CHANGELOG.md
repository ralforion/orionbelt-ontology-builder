# Changelog

All notable changes to OrionBelt Ontology Builder are documented here.
Versions follow [Semantic Versioning](https://semver.org/). Entries before
1.33.0 are the release notes of their version as published on GitHub, so
their sections are named as they were then.

## [Unreleased]

### Added

- **SKOS-XL labels can be written, edited and removed** (#574). A concept's label editor offers `skosxl:prefLabel`, `skosxl:altLabel` and `skosxl:hiddenLabel` beside the plain kinds. Editing a SKOS-XL label's text keeps its resource, so a note or a link on the label stays with it. Removing one deletes the resource and what is said about it, unless another concept shares it. The Add Concept form can write the preferred label as SKOS-XL, and a vocabulary that already labels that way gets that form offered first.
- **Converting a vocabulary between plain SKOS and SKOS-XL** (#574), in the new SKOS-XL section of the SKOS page: every plain label to SKOS-XL, or every SKOS-XL label to the plain label it entails. The second can keep the label resources, adding plain copies for consumers that read plain SKOS only. Each conversion is one undo step.
- **Two SKOS-XL integrity checks** (#574): `xl_literal_form`, a label resource without exactly one literal form (SKOS Reference S52), and `xl_label_disjoint`, a label resource that is also a concept, scheme or collection (S48). Both are errors.
- Search finds a concept by the text of its SKOS-XL preferred and alternative labels (#574).

### Changed

- One preferred label per language holds across both forms (#574): a new `prefLabel` replaces a different one in its language, plain or SKOS-XL. The same text in both forms is one label and stays.
- The `missing_lang` fix re-tags untagged SKOS-XL labels too, in place (#574).
- The editorial `skos_xl_labels` notice is gone (#574). It said SKOS-XL labels could not be edited here.

### Fixed

- Deleting a concept deletes its SKOS-XL label resources, unless another concept shares one (#574). They were left behind as labels of nothing.

## [1.33.0] - 2026-11-18

Talk to your ontology: an AI agent such as Claude can now explain, query and extend the ontology open in your app, while you watch each change arrive.

### Added

- **A local HTTP API and an MCP server** (#572). Install the `api` extra and start the app with `orionbelt-ontology-builder --api`: it serves the ontology open in it on `http://127.0.0.1:8765`, behind a bearer token. `orionbelt-ontology-builder-mcp` gives MCP clients such as Claude Desktop and Claude Code twelve tools on it: eight to ask (overview, find, list, describe, hierarchy, paths between two entities, read-only SPARQL, checks) and four to change (`edit_ontology`, `merge_turtle`, `infer`, `undo_redo`), and the open ontology as Turtle. It finds the app through `~/.orionbelt_ontology_builder/api.json`, which each start writes (owner-only), so it follows a restarted app.
- **Changes an agent makes are safe to review and take back** (#572). A batch of changes is kept whole or not at all, and is one step in the app's Undo history. `dry_run` returns what a change would add and remove without keeping it, and `expected_revision` refuses a change when the ontology moved since the agent read it. The app and the API take turns, so they never change the graph at the same time.
- **The app shows what an agent did** (#572). A toast names each change, for example "add_class Employee (+3 / −0 triples)", and an "Agent changes" list in the sidebar keeps the last ten. The sidebar also shows the API's address and the token file, each with a copy button.
- **Settings from a `.env` file** (#572) for the console launcher and the MCP server: in the directory you start from, then `~/.orionbelt_ontology_builder/.env`. A variable already set wins over the files, and a command-line flag over all. Only `ORIONBELT_*` and `STREAMLIT_*` names are read. `.env.example` lists every setting.

### Changed

- The console launcher reads `.env` files (see above), so a `STREAMLIT_*` setting in a `.env` in the start directory now applies. `streamlit run app.py`, the hosted demo and the desktop app read none.
- The lock file moves starlette, the web framework Streamlit's server runs on, to 1.10.0, and anyio to 4.16.0. The Docker image is built with them.

### Docs

- README: "Talking to your ontology" up front, and "A session with an agent", a walk through a real session in screenshots.
- This changelog, with the notes of every release before it.
- The API is not in the hosted demo or the published Docker image, which runs `streamlit run app.py` without the `api` extra.

## [1.32.1] - 2026-11-17

The list pages get a name filter, and the Dashboard's two check panels stop counting one problem twice.

### New

- **Filter by name on the list pages** (#565). Classes, object and data properties, individuals and SKOS concepts get a filter that matches the name or the label, ignoring case. Plain text matches anywhere. `*` stands for any text and `?` for one character, and then the pattern has to match the whole name: `address*` finds the names that start with "address", `*type` the ones that end with "type".
- **A narrow Page selector** (#565) at the right of the filter row, shown only when the list has more than one page. The Relations and Restrictions lists get the same selector. Changing the filter goes back to page 1, and the caption says how many entries matched.

### Fixed

- **The Dashboard's Validation and Model quality panels no longer count one problem twice** (#564). Validation leaves out a missing label, an unconnected class or a cycle that a quality rule already reports, and a caption under the panel says so. An ontology carrying gist and gUFO used to show 4 warnings under Validation next to 0 under Model quality.
- **Duplicate labels are checked once, per language** (#564). Quality rule Q003 does it; Validation no longer does. The old check ignored the language tag, so a class labelled "Cajun"@en and "Cajun"@pt clashed with itself (15 of pizza's 16 duplicate-label warnings).

### Good to know

- A card opened from the graph or the sidebar search clears a filter that would hide it.
- The Validation tab on Validation & Reasoning no longer lists duplicate labels; they are in the Quality section.
- The Docker image is built with uv 0.13.9 (#569, #570).

## [1.32.0] - 2026-11-12

The Dashboard now opens on an overview of the ontology: what it holds, how well it is documented, the shape of its class hierarchy, and what the checks find. The settings it used to lead with move to a tab of their own.

### New

- **An overview on the Dashboard** (#562). A header card with the ontology's title, IRI, version, triple count and imports, and tiles counting classes, object and data properties, individuals and restrictions (concept schemes and concepts for a SKOS vocabulary). Below them:
  - **Coverage**: how many of the ontology's own classes, properties and concepts have a label and a definition, and how many of its properties have a domain and a range. Labels and definitions are counted as the quality rules count them.
  - **Class hierarchy**: depth, root, leaf and multi-parent classes, and a chart of classes per depth.
  - **Checks**: validation and the model quality rules, with the findings per rule. Up to 10,000 triples they run by themselves after each edit; above that, **Run checks** runs them. **Open Quality** goes to the Quality section, where the same run is already loaded.
  - **Individuals per class** and **label languages**.
- **A Settings tab on the Dashboard** (#562) holds the metadata, imports and namespace prefix forms, as before.

### Good to know

- The Classes tile counts named classes, as the Classes page lists them. The old Dashboard statistics also counted the anonymous classes that unions and complements declare (pizza: 143 instead of 99); the Statistics tab on the Visualization page still does.
- The charts follow the light and dark theme.

## [1.31.3] - 2026-11-12

SPARQL queries on large ontologies run on Oxigraph, and the SPARQL page lets you choose the engine. This completes the large-ontology work.

### Performance

- **SPARQL on a large ontology runs on Oxigraph** (#560). From 20,000 triples, a query runs on Oxigraph in a separate process that is stopped at the time limit, as before. On a 213,000-triple ontology, the "Ancestors at any depth" example went from 10.9 seconds (so it hit the default 10 second limit with no rows) to 1.7 seconds, and "Everything about one resource" from 2.7 to 0.7 seconds. Each query sends the ontology to Oxigraph, which costs about 0.7 seconds at that size, so a query rdflib answers at once is a little slower there.

### New

- **An Engine setting on the SPARQL page** (#560): Automatic (Oxigraph from 20,000 triples, rdflib below), Oxigraph, or rdflib. It is remembered with the row and time limits, and the result says which engine ran.

### Good to know

- Language tags come back as the ontology writes them.
- A query that Oxigraph would answer differently without showing it runs on rdflib, with a line under the result saying why: a REGEX with a backreference or lookaround, `lang()` compared on mixed-case language tags, or a query Oxigraph does not accept.
- Other differences on Oxigraph, listed in the setting's help: numbers come back in canonical form (`1.50` as `1.5`), `"a"` and `"a"^^xsd:string` count as one value, decimal division keeps 18 places instead of 28, and ORDER BY may order labels in different languages differently.

## [1.31.2] - 2026-11-11

Faster loading of large Turtle files, a SKOS concept list that keeps up with edits, and confirmations that no longer push the page down.

### Performance

- **Large Turtle and N-Triples files load faster** (#557). Files are now parsed by Oxigraph wherever its result is exactly rdflib's, and by rdflib otherwise, so a file never loads differently depending on which parser ran. For a 213,000-triple Turtle file, loading went from 3.5 to 2.1 seconds, restoring the recovery snapshot from 3.1 to 2.4 seconds, and Preview Import from 4.6 to 2.9 seconds. Import, merge and compare go through the same path.
- **The SKOS concept list follows edits** (#556). It used to be rebuilt after every change. With 5,000 concepts, the list after an edit now takes 1 ms instead of a 147 ms rebuild, and the per-scheme list and the concept hierarchy no longer rebuild on every change.

### Fixes

- **Confirmations are toasts** (#555). Deleting a class, property, individual, scheme, concept or annotation, importing an ontology, adding or removing a prefix, the language pack actions, quality settings and SHACL shapes confirmed with a banner above the page that pushed what you were looking at down. They now show as toasts. Errors, warnings and notes stay banners, to be read.

### Other

- pyoxigraph is a new dependency (#557). The Docker image carries the licences of the code compiled into it under `/app/licenses/`.

## [1.31.1] - 2026-11-11

A fix for importing large ontologies, found while testing v1.31.0 on the hosted app.

### Fixes

- **Preview Import of a large file** (#553). With an ontology already loaded, previewing an import compared every changed resource in a way that grew with the square of their number: an 11 MB, 273,000-triple file took over two minutes and looked as if nothing happened. It now takes about 6 seconds.
- **The import review stays light** (#553). The list of changes shows the first 300 and says how many more there are; the counts above it still cover them all. It used to draw one line per changed resource, 70,000 for that file.
- **A progress bar for imports** (#553). Import, Preview Import and Apply Import show which step they are on (parsing the file, comparing it with the current ontology, checking for conflicts), with the seconds counting.

## [1.31.0] - 2026-11-11

A release for large ontologies since v1.30.0: reasoning in seconds instead of minutes, in the background and with Cancel; edits that no longer rebuild every list; and pages that ask before putting a whole ontology on screen. Measured on ontologies of up to 213,000 triples.

### Reasoning

- **RDFS in seconds** (#550). RDFS reasoning is computed natively instead of by owlrl, with exactly the same result. On a 43,000-triple ontology it takes 3 seconds instead of over two and a half minutes, and on 213,000 triples about 20 seconds, where owlrl did not finish.
- **RDFS, lean** (#550). A new profile that adds only what the ontology's own terms imply: types from domains, ranges and superclasses, and the closed class and property hierarchies. It leaves out what every RDFS graph implies, such as typing every node an `rdfs:Resource` and every predicate an `rdf:Property`.
- **In the background, with Cancel** (#545). Reasoning runs in a separate process, so the app stays responsive. Progress shows the pass and the time so far, a run stops after 10 minutes, and **Cancel** stops it and leaves the ontology as it was. A finished run is one undo step.
- OWL-RL still runs owlrl. From 20,000 triples the Reasoning tab says that an OWL-RL run can take many minutes (#549, #550).

### Large ontologies

- **Edits no longer rebuild every list** (#548). After an edit, the class, property and individual lists and the statistics are updated entry by entry instead of rebuilt. On 213,000 triples a page reruns in 0.02 to 0.1 seconds after an edit, instead of about 0.6.
- **Visualization with every class selected** (#546). "Select all" in the graph's filter made each rerun check every selected class against all the others: 6 seconds per rerun at 50,000 classes, now 0.4.
- **Source on request** (#549). The Source page writes the Turtle when you click **Generate source**, at any size, and shows it again while the ontology is unchanged. Opening the page no longer serializes the whole ontology.
- **Bulk Edit of annotations** (#549, #551). Past 2,000 resources, the table shows the annotations of the resources whose name or label matches a filter. A long table fills the window down to **Apply Changes**, which stays in view.
- **SKOS concept hierarchy** (#549). Drawn as one text block, like the class hierarchy: it stops at a cycle and shows a concept with two broader concepts once. It used to draw one element per concept, which could take the desktop window down on a large vocabulary.
- From 100,000 triples the sidebar says the ontology is large (#549).

### Saving

- **A faster recovery file** (#545). On the desktop and in local runs, the crash-recovery file is N-Triples (`recovery.nt`), written six times faster than Turtle on a large ontology. It keeps your prefixes, unused ones included. A `recovery.ttl` from an earlier release is read once and then replaced.
- **Browser autosave of a large ontology** (#545, #547). Once an ontology is too large for the browser's storage, an edit no longer pays for a full serialization just to find that out again. It is measured again when an edit may have made it fit.

### App

- **A click waits for the page it interrupts** (#545). Streamlit's fast reruns are off: a click while a page is running is handled when that page reaches its next step, instead of starting a second run beside it. Two runs editing the ontology at once could lose a change.
- **Bulk results as toasts** (#551). A clean result of a bulk add, edit or delete is a toast; one with errors stays a banner, to be read. Bulk Edit and Delete on the Classes, Properties and Individuals pages now confirm at all: their message was lost before.

## [1.30.0] - 2026-10-27

A feature release since v1.29.3, mostly for the graph: SPARQL results on the graph, more routes in the path finder, property colours, the sidebar's tools in fullscreen, Node options as a file, and a text size setting.

### Graph

- **Show a SPARQL result on the graph** (#395). A **Show on graph** button under SELECT, CONSTRUCT and DESCRIBE results opens the graph with the entities the result names ringed in cyan, and the links between entities named in the same row ringed too. A line above the graph says how many are shown, with a **Clear** button.
- **Next-best routes in the path finder** (#353). Up to 5 routes between two entities, shortest first. A **Route** picker chooses which one is drawn; equally short routes are listed together, each with its hop count.
- **The path is drawn through a focus** (#362). In focus mode the path's entities stay on the graph whatever the focus is on, and the focus seeds are left alone.
- **A colour of your own for a property's edges** (#160). A **Colours** popover in Display options gives a property its own colour on every edge that stands for it: its domain/range edge, restrictions on it, assertions between individuals and custom relations. Picking a property zooms the graph to its edges, coloured properties are named in the legend, and the colours are kept with the other graph settings, not written into the ontology.
- **Undo, Redo, search and language pack in fullscreen** (#452). Fullscreen hides the sidebar, so these four now sit in the gap before **Render** while the graph is fullscreen. A search result is found on the graph rather than opened on its page.
- **Save and load the Node options as a file** (#485). A **File** button beside **Paste / copy** downloads the node filter's or the focus's options as JSON, named after the ontology, and loads them back.
- Two data properties sharing a local name across namespaces are now two separate Find options; before, picking either went to the same node.

### App

- **Text size** (#387). A sidebar setting for the app's text and controls: 90%, 100%, 115% or 130%, kept for next time. On the desktop, which has no browser zoom, this is the way to make the app larger.

## [1.29.3] - 2026-10-24

A security and fix release since v1.29.2: Streamlit 1.66.1, which unblocks the Pillow 13 security fixes (#523), and a working SPARQL editor in the desktop app (#524).

### Security updates

- **Pillow 13.0.0.** Fixes 41 advisories published this week, several critical, among them a heap buffer overflow in the JPEG decoder (GHSA-8g5g-8vmr-9782). Streamlit 1.63 capped Pillow below 13, so the fix needed **Streamlit 1.66.1**, which allows it.
- **certifi 2026.10.23.** Drops the emSign root CAs whose intermediate CA keys were compromised.
- **setuptools 84.2.1.**
- The Docker image builds with **uv 0.13.5**, which also removed the affected emSign root from uv's own certificate store (#525).

### SPARQL editor in the desktop app

In the desktop app the SPARQL page's editor never loaded: its frame got a 404 for the whole session. The launcher imported the app's pages before Streamlit was running, so the editor component was never registered. It now loads as in the browser.

## [1.29.2] - 2026-10-14

A fix release since v1.29.1: **Apply Reasoning** now gives the same result however often it is clicked, and shows its progress (#519).

### Reasoning settles on the first click

Clicking **Apply Reasoning** a second time inferred more triples, for example 3117 and then 3215 on PROV-O with OWL-RL Extended. Several causes, all fixed:

- **Unwritable triples.** The reasoner left triples with a literal as subject in the ontology. No RDF format can store them, and the next run read them as datatypes and inferred more nonsense from them. They are now removed. Applying reasoning again to an ontology saved with them cleans them up.
- **An incomplete first pass.** One pass of the reasoner does not infer everything: terms it introduces only get their axioms on the next pass. Reasoning now repeats until nothing new appears, which takes two passes on every bundled sample.
- **Repeated error messages.** For an inconsistent ontology, such as an individual in two disjoint classes, every pass stored the same error message again. Each message is now kept once.
- **Changes beyond the ontology.** OWL-RL Extended changed how literals were parsed for the whole running app, and on the hosted demo for every session, after anyone used it. Reasoning no longer leaves any of that behind.

### Progress while reasoning runs

A progress bar under the button names the pass and the triples inferred so far, cleared when the run ends, like the quality and SHACL checks since v1.29.1.

## [1.29.1] - 2026-10-14

A small release since v1.29.0: the quality and SHACL checks now show their progress, plus the regular dependency updates.

### Progress while the checks run

After clicking **Run Quality Checks** or **Run SHACL check**, nothing on the page changed until the results arrived. On a large ontology, or with OWL RL inference before the generated SHACL check, that takes seconds, and it looked as if the button did nothing (#514).

Both runs now show a progress bar under their button, cleared once the results are in:

- **Quality:** the rule being run, for example "Rule 3 of 18: Duplicate preferred labels…".
- **SHACL:** the shapes being checked against, with a count when more than one source is ticked. Generating the shapes from the model is its own step.

### Dependencies

- uv 0.13.0 in the Docker image (#516).
- ruff 0.17.0 for development (#517).
- GitHub Actions: setup-uv 10.3.0, upload-artifact 7.0.2, download-artifact 8.0.2 (#515).

## [1.29.0] - 2026-10-12

The main change in this release is checking how well an ontology is made, not only whether it is valid. The page is now called **Validation & Reasoning**, with four sections: Validation, Quality, SHACL and Reasoning. Quality runs advisory rules over the model. SHACL checks the data against shapes: your own, built-in sets, or shapes derived from the ontology's own axioms. Also in this release: graph labels that wrap instead of being cut short, and a fix for converting restrictions on a declared object property.

### Model quality

The Quality section runs 22 rules, grouped into metadata, naming, structure and SKOS (#504, #505, #510):

- **Metadata:** missing labels and definitions, placeholder text (TODO, lorem ipsum), unexplained acronyms, vague or circular definitions, missing language tags.
- **Naming:** duplicate labels, labels that differ only by case, a plural or one typo, naming conventions.
- **Structure:** hierarchy cycles, self-referencing and redundant subclass edges, disconnected class islands, opposite properties without `owl:inverseOf`, use of deprecated resources, unused properties.
- **SKOS:** more than one prefLabel per language, broader links without the narrower link back.

Findings are advice, not errors. Each one explains itself, suggests a fix and opens the resource it is about. There is no overall score: the summary counts findings by severity and shows which rules ran.

- **Profiles and rule settings:** start from General ontology, SKOS vocabulary or Strict documentation, then switch rules on or off and change their severity. Settings are kept per ontology, in the browser on the web and in the config file on the desktop, and can be saved to and loaded from a JSON file (#507).
- **Scope:** only the ontology's own resources are checked, unless you include imported vocabularies.
- **Findings table:** filter by severity, rule, kind or text, and select a row for the details, the evidence behind it and Open buttons for the related resources (#507).
- **Suppressions:** mark a finding as deliberate, with the reason. It is hidden and counted, can be shown again, and still appears in exports with its reason. Suppressions are kept with the settings, not in the ontology (#510).
- **Exports:** findings as JSON (with the run's details) or CSV (#507).

On the bundled samples, all rules together take 13 to 38 ms; on a generated ontology of 10,000 classes, about 2.4 s.

### SHACL

Closed-world checks of the data against SHACL shapes, run with pySHACL (#506, #508, #509):

- **Shapes in the ontology** are found and listed, and checked against the rest of the data. Shapes are never validated as data themselves.
- **Add shapes** by pasting or uploading them. They are checked against the SHACL meta-shapes first, then stored in the ontology file as one undo step, or used for a single check without saving.
- **Built-in sets:** the OrionBelt quality policy (the missing-label, missing-definition and one-prefLabel-per-language rules as SHACL), plus SKOS integrity and SKOS best practice shapes from the skohub project (Apache-2.0). Each can be checked against directly or copied into the ontology (#508).
- **Shapes generated from the model:** cardinalities, someValuesFrom, allValuesFrom, hasValue, functional properties and ranges become shapes that check your individuals. Numeric datatypes are checked by value. They are derived fresh for each check and never stored; you can view and save them (#509, closes #498).
- **OWL RL inference first**, for the generated check and on by default: the check sees what the ontology implies, so a value a `hasValue` restriction entails no longer reads as missing. Switch it off to check what is written down.
- Each check runs in its own process with a time limit, `SERVICE` queries are refused, and results can be exported as a SHACL report or as findings.

Export can now write the ontology, its shapes, or both.

### Graph labels

Annotation and literal nodes wrap their value onto two lines at word boundaries instead of cutting it at 30 characters, and a line break in the value no longer leaves the box half empty (#511, #512). The full value is still in the tooltip and the details panel.

### Fixes

- **Restrictions → Custom Relations** with the relation name left at "Same as the property" works when the property is declared as an object property: it is retyped as an annotation property, and an option removes the axioms that stand in the way (#499, #500).

### Dependencies

- **pySHACL** (0.40 or later) is now a dependency, for the SHACL checks.
- urllib3 2.8.0, and the regular minor and patch updates.

## [1.28.0] - 2026-10-05

The main change in this release is custom relations: direct links between resources through a relation you name, as an alternative to restrictions when what you want is to navigate and query a sequence rather than to reason over it. Also new: undo and redo for the graph's Node options, two property-path SPARQL examples, and three fixes to how pickers search.

### Custom relations

A custom relation is a direct link such as `:step1 :nextItem :step2` (#484). The relation is declared as an `owl:AnnotationProperty`, so the ontology stays OWL 2 DL: an object property between two classes would make each class an individual too. Following a sequence is then a plain property path, with no restriction nodes to step through:

```sparql
SELECT ?from ?to WHERE {
  :pnt :nextItem* ?from .
  ?from :nextItem ?to .
}
```

Reasoners give a custom relation no meaning. When you need inference, a restriction is still the right tool, and the two can live side by side.

- **Relations page:** custom relations are listed with the others, with search, edit and delete. A new Custom Relations tab adds one: pick a subject, a relation (an existing one, or type a new name) and an object. Either end can be a class, an individual or a property.
- **Graph:** each link is a solid pink edge labelled with the relation's name, with its own legend entry. Clicking one opens it in the Details panel.
- **SPARQL:** two examples, one listing every custom relation and one following a relation along its sequence.

Nothing marks a triple as a custom relation beyond its shape, so a file written by hand or by another tool is read the same way.

### Converting between restrictions and custom relations

The Custom Relations tab converts in both directions, each as one Undo step:

- **Restrictions → Custom Relations** turns every `someValuesFrom` restriction on a property into a direct link: `A subClassOf (p some B)` becomes `A p B`.
- **Custom Relations → Restrictions** turns the links between classes back into restrictions (#494).

You choose to remove the originals (move) or keep them (copy). Moving there and back under the same name gives back the ontology you started from, so a conversion is safe to try.

OWL 2 DL does not allow one property to be both an annotation property and an object property, so copying needs a different name for the new relation or property. Each picker shows how many links a conversion would make.

### Undo and redo in Node options

The graph's Node options panel has Undo and Redo buttons for changes to the node filters, the focus nodes and focus mode, up to 20 steps (#491). That includes focusing from the canvas and focusing on a path. A class created or renamed since keeps its place, so stepping back through an older change does not hide it.

### Property-path SPARQL examples

Two new starter queries: "Ancestors at any depth" follows `rdfs:subClassOf+`, and "Classes reachable through restrictions" follows `(rdfs:subClassOf/owl:someValuesFrom)+` (#483).

### Picker search fixes

- A whole name now ranks above the same word inside a longer name: `add` lists `add` above `1-cpl-add` (#479).
- A match in an entity's name ranks above the same match in its label, so `sum` lists `sum` above `dg-sum · Digital sum` in the graph's pickers (#486).
- Tab moves on from a picker instead of getting stuck on its option list, so a form's later fields and its submit button can be reached by keyboard (#480).

### Fixed along the way

Deleting a restriction from one class no longer empties it when another axiom, such as an `owl:equivalentClass`, still uses the same restriction.

## [1.27.8] - 2026-09-22

Three changes since v1.27.7. The main one comes from an ontology that uses case to keep names short: search in every entity picker now pays attention to the case you type.

### Pickers rank by the case you type

Streamlit's dropdowns rank a search without regard to case, so names that differ only in case (`fn`, `FN`, `Fn`) always tied, and typing `FN` listed `fn` first (#468).

Every entity picker, single choice and multi-select, now uses a search of its own that runs in the browser:

- a match in the exact case comes first, then the same match in another case, so `FN` lists `FN` first and `fn` lists `fn` first;
- a whole name beats the start of a longer one, which beats a match inside a word;
- the letters in order still match (`prsn` finds `Person`), last, closest first.

Typing costs no round trip to the server, and inside a form a pick still waits for the form's button. Multi-selects keep the order you pick in, which property chains depend on, and "Select all" is never what Enter takes: it is one Up away.

A few things look a little different: picked items in a multi-select sit as chips with their own ×, and the SKOS scheme filters and the Properties domain filters clear to "all" instead of offering an "All" entry. Leaving an editor with an unsaved pick and coming back still shows what the entity holds.

### No more deprecation notices in the console

`st.components.v1.html` is deprecated, and Streamlit logged a notice for it on every rerun, which filled the desktop app's terminal. Both frames that used it now use `st.iframe`.

### Picker help reaches screen readers

A picker's help text is now the field's accessible description, as it already was for the other widgets, rather than only a tooltip.

## [1.27.7] - 2026-09-18

Three changes since v1.27.6, all reported from real use of the graph and the sidebar: two things the app did to your view that you did not ask for, and one thing the search could not find.

### Esc in "Find and centre" clears the pick and nothing else

Pressing Esc to clear the Find picker did two things in one press: the picker dropped its pick, and the page dropped out of fullscreen (#454).

Esc now stays with the control that has a use for it: a text field, an open dropdown, the Find picker. Everything else still leaves fullscreen, including the canvas, the rest of the page, and the controls that make no claim on the key such as the display checkboxes and the depth slider.

One thing to know: after Esc has cleared the pick, focus stays in the picker, so a second Esc will not leave fullscreen either. The Restore button, or a click on the canvas first, is the way out from there.

### Deleting something no longer zooms the graph out

Deleting an annotation from the details panel rebuilt the graph one node lighter, and the view zoomed out to the whole ontology, away from the entity the annotation hung from (#455).

The rebuild used to hold your zoom and pan only when nothing had gone away. It now holds them whenever the view still frames one of the nodes that stayed where it was, which covers a delete of any kind. Measured on FOAF:

| deleted while zoomed to 1.35 | before | after |
|---|---|---|
| an annotation | view drops to 0.73 | unchanged |
| a class, with its annotations and links | view drops | unchanged |
| a data property | view drops | unchanged |

Delete the only thing on screen and the graph still re-frames, since holding the view there would leave you looking at an empty canvas. Turning a node type off while looking at something now keeps the view too, where it used to re-frame.

### Search finds what an entity's annotations say about it

The sidebar search read the name, the label, the SKOS labels and the comment. A definition, a scope note or a `dcterms:description` was not searched, so finding an entity by what it means meant already knowing what it was called (#453).

Search now falls through to the rest of an entity's annotations, ranked below the fields above them so an entity actually named after your query still comes first. In the bundled gist ontology, "monetary" appears in one scope note and nowhere else, and now finds `isAssignmentOf`. Since the name and the label say nothing about the query, the result explains itself on hover:

> Matched **skos:scopeNote**: People, organizations, monetary amounts, equipment can all be assigned.

URI-valued annotations such as `rdfs:isDefinedBy` are left out: they are links rather than something written about the entity, and searching them would answer "foaf" with most of an imported vocabulary.

## [1.27.6] - 2026-09-16

Five changes since v1.27.5. Most came out of the follow-ups on the performance report (#437): two were things the app did to itself over a long session, and the rest were a pick, a click or a drag that did less than it should.

### Enter picks the first match in Annotation Type and the language fields

Typing `com` in "Annotation Type" and pressing Enter made a new annotation type called `com` instead of picking `rdfs:comment` (#447). The same went for every language field: `engl` and Enter made a tag `engl`.

These pickers accept names that are not in the list yet, and in Streamlit 1.63 Enter with nothing highlighted commits the typed text as a new entry. Enter now takes the first match there, the way it already did in the other pickers (#450). A name that matches nothing is still created, and the "Add: ..." row stays one Down away when a new name is what you want.

### The desktop app no longer leaves its server running

The desktop app is two processes: the window, and the Streamlit server it starts. Closing the window stops the server. When the window process died first, at logout, after a webview crash or on a kill, the server lived on with the whole app and ontology in memory, one idle process each time (#437).

The server now watches for the window process and stops itself when it is gone (#448). Checked by killing the window process outright: before, the server kept running and answering on its port; now it exits within a few seconds. Processes left over from earlier versions are not touched and need to be ended by hand.

### A long session no longer grows the page's memory

A small script every page loads, for help texts and keyboard handling, left something behind on every rerun: a page observer that nothing released (#449). Each one kept the previous copy of that script's frame alive, along with the page elements Streamlit had replaced since. Measured in Chromium on the Visualization page, that was a few hundred retained elements per rerun for as long as the tab stayed open, and in the desktop app a webview process that kept growing.

| per rerun | before | after |
|---|---|---|
| retained page elements | 240 to 280 | 0 |
| event listeners | +1 | 0 |

The server side was measured too and does not grow.

### The graph

- **A Ctrl-click reveal applies in one pass.** A focus click used to run the page twice before the new nodes appeared. It now takes effect in the run that carried it, and the prefix list behind every class and annotation name is computed once per change instead of once per name. On a 1,142-class ontology, click to new nodes went from 375 ms to about 200 ms (#446).
- **A drag while the graph settles stays where you put it.** After a change to the visible nodes, the graph ran a short layout pass and then zoomed to fit everything, which undid a pan or zoom made during that pass (#444). A drag or zoom during the settle now switches that fit off; a settle nobody touches fits as before.

## [1.27.5] - 2026-09-15

Three changes since v1.27.4, all from one performance report (#437) and the keyboard trap it turned up on the way (#438). Two of them only reach the desktop app through this release.

### The graph no longer freezes after a rename or a Ctrl-click

Every action in the report changed the set of nodes on the canvas: a rename re-keys the node and its annotation nodes, a Ctrl-click reveal adds nodes. The viewer then pinned the nodes it had already placed and ran a physics pass to settle the new ones, but sized that pass by the whole graph: up to 460 iterations over every node to place a handful. In the desktop app's WebKit view that was the half-second freeze (#440).

The pass is now sized by the number of new nodes, 60 to 200 iterations, and each new node starts beside a neighbour that already has a position, on a sunflower spiral so a hub that reveals hundreds of subclasses spreads them evenly. Measured in Chrome: five new nodes in a 150-node view went from 642 ms to 107 ms, a hub reveal to 500 nodes from 4.6 s to 1.6 s. Fresh layouts from the Render button are unchanged.

### Undo history no longer holds fifty copies of the ontology

Every checkpoint serialised the whole graph to N-Triples and undo parsed it back. On a 5,000-class ontology that was 29 ms per edit and about 112 MB of history per session. The engine's graph now runs on a store that reports every real change to a journal, and the undo history keeps only the diff of each edit: 0.1 ms per checkpoint and 0.1 MB for fifty steps (#439).

Two things got better on the way. Undoing "Add prefix" removes exactly that prefix, where the old restore dropped every custom one, and undoing a load brings the custom prefixes back.

The same journal gives the engine a revision counter, and the entity listings, the statistics and the Turtle export are computed once per revision instead of on every rerun. On the same 5,000-class ontology a Classes page rerun went from 87 ms to 34 ms, Individuals from 163 ms to 36 ms and Source from 340 ms to 6 ms. Above a megabyte of Turtle the Source page waits for a click before rendering.

### Down in a filter lands on the first match

Typing a query in a multiselect puts "Select N matches" first, drawn tinted, so it reads as the current row. Enter already took the first real match, but Down landed on the bulk row, which looked like no change at all, and Enter from there selected every match (#438). The first Down now lands on the first match, the row Enter takes; the bulk row stays one Up away.

### Under the hood

- ruff to 0.16.7, astral-sh/setup-uv to 10.1.0, and the uv stage in the Docker image to 0.12.13.

## [1.27.4] - 2026-09-11

Eight changes, most of them the Visualization page again, and two of them things the app was doing to itself rather than bugs anyone reported.

### An empty 150px block at the foot of every page

The help and Enter wiring added in 1.27.3 rides in a component frame that draws nothing, mounted with `height=0`. That does not give a zero-height frame: Streamlit 1.62 reads a falsy height as "no height given" and falls back to the component default of 150px.

So every page carried an empty block that tall at its foot, and Visualization paid for it twice, because the canvas fits itself to the room left below the controls and the measurement counted the phantom block. At 1600x1000 with gUFO loaded, the reserve came out 217px instead of 44px and the graph came out 329px instead of 508px, with a blank strip under the status bar.

### Edges, curved or straight

The curve on an edge that is the only link between its two nodes is decoration, and it is redrawn on every frame. On a 1058-class ontology from a performance report, 543 of the 549 edges drawn were single links paying for it (#425).

`Edge curves` joins the display options with three settings. **Auto**, the default, curves a graph up to 300 edges and straightens anything above. **Curved** and **Straight** are yours to set at any size.

The threshold counts edges rather than nodes because that is what the curve costs. Measured under a 6x CPU throttle: holding a graph at 200 nodes and varying the edges, the curve added 1.0ms per redraw at 100 edges, 1.7ms at 200, 4.7ms at 400 and 7.4ms at 800; holding the edges at 300 and varying the nodes from 100 to 800, it stayed between 1.6 and 3.9ms with no trend.

Parallel edges keep their curves at every setting. That is what tells them apart, and it is set per edge.

### Find and centre stops rearranging your focus

Picking an entity while "Focus on one node" was on added it to the focus seeds and left it there: through a cleared picker, and through a reload, since the seeds are saved (#423). Every pick added another.

That was how the prune was persuaded to keep the entity in view. The prune now takes the Find target as a seed for that one render, so the target still arrives with the neighbourhood the focus is set to, and clearing the picker forgets it. The note on the Node options label names it while it is there, since the seeds no longer describe everything on the canvas.

### Smaller things

- An edit confirmation clears in two seconds instead of four (#419).
- A help icon sits beside the label it explains. Streamlit pushes it to the far right of the widget, which on the Visualization controls put Node Spacing's help 460px from its own label and 6px from the next one.
- Four CSS selectors that could never match are gone: two for a widget the app stopped using, one renamed by Streamlit years ago, one for chrome that is no longer drawn. A selector that has never matched cannot be told from one that has just stopped matching.

### Under the hood

- The Streamlit pin moves to 1.63.0, which restores Ctrl/Cmd+A in the multiselect filter and stops markdown lists overflowing a narrow container. `select_all=False` goes on the four pickers where selecting everything is not a coherent thing to want.
- ruff to 0.16.6, and the uv stage in the Docker image to 0.12.10.

## [1.27.3] - 2026-09-06

Thirteen changes since v1.27.2. Most of them are the Visualization page, and four of them are the app catching up with what Streamlit 1.62 changed under it.

### An empty block at the foot of every page

The help and Enter wiring added in #412 rides in a component frame that draws nothing, mounted with `height=0`. That does not give a zero-height frame: Streamlit 1.62 reads a falsy height as "no height given" and falls back to the component default of 150px.

So every page carried an empty 150px block at its foot, and Visualization paid for it twice, because the canvas fits itself to the room left below the controls and the measurement counted the phantom block. At 1600x1000 with gUFO loaded, the reserve came out 217px instead of 44px and the graph came out 329px instead of 508px, with a blank strip under the status bar. The frame now goes in a container the CSS takes out of the flow, so it costs the page nothing (#417).

### Enter takes the first match again, and Tab walks field to field

Streamlit 1.62 rebuilt the widgets on react-aria, and two keyboard habits went with it.

Typing into a multiselect and pressing Enter used to insert the first match. On the new widgets nothing was marked as the match and Enter only closed the list, so a picker that had always been type-and-Enter had to be finished with the mouse. Enter takes the first match again (#384).

The help tooltip also became a real button sitting in the tab order, before the field it belongs to, and a clearable selectbox added a Clear cross after it: Add Class went from 5 fields to 21 focus stops. The icons and crosses leave the tab order, which is only honest if the text an icon holds goes somewhere a keyboard reaches, so every `help=` the app passes is now put on the field itself as a description a screen reader reads. Twelve stops, and one Tab from Class Name lands on Label (#383).

### The graph draws what you are looking at

Selecting a class now raises its links, lines and arrowheads alike, over everything they cross. vis draws edges in the order the builder emitted them, so a restriction's arrowhead was always over a relation's for no reason the ontology gives; putting the selection in front answers it without reordering anything (#385).

A selected node also keeps a colour its label can be read on. vis-network's default highlight is a pale near-white wash, and every node the builder makes named a background and a border and nothing else, so every one of them fell back to that default under a near-white label (#400).

The node tooltip is visible again. It was built correctly the whole time and rendered with no styling at all, because the viewer vendors `vis-network.min.js` and the tooltip's rules live in the `vis-network.css` that was never vendored (#415).

And the Triples layer stops restating what the graph already draws. It exists to show what nothing else shows, and it was redrawing every `subClassOf`, `rdf:type` and `rdfs:label` a second time in grey, which made the edges it is actually for the hardest ones to pick out (#414).

### Adding a class above the one you picked

Everything the graph panel created hung below the selection: the class you picked became the parent, the subject, the type. Inserting a class above an existing one meant leaving the graph, adding it on the Classes page and coming back to re-parent the first one.

`Add parent class` closes that. The new class is added alongside whatever parents the selected class already has, not spliced between them, which is what the reporter asked for (#327).

### A subClassOf cycle is reported

Point a class at one of its own descendants and the triple was written with nothing said anywhere. Validation reported the missing labels and no loop, so a cycle could sit in an ontology with only the hierarchy view to show it, and only if you opened it.

It is reported as a warning rather than an error: `A subClassOf B` with `B subClassOf A` is legal OWL that asserts the two classes are equivalent, and a reasoner reads it that way. Usually a modelling slip, occasionally deliberate (#413).

### Smaller things

- Undo and Redo keep the graph's node filters. Narrowing the class filter and pressing Undo used to bring every class back on the canvas (#401).
- Restore keeps where you are, not where you were: everything you panned and zoomed to in the maximised view survives leaving it (#406).
- A focus that leaves no room for its annotations says so, instead of drawing nothing with Annotations ticked (#405).
- A failed SPARQL query puts the engine's message in a code block, where Streamlit gives it a copy button, and shows it verbatim rather than as markdown (#399).

## [1.27.2] - 2026-09-02

Eleven changes, most of them the Visualization page getting out of its own way. Six came from reports by @SuperCowProducts.

### Fullscreen fills the window, not the screen

The graph's fullscreen button did two separate things: it hid the app's chrome so the canvas got the whole page, and it put the browser window into OS fullscreen (#390). Only the first is what the button is for. An ontology gets built alongside other windows, and anyone who does want the screen already has their system's own shortcut for it.

Fullscreen is now the chrome hiding and nothing else. Esc still leaves it, wired up by hand since it no longer comes free with the Fullscreen API, and it survives a rerun with the button reading its state back off the page.

The same button also keeps the graph's controls now (#381). Display options, Find and focus, the path finder, Node options and the details panel all stay reachable, so changing what is drawn no longer means leaving fullscreen and coming back. The page gives the canvas more room while it is there.

### The graph stops interrupting

Every Ctrl/Cmd-click on a node put a message in the corner naming what had just been clicked (#389). It confirmed something you had done on purpose, and it repeated all through a working session.

It was also wrong as soon as you worked at any speed. A toast is shown when its element mounts and Streamlit will not re-show one already on screen, so a second click inside the four seconds a toast lives was dropped: measured, a click on Person at 0.03s put up "Focusing on Class: Person", a click on Department at 1.05s left it saying Person until it faded at 4.09s, and no message for that second click ever appeared. Both clicks had applied.

Nothing was lost by removing it. The canvas redraws to the focus, and the note on the Node options label names the seeds, the depth and what is held back, whether that panel is open or shut, and it keeps up with clicks a second apart.

The messages that report what the app did on its own are all still there: focus ending by itself, entities a filter held back, a modifier-click on something that cannot be focused, and the graph image save.

### Hiding an entity type no longer costs you your focus

Untick Classes with a focus running on classes and the seeds were not set aside, they were deleted. Ticking Classes back on left an empty picker and a focus to rebuild by hand, which is a poor trade for hiding a type to declutter the canvas.

The seeds are now parked and restored, focus mode included. Seeds picked while a type was hidden are kept, and an entity deleted while its type was hidden is still dropped on its return, so the guard that stops a focus being handed to a same-named stranger is untouched.

And a focus that has nothing left to act on says so on the Node options label, rather than only inside a panel that is shut by default.

### The SPARQL page remembers what you were doing

The Plain editor choice, the query, the row limit and the time limit are all kept now, across a page switch and across a reload (#388). They are stored where the Visualization settings and the language packs are stored: the local config file on a run that may write to disk, the browser's localStorage on the cloud.

Streamlit drops a widget's state as soon as the widget stops being rendered, which is why one look at another page used to put the highlighted editor back and reset both limits.

### Smaller things

- Toggling `Display options` or `Path finder` no longer flashes the graph white (#372).
- A highlighted path is drawn whatever the node cap, and says when it is only half drawn (#378, #377).
- The graph's pickers show the label the canvas draws, so what you search for matches what you see (#376).
- The class hierarchy no longer prints every path through the graph, which turned a modest ontology into pages of repetition (#371).

## [1.27.1] - 2026-08-31

Three fixes, all from reports by @SuperCowProducts, and all three are the app being asked to remember or show something it already had.

### The SPARQL editor no longer has to be downloaded to pick an example

Picking one of the worked examples could put up "Your app is having trouble loading the streamlit_ace.streamlit_ace component" (#356). That is Streamlit's message when a component does not report ready within three seconds, and two things line up to cause it.

The highlighted editor takes its text as *initial* content and ignores it afterwards, so the only way to show a different query is to mount a fresh copy — a new iframe, which loads the whole editor again. And Streamlit serves component files with `cache-control: public` and nothing else: no expiry, no validator, so the browser cannot keep what it just downloaded. Every example is a 286 KB fetch. On a desktop connection it finishes unnoticed; on mobile data it does not.

There is now a **Plain editor** toggle beside the Query label. It swaps the highlighted editor for a plain text box: no iframe, nothing to load, nothing to reload when you pick an example. Syntax colouring is what you give up.

Two smaller things went with it: picking an example that is already on screen no longer reloads the editor — and no longer throws away a result that still answers that very query — and the reload is skipped entirely while the plain editor is on.

### Dark mode reads properly again

On a dark background the selected view tab was drawn in the brand navy at 1.48:1 against the page — the one label on the screen that could not be read (#368), while its neighbours sat at 18:1.

Two faults, either of which alone would have done it. The rule meant to lighten it named a Streamlit test id that the button no longer carries, so it matched nothing and said nothing. And the dark styling was switched on by asking Streamlit whether the theme is dark — a question that reports the theme's *base*, so an app themed to a near-black background with no base reports "light" and gets the light styling on a black page.

Both are fixed, and the second one has a second effect: with a custom dark theme the graph canvas was drawn white, because it asked the same question. It follows the background now.

That check also turned up four more rules that had gone quiet — Streamlit 1.62 rebuilt checkboxes, toggles, radios, sliders and multiselect chips, and every selector naming the old markup stopped matching. With them working again the dark theme could reach the filled controls, which needed it: the navy is 1.48:1 against the page, so a button, checkbox or slider thumb barely separated from it.

The dark theme is one blue family now — the same colour on the button, the selected tab, the checkboxes, the radios and the slider, with links and the slider's value a step lighter so they read as text. The selected tab is filled rather than written in the accent: coloured text made it the dimmest of the three tabs, which is backwards for the one that is selected.

Measured against Streamlit's dark background, before and after: the selected tab 1.48:1 -> 5.8:1, and the filled controls 1.48:1 -> 3.3:1, against the 3:1 that WCAG asks of a control and the 4.5:1 it asks of text. Light mode is unchanged.

### The path finder keeps what you picked

Switching the Path finder panel off and on again came back empty (#360). The two pickers are widgets inside the panel, and Streamlit drops a widget's state the moment it stops being drawn, so the pair had to be chosen from scratch every time the panel was reopened. The pair is kept outside the widgets now and put back when they are rebuilt — including the highlight on the canvas. An entity deleted while the panel was closed is forgotten rather than restored.

### Notes

- The plain editor is a per-session choice; the highlighted editor stays the default.
- Nothing in this release changes an ontology, an export, or the graph's own colours.

## [1.27.0] - 2026-08-31

**The graph can answer "how are these two related?"** Pick two entities on the Visualization page and it reports the shortest chain of links between them, hop by hop, and marks it on the canvas (#176, #352). Suggested by @SuperCowProducts.

### The shortest path between two entities

A new panel under the Find / Focus row, with two pickers listing the same entities Find does — classes, individuals and SKOS concepts. The answer comes back as one line naming each link and the direction it was asserted in:

`Class: Role ←subClassOf— Class: Department ←hasDepartment— Class: Organization`

The search is undirected, because the question is how two things are related rather than what points at what. Each link still keeps the direction the ontology states it in, so the line reads it back the way you wrote it.

It runs in the engine over the whole rdflib graph, not over what is on screen. The canvas draws at most 500 nodes, and searching only those would report "no path" on exactly the ontologies where the question is worth asking. Which kinds of link a path may be walked over follows the display toggles, so a path that is found is always made of links the canvas draws.

When the path names entities the current view has no node for — past the cap, or hidden by a filter — the graph says so where it already explains why it is smaller than the ontology, and **Focus on this path** is the way back: focus mode assembles past the render cap and prunes to what you asked for.

A data property is not walkable and appears in neither picker. Its node hangs off its domain class and leads nowhere else, so it can be neither a step in a path nor a useful endpoint.

### A highlighted link keeps its own colour

The first version painted every link on the path yellow, which cost it the one thing its colour was carrying: which kind of link it is. Since the colours are what the graph is scanned by, that traded one piece of information for another (#357).

Now the link is left exactly as it is drawn — same colour, same weight, same dashes — and a ring in the highlight colour is added around it, the way the path's nodes keep their fill and take a coloured border. A dashed link keeps its dashes, so a restriction on the path still reads as a restriction rather than turning solid.

vis-network has no edge equivalent of a border, so the viewer draws the ring itself: it samples the curve vis is drawing each marked link as and strokes a wider line underneath it, before anything else is painted.

### Runs on Streamlit 1.62.0

The pinned Streamlit moves from 1.49.1 to 1.62.0 and pillow to 12.3.0, closing 22 dependency advisories (#363). 1.49.1 capped pillow below 12, so the two could only move together.

Every page was driven on the new release before the pin changed, and the suite passes on Python 3.12 and 3.14 alike.

### Notes

- Every GitHub Action in the workflows is pinned to an immutable commit SHA, with the release workflows verifying the pins before they publish anything (#355).
- The README leads with SPARQL and the SKOS depth (#351), and the licence names the Licensed Work without a stale version in it (#350).

## [1.26.2] - 2026-08-29

**The graph fills the window, and there is no longer a setting that stops it.** Collapsing the Visualization display options is a "give the graph the room" gesture. It did not always give it (#347).

### What was wrong

The canvas was only sized to the window when **Fit to window** was ticked. With it off, the canvas stayed pinned to the **Graph Height** slider, so collapsing the display options band freed about 120 px that the graph would not take, and the reclaimed band became white space above the status bar.

That setting is saved per browser. Once off, it stayed off across every reload, which made it read as a rendering bug rather than a setting. It was also unreachable while the band was collapsed, which is exactly when the wasted space is noticed: the checkbox that explains the behaviour sits inside the panel you just collapsed.

Measured at a 1900x1139 window, band collapsed:

| Fit to window | canvas height | bottom edge |
| --- | --- | --- |
| off | 670, fixed | 980 of 1139, about 120 px of dead space |
| on | 777, fitted | 1087 plus the status bar, at the window bottom |

### What changed

The option is gone rather than taught about the band. A fixed height can only ever leave white space or overflow, and fullscreen already covers wanting more room than the window has.

- the **Fit to window** checkbox and the **Graph Height** slider are removed; the second row of the display options is now Node Spacing and Highlight Issues
- the canvas is always fitted: it measures the room left below the controls and re-measures on every layout shift, including the band collapsing, the details panel opening, a window resize and leaving fullscreen
- a fixed height survives only as the fallback for the one case the viewer cannot measure, a browser that walls the parent window off from the component iframe
- `fit` and `graph_height` are no longer persisted, so a browser holding the old pair neither resurrects the fixed height nor writes the keys again

### Upgrading

No migration. A browser that saved the old fixed-height settings is fitted to the window on first load, and the stale keys drop out the next time settings are saved.

## [1.26.1] - 2026-08-29

**A prefix means what the page says it means.** A query that names an entity by prefix and finds nothing looks exactly like an empty ontology. This release removes one way that happened silently, and tells you what the prefixes actually are so the other way is visible (#345).

### `:` stays bound to the ontology's own namespace

rdflib's `Graph.bind` defaults to `replace=False`, which does not mean "leave the binding alone": when `:` is already bound to a different namespace it keeps the old binding and parks the new one under a generated `default1:`. Nothing raises, so the app went on believing `:` was its namespace while it named someone else's.

Two paths reached that. Loading a file that declares its own `@prefix : <...>` kept the file's binding. Changing the base URI left `:` on the namespace the ontology had just moved away from:

```
base:     http://acme.org/onto#
':'  ->   http://example.org/ontology#      (stale)
SELECT ?p WHERE { :Event ?p ?o }  ->  no rows
```

Both were silent until something read `:` back: entities the editor minted exported as `default1:Thing`, and a `:Thing` in the SPARQL console resolved into the foreign namespace and matched nothing. The empty prefix now belongs to the ontology's namespace by force, since that is the one namespace it can mean without lying. A namespace displaced from `:` keeps a prefix rather than being dropped, so a binding a loaded file declared survives the round trip. Renaming the base URI is the exception: it rewrites every resource into the new namespace, so the old one is abandoned rather than displaced and does not linger in the entity-creation namespace picker.

### The SPARQL page says which namespace a prefix means

A prefixed name pointing at a namespace the ontology does not use is valid SPARQL. It does not fail, it matches nothing. `:Event` against a loaded gUFO is the case in point, where the class is `gufo:Event`.

The page now lists the namespaces that actually hold something, under the editor:

| Prefix | Namespace |
| --- | --- |
| `:` | `http://example.org/ontology#` |
| `gufo:` | `http://purl.org/nemo/gufo#` |
| `time:` | `http://www.w3.org/2006/time#` |

That is the creatable-namespace set rather than every binding, because the graph carries around thirty prefixes rdflib binds by default and a list that long is one nobody reads. A namespace nothing names reads `(none)`, so you know to write it in full. The editor caption says `:` is the ontology's own namespace and that an imported vocabulary keeps its own prefix, and an empty result points at the list, where the explanation usually is.

### Upgrading

No migration. An ontology saved while `:` was mis-bound is repaired on load.

## [1.26.0] - 2026-08-29

**The workbench can be asked questions now.** Until this release, exploring an ontology meant search, the usage and backlink views, and the graph. Every one of those answers a question someone else decided you would ask. This release adds a SPARQL page, so you can ask your own (#343).

### Ask the ontology anything

`SELECT`, `ASK`, `CONSTRUCT` and `DESCRIBE`, run against whatever is loaded. The ontology's own prefixes are already declared, so `owl:Class` and `:Person` work without a `PREFIX` line. Results come back as a table, or as Turtle for the two graph forms, and download as CSV or `.ttl`.

Eight worked examples are one click away, written against prefixes every ontology here has bound so they run as-is: classes and their labels, the class hierarchy, properties with domain and range, individuals by type, classes with no label, triples per predicate, SKOS concepts with their broader terms, and everything about one resource.

The editor highlights SPARQL as you type, with line numbers, folding and bracket matching, and follows the app's light and dark themes.

### It cannot change your ontology

The page runs the four query forms and nothing else. `INSERT`, `DELETE`, `LOAD`, `CLEAR` and `DROP` are refused with a message that says the console is read-only, rather than a parse error that leaves you guessing. Edits keep going through the editor pages, where they are checkpointed and can be undone — which is the point: a query console that could quietly rewrite the graph would put changes outside the undo history that makes the rest of the app safe to experiment in.

Two more are refused for the same reason, that accepting them would mislead:

- **`SERVICE`**, which would have the server open a connection to a host named in your query.
- **`FROM` and `FROM NAMED`**, which name a graph to query instead of this one. There is no such graph here, and the underlying engine does not fail on that — it answers from the loaded ontology anyway. The query looks honoured and the rows look right, so `FROM <somewhere-else>` would hand back this ontology's data under another graph's name with nothing to signal the substitution.

### A runaway query cannot take the app with it

Every query runs under a row limit and a wall-clock time limit, both adjustable on the page. Hitting either is reported rather than hidden: a truncated result says how much you are seeing, and a query stopped by the clock says so and shows whatever it had produced.

The time limit is the one that matters, and it is enforced deep enough to be real. A great many queries produce no first row at all until evaluation finishes — `ORDER BY`, `GROUP BY` and `DISTINCT` for the obvious reason, but also **every query containing a `UNION`**, which is most non-trivial ones. Bounding the rows you read cannot help with any of those, because there are no rows to bound yet. So the limit is enforced against the graph itself, throughout evaluation. A three-way cartesian product under `ORDER BY` that produced nothing at all after eight seconds now stops on schedule, at a cost too small to measure on an ordinary query.

### Notes

Column order for `SELECT *` follows the order your query names its variables, and an explicit projection is never reordered.

This adds one dependency, `streamlit-ace`, for the editor. If it is unavailable the page falls back to a plain monospace editor and everything else works unchanged.

## [1.25.0] - 2026-08-29

**The graph stops deciding things for you.** When there was nothing left to focus on, the page used to quietly pick a class and carry on. When you created an entity, the filter used to decide whether it belonged. This release takes those decisions back, and makes the gestures that got you into a view work for getting out of one too.

### Nothing stands in for what you picked

Focus mode could not be emptied. With the mode on and no seeds, the render filled the picker with the first class alphabetically, so pressing `Clear all` put an arbitrary entity straight back (#335).

That was the visible half. The same substitution ran whenever the saved seeds resolved to nothing on a render: focus a data property, switch `Data Props` off, and the focus moved silently onto the first class. A focus you never chose, arrived at without a click.

Both are gone, and so is the mechanism. Nothing is stood in any more: clearing the picker leaves focus mode, and a focus whose entity is deleted or whose type is switched off ends and says so. Every route out of a focus now lands in the same place, with the whole graph back on screen.

### A click that focuses can unfocus

Ctrl/Cmd-click adds a node to the focus and Alt-click focuses on it alone, but clicking a node that was **already** focused did nothing at all, so the only way out was reaching for the checkbox (#328).

Each modifier now undoes its own action. Ctrl/Cmd-click adds, so on a node it already added it takes it back out, and taking the last one out ends the mode with it. Alt-click sets the focus to exactly one node, so on the node it is already set to, it is the way back out, keeping the seeds so switching focus back on returns you where you were.

Alt-click is deliberately not a general toggle. It states a target rather than accumulating, and in the one case it does alternate, the graph is visibly showing that node's neighbourhood, so which way the click will go is on screen. Every case that changed behaviour here did nothing before.

### New entities, on your terms

Whether a class created while the filter is narrowed should join it turns out to depend on the ontology rather than on taste. Curating twenty classes out of five hundred, one forcing its way in is noise. Building a small ontology class by class, being told every time that what you just made is not on the canvas is friction.

**Auto-show new**, in the Node options panel, is that choice (#326). Off by default, so v1.24.0's behaviour is unchanged. On, entities created from then on join the selection by themselves, and turning it on also takes in whatever `Show new` was already offering. A filter you *cleared* is the exception and stays empty, since it is the one state auto-add could never be undone from.

### Fixed

- **Renaming an entity no longer zooms the graph out** (#329). A rename mints a new URI, and a node is keyed by a hash of it, so the layout cache read the rename as one node leaving and a stranger arriving. At scale 2.4 on a small ontology, renaming a class dropped the view back to 1.0, zooming out of the very thing being renamed.
- **An edit confirmation no longer shoves the page** (#330). `Relation updated!` was drawn above the whole page body, so a confirmation for an edit made in the details panel pushed everything out from under the cursor. Those confirmations float over the page now. Anything worth reading twice, such as a bulk-add summary naming every row that failed, keeps its banner.
- **Focus mode saved from the canvas actually persists.** Switching the mode from a graph click never lifted the gate the settings save is behind, so what was stored went stale against what was on screen.

### A lighter install

`pyvis` is gone. Nothing had imported it since the custom graph component replaced it, and it pulled IPython and its whole tree: **17 packages** leave the install, the container image and any future bundle. Three vendored frontend directories that nothing had loaded since v1.3.1 go with it.

### Licensing

The declared licence is now the SPDX identifier `BUSL-1.1`. The previous value, `BSL-1.1`, is not an SPDX identifier at all, and `BSL-1.0` is the Boost Software License, so the metadata read as a claim about a different licence entirely. It now uses the PEP 639 form.

`THIRD_PARTY_NOTICES.md` maps every redistributed work to its licence, and the texts ship inside the wheel and the sdist. The container image redistributes more than the wheel does, so it now carries streamlit's Apache-2.0 text, which streamlit's own wheel omits.

### Compatibility

**Two behaviour changes, on purpose.** Focus mode can now end by itself when there is nothing left to focus on, where it used to substitute a class; and a modifier-click on an already-focused node now does something where it used to do nothing. Both are announced when they happen.

`pyvis` is no longer installed as a dependency. Nothing in the app used it, but anything relying on it arriving transitively will need to declare it.

### Thanks

Most of this release began as issue reports from [@SuperCowProducts](https://github.com/SuperCowProducts), who has filed the large majority of this project's issues. The filter reconcile behind `Auto-show new` is their code (#326).

---

## [1.24.0] - 2026-08-25

**The graph page keeps the view you built.** A narrowed filter and a chosen focus are views, not accidents, so this release stops overwriting them, lets you write them down and paste them back, and lets you take away what is on screen instead of only reading it.

### A filter you narrowed is a view you built

Creating a class used to add it to the node filter whatever the filter was set to. That is right for the default view and wrong for a curated one: a filter narrowed to a handful of key classes is a view someone built, and a class created afterwards should not force its way into it (#194).

New entities now join only while the filter is showing everything. Nothing extra is stored to know that: the previous render's entity set already says whether anything was being held back.

Restricting it would make a creation invisible, which is the confusion that opened #190, so the page reports it instead. A toast names the entity and the filter hiding it, and a **Show new (N)** button appears beside `Select all` while there is something to show. It adds those entities to the selection rather than replacing it, so the curated view survives, and its list prunes itself: an entity deleted or shown some other way drops out of the offer on its own.

### A focus you can write down

Focus mode gets the node filter's restore-a-view box (#283). Picking seeds out of a long list is slow and a focus worth setting is worth keeping, so focus mode now takes a pasted list and prints the current one back in the same syntax. The button sits where the filter's does, so it does not move when the panel switches between the two modes.

Seeds are written as the names the picker lists. A plain name resolves across every focusable kind, so one pasted list can bring back a class, an individual and a SKOS concept together, and `Class:Person` picks one side when two kinds share a name. Full URIs work as they do in the filter, including for a resource that is legally both a class and a concept: the IRI names both, so pasting it focuses on both, while the two stay separately selectable.

### What is on screen can be taken away

Both places a selection is reported cut it to fit: a node draws a label short enough for the node, and the bar under the graph ellipsises its one line. An annotation's value is usually the thing worth copying and is exactly what those cuts eat, so it could be read but not taken away. There is now a copy button on the canvas for what the selection is called, and one at the end of the status bar for the whole line it reports (#312, #320).

### The card gets out of the way

The Node options card floats over the canvas, so clicking a node left it covering the very graph the click was about while the answer appeared in the panel beside it. Selecting a node or an edge now closes it. Clicking empty canvas leaves it open, since a deselect shows nothing new and there is no reason to undo something you opened (#319).

### Fixed

- **Adding to the graph no longer zooms out to the whole ontology** (#314, #318). A rebuild that only gains nodes kept every placed node pinned and then asked vis to frame the whole graph once physics settled, undoing the viewport the same branch had just restored. Building one subclass after another, the class being worked on was the first thing to leave the screen.
- **A dropdown in a floating panel opens below its input** (#315, #317). The panels are capped with `overflow-y: auto`, and that scrollport is the boundary BaseWeb measures against, so a picker near the bottom of the card flipped its list upwards over the box being typed into.
- **The details panel's link points at the whole value** (#313, #316). An annotation node draws its label cut to 30 characters, and a cut URL linkified into a link to the cut URL, so clicking it opened an address that does not exist.
- **A renamed entity stays in a narrowed filter.** A rename mints a new URI, which a URI-keyed filter reads as a delete plus a create. Harmless while everything new was shown by default, but with the change above it would have dropped the very class you had narrowed the view to and announced it as something you had just created. The filter now follows the same rename notes that keep focus seeds pointing at their entity.
- **Both paste boxes report what they dropped.** Applying a pasted list changes what the view is holding back, which reruns the page, and the warning was drawn on the pass that reran. A partly matching paste applied silently and never said which names it had ignored.

### Compatibility

**One behaviour change, on purpose.** A class created while the node filter is narrowed no longer appears in the graph by itself (#194). The toast and the `Show new` button are there to make that visible rather than silent. A filter showing everything, which is the default and what most sessions are in, behaves exactly as before.

---

## [1.23.0] - 2026-08-21

**SKOS stops being a demo.** A vocabulary can now be checked at the depth its size calls for, repaired where a repair is safe to make, and edited with the labels, notes and metadata SKOS actually has — including the vocabularies that publish their labels as resources rather than literals. On the graph page, the panels stop being paid for out of the canvas.

### Validation that tells an error from an opinion

`validate_skos` checked five things. It now runs **twenty checks in three tiers**, so a large imported vocabulary can be checked for real errors without drowning in advice (#300).

**Errors** always run and are the ones a SKOS consumer will trip over: a missing `prefLabel`, two of them in one language, an empty label, a concept related to itself, a relation to a concept that does not exist, `related` clashing with the hierarchy, a `broader` cycle. **Warnings** are conventions worth following — untagged labels, a label used twice, an orphan, a top concept that also has a `broader`, redundant hierarchy, a mapping that never leaves its own scheme. **Info** is editorial: no scheme, undocumented concepts, associations with no value, disconnected components. The two softer tiers are gated, so a 40,000-concept import can be read for errors alone.

### Seven of them fix themselves

`autofix_skos` repairs one class of issue at a time and reports how many it resolved (#302). **Seven of the twenty-one checks are fixable:** untagged labels, self-relations, dangling relations, top concepts carrying a `broader`, label overlap, redundant hierarchy, and `broader` cycles.

The rest are left alone on purpose. They describe things only an author can settle — what a concept means, which scheme it belongs to — and a wrong report is a nuisance where **a wrong repair is written into your graph**.

### Concepts with the labels SKOS actually has

A SKOS graph holding one untagged `prefLabel` and one `broader` per concept is not worth querying. Concepts are now edited with **language-aware, multi-valued labels and notes** — all three label kinds and all seven documentation properties — plus `notation`, top-concept membership, and mappings into other vocabularies (#298).

A `prefLabel` replaces any existing one carrying the same language tag, per SKOS Reference S14, so the editor cannot create that violation in the first place. Relations can also be **removed**, which was not previously possible: they could be added but never taken back, and removing only the asserted direction would have left the auto-added inverse behind as a half-edge.

### SKOS-XL vocabularies arrive labelled

SKOS-XL makes a label a resource rather than a literal, so statements can be made about the label itself. **AGROVOC and EuroVoc both publish that way.** This app read `skos:prefLabel` only, so such a vocabulary arrived with every concept apparently unlabelled and `missing_prefLabel` reported for each one, at the single severity that cannot be switched off — 40,000 errors, all wrong, about a perfectly valid file (#301).

### Dublin Core on concept schemes

`add_concept_scheme` took a label and a comment. Every published vocabulary carries more than that, and consumers rely on it: AGROVOC, EuroVoc and LCSH all publish `dcterms:title`, `creator`, `license` and dates on the scheme. Twelve fields are now catalogued with the property and the **shape** each is written in — dates as typed literals, licences and creators as IRIs where that is what they are, not everything flattened to a string that would round-trip cleanly and still be wrong (#304).

### A template that passes its own validator

The built-in SKOS Thesaurus template opened with twelve validation issues — six untagged labels, six undocumented concepts. It predated the data-model work, so it demonstrated none of what the editor now supports and taught exactly the habits the validator complains about. It now opens clean, and ships alongside a sample worth copying from (#303).

### The graph page stops paying for its panels

Everything that opened on the Visualization page was paid for out of the canvas: the details panel took a quarter of the width, the reopen toggle took a sliver, and the Node options picker pushed the graph down far enough to squeeze it to its floor. **All three now float over the canvas** as solid cards, and the canvas keeps its full size whatever is open (#310).

The status bar under the graph is pinned to the bottom of the window, so the node you just clicked stays readable while you work (#308).

### Fixed

- **S27 sees a directly asserted `broaderTransitive`** (#306). SKOS makes `related` disjoint with `broaderTransitive`, and the check walked `broader` — which is that closure in every ordinary vocabulary. A vocabulary may assert the transitive property outright, and then the clash was invisible.
- **The focus switch sits outside the panel it swaps** (#307). `Focus on one node` was a click deep inside a collapsed expander while ten display toggles that matter less sat in the open — and it is not a node filter at all: turning it on replaces the very controls it was hidden behind.
- **The pinned status bar no longer eats the canvas's height reserve** (#309). Autofit sizes the canvas by measuring what follows it, and a pinned element reports where it is painted rather than where it sits, so the canvas grew until the bar was drawn on top of the graph.
- **Accent controls keep the brand navy under Streamlit's theme presets** (#308). The presets drop the configured primary colour; `st.toggle` was the one accent widget the override had missed, and it rendered red.
- **Invisible elements stop taking up room.** The browser-storage component and every CSS-only injection each held a slot in the page column's gap grid, which added up to a band of nothing above the graph (#309, #310).

### Compatibility

**Python 3.12 is now the floor** (#299). `requires-python` said 3.10 and the classifiers advertised 3.10 through 3.14, but CI only ever ran 3.12 and 3.14 — two of the five advertised versions were never exercised, and the code already contained syntax that is a `SyntaxError` on 3.11. Both deployment targets are at or above 3.12, and a test now fails if `pyproject.toml`, the README badge and the CI matrix drift apart.

---

## [1.22.0] - 2026-08-17

**Annotations stop being the page you fight.** Language tags are picked rather than recalled, a custom annotation type can be renamed in place, and annotations now address the resource itself rather than a namesake in your own namespace. Focus mode gets the other half of the story: one click to focus a single node, and what it shows keeps its annotations.

### Language codes you pick, not ones you remember

Every Language field (Add Annotation, the annotation editor, the graph panel's annotate form, Add Concept on the SKOS page) was an empty text box you had to type a tag into exactly. They are now searchable pickers over a **language pack**, with options reading `eng · English` so a code can be found by either half. Any BCP 47 tag can still be typed and used as it stands (#252).

Two packs ship built in, projected from one table so a language's alpha-2 and alpha-3 codes cannot drift apart: **ISO 639-3 (alpha-3)**, the default, 228 codes including the historical languages alpha-2 has no code for (`grc`, `ang`, `non`, `sux`, `syc`) and the special-purpose codes (`und`, `mul`, `zxx`, `qaa`); and **ISO 639-1 (alpha-2)**, 184 codes, for an ontology in modern languages only.

**Custom packs** live in a Language Packs tab under Annotations: start one empty or copied from an existing pack, edit its rows in a spreadsheet, import or export it as JSON. Built-in packs are read-only, so there is always a way back to a known list. A pack of your own can be the short list of languages one ontology actually uses, or private codes for a language no standard names.

The pack in use is one choice, not two: the picker in the tab and the one in the sidebar are the same setting, so a pack you build and pick is the pack every Language field draws from, on every page and in the graph panel. Creating or importing a pack puts it in use as well (#293). The choice persists the way the Visualization settings do, to the config file on a desktop run and to localStorage on the cloud.

Two smaller things came with it: a tag rdflib would refuse (`xx1`, `en_GB`) comes back as advice naming the private-use alternatives instead of raising out of the write and taking the page down, and the language now stays put after adding an annotation, so a run of labels in one language needs one pick rather than one per row.

### Rename a custom annotation type

Renaming a custom annotation type used to mean replacing every `ns1:<name>` in the exported Turtle by hand, which only worked as long as the file wrote that type under one prefix. A new **Annotation Types** tab lists the types this ontology defines itself, with how many annotations use each one and a rename per row (#287).

The rename moves every triple that mentions the type: its `owl:AnnotationProperty` declaration, the annotations that use it as their predicate, and any reference to it as an object. It goes through the undo history like every other mutation.

It refuses what it should. A type from another vocabulary is not listed or renameable, because renaming `rdfs:label` forks that vocabulary rather than renaming anything. A name already taken is refused rather than merged, so two types never silently collapse into one. And a bare new name keeps the type in its current namespace: renaming a custom type to `label` mints a local `<base>#label`, it does not fold every value into `rdfs:label`.

### Focus on one node

Ctrl/Cmd-click adds a node to the focus selection, which is what building a neighbourhood out of several nodes needs. Wanting one node at a time is the more common case, and it meant emptying the focus picker by hand between hops. **Alt-click now replaces the focus with the node clicked** (#276). The side panel caption, the status bar under the graph and the README all say what both modifiers do.

### Fixed

- **Annotations address the resource, not its local name.** Adding an annotation resolved the subject through this ontology's own namespace, so annotating an imported class (`gist:Account`) wrote to `:Account`, a subject nothing declares. It looked right, because the page read them back the same way, but the row editor's Save and Delete address the resource by URI and so quietly did nothing to what was listed in front of them. The Add form, the View list, its row delete and the Bulk Edit rows now all address the resource by URI. Where a resource has an undeclared namesake holding annotations written by the old code, the View tab names it and offers to move them across under an undo checkpoint.
- **Focus mode keeps the annotations of what it shows** (#272). The focus prune is a breadth-first walk, and it counted an annotation node as a hop exactly like a class, so focusing on a node drew its neighbours stripped of their annotations with nothing said about why. Annotation edges are now left out of the walk and hung back on afterwards, so the depth counts entity hops.
- **Renaming the entity you are focused on keeps the focus on it** (#275). Focus seeds are held as the labels the picker shows, and a rename mints a new URI, so the seed was pruned as a stale reference and the view jumped to an arbitrary other class. That fallback was then written back over your selection and persisted to the linked file's saved state, so the loss survived a restart.

### Under the hood

A test-suite leak fixed at the source: the launcher tests call `cli`/`desktop` `main()`, which sets `ORIONBELT_LOCAL_PERSIST` for the whole process, and nothing unset it. Every test sorting after it believed it was the desktop app, and the first one to save a setting saved it into the developer's real `~/.orionbelt_ontology_builder/config.json`. An autouse fixture now restores the variable after each test.

---

## [1.21.2] - 2026-08-12

Patch release: a name already used by another kind of entity is refused instead of quietly becoming one resource with two listings.

### Fixed

- **A class named after an existing individual no longer swallows it** (#279). Local names all resolve into one URI, so declaring a class with an individual's name added `owl:Class` to that individual. OrionBelt then listed one resource on both the Classes and the Individuals page, and deleting what looked like the class deleted the individual with it. Every create path now refuses a name another kind of entity owns and explains the clash: the Class, Individual, Object Property, Data Property, Concept and Concept Scheme forms, the Visualization side panel, the bulk add paths, and the `add_*` engine APIs themselves.
- **Ontologies that already carry such a name are reported rather than hidden.** Punning is legal OWL 2 and files arrive with it (PROV-O declares `prov:EmptyCollection` as both a class and an individual), so loading is unchanged: the delete preview now says what else the name is defined as and that deleting takes both, and validation lists punned names as a warning.
- **A bulk class row no longer links a class under an individual.** `bulk_add_classes` used to write `rdfs:subClassOf` before checking the parent, leaving a class parented onto an individual that never became a class.
- **Deleting a SKOS concept scheme is previewed as a scheme**, not as a concept.

Full changes: https://github.com/ralforion/orionbelt-ontology-builder/compare/v1.21.1...v1.21.2

## [1.21.1] - 2026-08-11

**A patch release for one bug: the desktop app and the console launcher grew a second sidebar list that did nothing.**

Since v1.21.0, launching through `orionbelt-ontology-builder` or the desktop app put an extra list above the app's own navigation: `streamlit entry`, `advanced`, `annotations`, `classes`, `dashboard`, `import export`, and so on. Every entry in it was dead. All real operations worked, so this was cosmetic, but it made the sidebar look broken (#269).

That list came from Streamlit, not from the app. Streamlit treats a directory named `pages` next to the entry script as a legacy multipage app and builds a navigation from the filenames it finds there. Splitting `app.py` in v1.21.0 put the page modules in exactly that position, right beside the entry script both launchers run. The entries were dead because those modules are relative imports into the app, not standalone scripts.

The page package is now called `views`, which Streamlit has no opinion about, and a test guards the name next to every entry script the repo ships.

**The hosted app at [orionbelt.streamlit.app](https://orionbelt.streamlit.app) was never affected**, and neither was `streamlit run app.py`: those run the top-level entry point, which has no such directory beside it. If that is how you use OrionBelt, this release changes nothing for you.

Thanks to @SuperCowProducts for the report.

## [1.21.0] - 2026-08-09

**Every dropdown can be cleared, every graph node can be deleted, and the Visualization page gives the graph its space back.** v1.20.0 made the graph somewhere you could create; this one makes it somewhere you can finish the job, and stops the forms writing to values you had cleared.

### Dropdowns you can clear, and that say so when you do

Every dropdown holding an entity now carries a clear cross, and clearing one is finally meaningful.

It used to be possible to empty a dropdown by selecting its text and deleting it, and every one of them then fell back to whatever the row started with. Submitting wrote the edit against an entity you had explicitly cleared, with no error and, on the Annotations page, no success message either. That is now refused by name: "Applies to Class is required." (#256)

The cross reaches the annotation types, namespaces, domains and ranges, class and property pickers, relation endpoints, restriction values, SKOS schemes and broader concepts, and the plain view selectors. Short enum pickers and "All"-style filters keep their plain dropdown, where empty already has a name.

Two of these needed more than a widget swap. An empty namespace reads as the base URI, so clearing one in an edit form would have moved the entity there and re-pointed every reference to it. And a relation's second endpoint can be replaced by an external URI, so the check runs against the resolved target rather than the dropdown.

### Delete from the graph

The counterpart to adding from it (#221): what the details panel can select, it can now remove (#261). Classes, object and data properties and individuals delete by URI; class relations and restrictions, which are axioms drawn as edges, delete as triples.

Deleting takes two clicks, and the confirmation is a modal rather than a line under the panel, so the summary of what goes with it cannot fall below the fold in that narrow column. From the graph you are one click from an entity you were only looking at.

### Annotations are editable where they live

The Annotations page listed annotations with a delete and nothing else, so fixing a typo meant deleting and re-adding, which lost the language tag and the datatype unless both were retyped exactly. Each row now has a pencil, opening the editor the graph panel has used since #223 (#258). Both routes rewrite the triple through the same guards and the same rollback.

### Room for the graph

- **The display options collapse** behind a switch that stays collapsed across reloads, giving the canvas about 100px (#260)
- **Fit-to-window reserves what is actually below the graph** instead of a flat 90px, so the canvas reaches the bottom of the window rather than stopping short of it (#260)
- **The page gutters** drop from Streamlit's 80px to 32px, which is 110px of width back on a wide screen (#260)
- **The sidebar recovers about 330px** of spacing, so Quick Stats is no longer pushed below the fold on a 1080p screen (#259)
- **The Visualization page says when it is hiding nodes.** A focus or a narrowed filter was invisible: a class added while focus mode was on simply was not drawn, and nothing said why (#260)

### Correctness

- **Import reports the same triple count the sidebar does.** An import announced "(14 triples)" while Quick Stats read "Triples: 12" for the same ontology, and the gap read as data lost on the way in. The template and upper/reference loaders already reported it the sidebar's way (#264)
- **A restriction's value is picked from the classes**, not typed, and switching a hasValue restriction to someValuesFrom no longer offers the individual it held (#255)
- **An annotation can be moved to another resource** from the graph, and an annotation on something the picker cannot list is no longer silently moved onto the first entry when saved untouched (#254)
- **Opposite-running parallel edges bow apart** instead of overlapping exactly (#253)

### Under the hood

`app.py` had reached 11,565 lines. It is now 650: the shared helpers live in `ui.py`, each page has its own module under `pages/`, and the shell wires them together (#262). No page imports another, which is what makes them separable at all.

That move broke two things that no test noticed, and both are now guarded rather than merely fixed: the graph component resolved its directory from `__file__`, and six imports inside tab bodies and button handlers resolved one level too shallow. The suite grew a sweep that renders every page and every sub-tab, a check that every relative import resolves including those nested in functions, and a rule that asset paths hang off the package rather than the module using them.

---

## [1.20.0] - 2026-08-08

**Build your ontology from the graph.** v1.19.0 made the Visualization page somewhere you could edit; this one makes it somewhere you can create, and fixes the ways it could quietly fail to show you what you asked for.

### Create from the graph

Everything here takes its subject from what you selected, instead of asking you to find it again in a list of the whole ontology.

- **Add an individual** of the class you picked, typed by it (#246)
- **Add an annotation** to whatever node you are looking at (#246)
- **Edit annotations** from the graph at all, which was the one thing there you could not (#241)

That completes #221, alongside the classes, relations and restrictions added in v1.19.0. Thanks to @SuperCowProducts, whose issue shaped the whole feature.

### Find and centre now reaches what you searched for

Three separate reasons the graph could omit the entity you picked, all reported in #234 and all fixed:

- the **render cap** dropped it when it fell past the node budget (#242)
- the **node filter** hid it when a filter change after the pick left it outside (#247)
- an **emptied filter** skipped the class loop entirely (#247)

The symptom was the same each time and was hard to read: the entity was listed and pickable, the graph visibly moved, and nothing arrived. The movement was the graph re-fitting *because* the node was missing, not an attempt to reach it. Find also no longer rewrites your node filter behind your back to make the entity visible.

### Correctness

- **Annotations keep their datatype and their object kind.** Editing one used to drop a `^^xsd:date` you never touched, mangle a non-XSD datatype into a broken relative URI, and turn an `rdfs:seeAlso` pointing at a resource into a plain string beside the original. A resource-valued annotation could also not be deleted at all, reporting success having removed nothing — including from the Annotations page and bulk editor (#241)
- **Qualified cardinality restrictions keep their `owl:onClass`.** A case-sensitive check matched `minQualifiedCardinality` and `maxQualifiedCardinality` but not `qualifiedCardinality`, so that type wrote an axiom no reasoner accepts, and re-saving an existing one silently stripped it (#241)
- **An unusable IRI is refused** rather than stored, where before one bad edit made every export of the whole ontology fail (#241)
- **Parallel edges each get their own curve.** From three connections between the same pair upwards, the third was drawn exactly on top of the first (#248)

### Also

- The app introduces itself to anyone arriving with nothing loaded, and gets out of the way once there is something to work on
- The README leads with what the workbench does, and says plainly what it does not: no SHACL validation, no SPARQL console

---

## [1.19.0] - 2026-08-07

Build your ontology **from the graph**. This release turns the Visualization page from something you read into something you work in.

### Build from the graph

You could already edit entities by clicking them. Now you can create them too, without leaving the page to find the other end in a dropdown of everything.

- **Add a class** from a selected class, which becomes its parent (#230)
- **Add a relation** by clicking its two ends: press Add relation and the selected class is the subject, the next class you click is the object. Direction stays explicit, because these are arrows, not lines (#231)
- **Add a restriction** the same way, for the five types that actually reference a second class. The picked class fills the value for `someValuesFrom`/`allValuesFrom`, or the `owl:onClass` of a qualified cardinality (#237)
- **Edit relations and restrictions** straight from a graph edge (#217)

Thanks to @SuperCowProducts, whose issue #221 shaped this, including the pick-one-then-the-other flow that replaced both approaches originally proposed.

### Seeing what connects to what

- **Neighbour highlighting.** Selecting a node outlines the nodes at the other end of its edges: dashed for the ones pointing at it, solid for the ones it points at. Clicking the node again clears it (#227)
- **Focus mode no longer opens on everything.** It seeded itself with every selected class, so on a large ontology the prune had nothing to narrow. It now starts from a real filter narrowing, or from one class when nothing was filtered (#228)
- **Your focus nodes stick.** Narrowing "Focus node(s)" to the one class you wanted no longer gets thrown away when you toggle the mode off and on (#235, #236)
- **Focus reaches deep nodes** past the graph's render cap (#218)

### Correctness

- **Qualified cardinality keeps its `owl:onClass`.** A case-sensitive check matched `minQualifiedCardinality` and `maxQualifiedCardinality` but not `qualifiedCardinality`, so that type never got an onClass selector: adding one wrote a bare cardinality, and re-saving an existing one silently stripped the `owl:onClass` off a valid axiom. Both the add and edit forms now share one classifier (#237)
- **No class-valued restrictions on data properties.** The graph flow offered data properties, which would write `owl:someValuesFrom :SomeClass` against an `owl:DatatypeProperty` (#237)

### Smaller fixes

- Shorter names rank first in entity dropdowns (#215)
- A visualization widget callback no longer crashes when its key has been dropped (#220)
- "Select all" says how many it would restore you to, so its greyed-out state explains itself (#229)

### Presentation

- The app introduces itself to anyone with nothing loaded yet, and gets out of the way once there is something to work on (#238)
- The README leads with what the workbench does, and a Roadmap section states plainly what it does not: no SHACL validation, no SPARQL console (#239)

### Dependencies

- ruff 0.16.1, astral-sh/uv 0.12.1 (#226, #225)

---

## [1.18.0] - 2026-07-31

### Features

- Persist node filters and focus seeds per linked file (#212, closes #164)
- Filter individuals, in a filter panel that stops growing (#202)
- Paste a class list into the Visualization filter (#199)

### Fixes

- Rank exact matches first in entity dropdowns (#211, closes #210)
- Draw graph edges that pointed at nodes never emitted (#201)

### Housekeeping

- Log swallowed exceptions instead of silently passing (#208)
- Justify each blind except in place, drop the BLE001 ignore (#209)
- Adopt ruff's full default rule set alongside the 0.16.0 bump (#207)
- Dependabot: astral-sh/uv in the docker group (#204), dorny/paths-filter in the github-actions group (#203)

## [1.17.5] - 2026-07-27

Patch release. Two graph fixes.

### Fixes
- The interactive graph stays in fullscreen when you click a node (#193, closes #189). The `Building graph...` placeholder was only created on renders that rebuilt the graph, so it appearing and disappearing shifted the graph component's slot in Streamlit's element tree, Streamlit re-created its iframe, and the browser dropped fullscreen along with the removed element. That is why the first click after a rebuild exited fullscreen and every Ctrl/Cmd-click did. The placeholder is now reserved on every render, and while fullscreen a plain selection no longer round-trips to Streamlit at all: vis highlights the node locally and the last selection is flushed on exit, so the details panel comes back showing what you left selected.
- **Find and centre** works on an entity that the class filter is hiding (#197, closes #195). Picking such an entity already revealed it, but the camera then framed the whole graph instead of centring, so the feature looked broken until the class was added to **Filter Classes** by hand first. Revealing the entity changes the node set, which forces a physics pass, and vis-network's `stabilization.fit` defaults to on, so it fitted the whole graph over the centring the moment the layout settled. Picking an already-visible entity was unaffected because that reuses the cached layout with physics off. The auto-fit is now suppressed while a Find pick is active, and the centring happens once the nodes have stopped moving, so it lands accurately. A click or drag during that settle still cancels it, so the camera never fights you.

## [1.17.4] - 2026-07-25

Patch release.

### Features
- Custom annotation types: type your own into the **Annotation Type** picker on the Annotations page, as a name like `wikidataId`, a bound prefix like `wdt:P31`, or a full URI, instead of putting every ID into `Comment`. A new name of your own is declared as an `owl:AnnotationProperty`, so other tools list it as an annotation rather than an undeclared predicate (#186).
- Relations and restrictions can be edited in place. Each row on the Relations and Restrictions pages gains an edit button that opens a form pre-filled with that row's own values; saving rewrites it, rather than forcing a delete and re-add. Restrictions are also listed as rows of class / property / type / value instead of one collapsed box each, and paginate like the relation lists (#188).
- Find one specific relation or restriction by pasting the whole triple: `capacitor disjointWith inductor` matches column by column, `*` leaves a part unpinned, and a single word still matches any column as before (#187).

### Fixes
- Fullscreen for the interactive graph works everywhere it is offered (#184). In the desktop app the button no longer raises `Fullscreen is not supported`, it shows just the graph rather than the whole app window, and leaving with `Esc` restores the layout instead of leaving the graph covering the window. In the browser, entering fullscreen from a window smaller than the screen no longer cuts the graph off.
- Six actions changed the ontology without recording it: adding and removing an import, and the Advanced page's property chain, disjoint union, AllDifferent and hasKey. Each of those could not be undone, left the Visualization drawing the previous state, and was never autosaved, surviving in memory only until a later action swept it up (#191, investigating #190).
- Editing a restriction now identifies it by its whole specification, so a class carrying several restrictions on one property and type changes the one on screen rather than whichever came first. The same applies to deleting one (#188).
- Restrictions on imported entities keep their namespace through both the add form and the editor, instead of being recreated in the base namespace (#188).

## [1.17.3] - 2026-07-25

Patch release.

### Features
- The Visualization graph has a Fullscreen button: it expands the graph to fill the screen, zooming out about 30% around the centre so more context is visible, and restores the exact view on exit (#181).

### Fixes
- Fullscreen now works everywhere it is offered (#184). In the desktop app the button no longer raises `Fullscreen is not supported`, it shows just the graph instead of the whole app window, it fills the screen, and leaving fullscreen with `Esc` restores the layout instead of leaving the graph covering the window. In the browser, entering fullscreen from a window smaller than the screen no longer cuts the graph off.
- The `Filter Classes` selection is kept when a class or restriction is added, instead of being cleared (#183).
- `Class Hierarchy (Text)` no longer fails with a recursion error on ontologies with `subClassOf` cycles (#182).

### Internal
- The Docker build and description jobs run only when relevant files change (#175).

## [1.17.2] - 2026-07-22

Patch release.

### Fixes
- Slider tracks no longer show red when Streamlit's theme preset resets the primary colour. The filled-track colour is baked into a per-value class that can't be recoloured selectively, so the track is rendered in a neutral tint; the navy thumb and value label mark the position (#169).

### Features
- The "Find entity" picker in the Visualization graph now lists data properties too (as "Data Property: <name>"), in addition to classes, individuals, and SKOS concepts (#173).

## [1.17.1] - 2026-07-22

Patch release.

### Fixes
- Keep the brand navy on sliders and multiselects. Streamlit's built-in theme presets (the Appearance picker, and Streamlit Cloud's default) reset the configured primary colour to the default red; the app now re-forces the brand colour onto the slider thumb and value label and the multiselect chips and focus outline, matching the buttons/checkboxes/tabs it already covered. Dark mode uses a lighter accent for the text/indicator parts so they stay legible. A regression test guards the accent coverage (#167).

## [1.17.0] - 2026-07-22

Minor release focused on the interactive graph, plus a bulk-editing improvement.

### Visualization
- **Find and centre on an entity** (#144): a searchable picker that highlights and camera-centres any class, individual, or SKOS concept, so it is easy to locate in a large graph.
- **Saved display settings** (#142): entity-type toggles, spacing, Fit-to-window, focus mode, and the details panel now persist across sessions.
- **Stable, deterministic layout** (#141): the graph no longer reshuffles randomly. A pinned layout seed makes a given graph always lay out the same way, and on expand the existing nodes stay put while only the new ones settle in.

### Classes
- **Bulk multi-parent** (#159): in bulk "Add Classes", a row naming a parent for an existing class now adds that parent (multiple inheritance) instead of skipping the row.

### Under the hood
- Refactor: the open per-item list card is now a single active-entity value (#158).
- Dependency bumps: setup-python v7, uv 0.11.30, ruff 0.15.22 (#154, #155, #156).

## [1.16.7] - 2026-07-18

### Highlights

#### View Classes no longer crashes the desktop app on large ontologies (issue #140)
The View Classes tab rendered the full interactive widget tree (an expander plus buttons, and an edit form when expanded) for every class at once. On a large ontology that emitted thousands of widgets in a single render, enough to take down the embedded desktop webview, so opening Classes crashed the app while the lighter "Open full editor" path stayed safe. The tab now paginates at 50 cards with a page selector, and the full list stays available in the "All Classes" table. The payload is bounded regardless of ontology size; the hosted web app benefits too.

#### The same pagination now covers every list view (issue #146)
Object properties, data properties, individuals, SKOS concepts, and the three Relations lists shared the same unbounded-render pattern and the same crash risk. They now paginate through shared helpers, so no list view can overwhelm the desktop webview no matter how large the ontology. Search, graph-click, and "Open full editor" navigation continue to open the exact requested item, even when another card was already open.

#### Honest autosave status (issue #145)
On the desktop app the sidebar could sit on "Autosaving..." indefinitely: the disk write is debounced and only runs on a rerun, so a pending write lands on the next interaction. When the session went idle the caption looked stuck even though the work was safe in memory. It now reads "Saved in memory; writing to disk shortly..." so the state is not misleading.

### Changes since 1.16.6
- fix(desktop): paginate View Classes so large ontologies do not crash the app (#143)
- fix(autosave): make the pending-save caption honest instead of a stuck "Autosaving..." (#149)
- fix(desktop): paginate the other list views: properties, individuals, relations, SKOS (#150, closes #146)

## [1.16.6] - 2026-07-14

### Highlights

#### Copy buttons work in the desktop app (issue #120)
The embedded desktop webview blocked JavaScript-initiated clipboard writes, so Streamlit's built-in copy buttons (for example the IRI in the Visualization details panel) silently did nothing. The desktop launcher now routes clipboard writes through a native bridge, so every copy button works. The hosted web app is unaffected.

#### Autosave can never crash the app (issue #121)
An unexpected disk-write failure during autosave could escape and stop the app, most visibly right when linking a file (which forces an immediate flush). Autosave is now best-effort: any unexpected failure is logged to the in-app error log and pauses disk autosave instead of taking the app down, which also surfaces the underlying cause for diagnosis.

#### Search disambiguates same-named entities (issue #119)
When the same local name exists under more than one namespace (e.g. `Dog` in two ontologies), the sidebar Search now tags the namespace, showing `Dog` and `Dog (other)`, matching the graph and the rest of the UI.

### Notes
- 479 tests passing.
- Deployed to https://orionbelt.streamlit.app

## [1.16.5] - 2026-07-14

### Highlights

#### Bulk add no longer fails silently (issue #114)
Bulk-adding classes, properties or individuals now reports each rejected entry with the reason (e.g. an invalid name) instead of a bare count that was wiped by the rerun. Flash messages now display on every page, not just Import/Export, and the invalid-name reason names the specific disallowed characters (so a comma is called out, not just spaces).

#### Custom-prefix namespaces are normalized (issue #115)
Binding a custom prefix to an http(s) namespace without a trailing separator (e.g. `http://example.org/ontology`) now appends `#`, matching how the base URI already behaves, so entities are no longer mangled into `http://example.org/ontologyDog`. Namespaces that already end in a delimiter, and non-http schemes such as `urn:example:`, are left untouched.

### Notes
- 472 tests passing.
- Deployed to https://orionbelt.streamlit.app

## [1.16.4] - 2026-07-13

### Highlights

#### Custom / arbitrary URI editing (issue #87 part B)
Every entity edit form (class, object property, data property, individual, SKOS concept and scheme) gains an **Advanced: set a custom URI** expander. A full http(s) URI entered there renames the entity to that exact IRI everywhere it appears, so you can give an entity an arbitrary identifier or align it with an entity in another ontology.

#### Cross-ontology linking
The Relations page gains an optional **external URI** field on the Class, Property and Individual relation forms, so `equivalentClass` / `equivalentProperty` / `sameAs` (and the other relation types) can target an entity in an ontology that has not been imported. A single local entity is now enough to create such a link.

#### External-references validation notice
`Validation` reports an info-level notice for each link whose target is not defined in the ontology, so intentional cross-ontology links are visible rather than silently unresolvable. Importing the target ontology clears it.

#### SKOS robustness
SKOS concept and scheme addressing, widget keys, target selectors, dropdown disambiguation and add-time de-duplication all key on URIs, so custom-URI and duplicate-local-name cases resolve to the intended resource.

### Notes
- 456 tests passing.
- Deployed to https://orionbelt.streamlit.app

## [1.16.3] - 2026-07-12

### Highlights

#### Stale cached engine class fixed
`get_ontology_manager_class()` was cached with `@st.cache_resource`, which pinned the `OntologyManager` class captured at first import for the life of the server process. On Streamlit Community Cloud a redeploy reruns the script without always restarting the process, so new instances were built from the old class and raised `AttributeError` for methods added in newer code (for example `get_creatable_namespaces`). That crash also aborted form rendering, producing a spurious "Missing Submit Button" warning. The decorator is removed so the class is always current.

#### Navigation glitches fixed
- The browser autosave restore no longer redirects to Dashboard. That saved data arrives on a later rerun (often the user's first tab click), so the redirect used to hijack that click and jump the page. Restore is now silent apart from the toast.
- Silenced the Streamlit warning about the Classes section control being created with both a default value and a session-state value.

### Notes
- 424 tests passing.
- No public API changes.
- Deployed to https://orionbelt.streamlit.app

## [1.16.2] - 2026-07-12

### Highlights

#### Bulk Add Classes declares referenced parents (issue #106)
When you bulk-add a class with a parent that does not exist yet (e.g. `Dog, A Dog, Animal`), the parent (`Animal`) is now declared as a real `owl:Class`, so the `subClassOf` link points at an actual class node and shows up in Visualization. Parents that another row creates explicitly keep their own label/comment; missing, skipped, or failed parents are still backfilled so no dangling parent is left behind.

#### Housekeeping
- Type-check (mypy) fixes so CI is green.
- README note on recovering from `uv tool upgrade` glitches with a clean reinstall (issue #95).

### Notes
- 424 tests passing.
- Deployed to https://orionbelt.streamlit.app

## [1.16.1] - 2026-07-12

### Highlights

#### Titles reflect the ontology (issue #90)
The **browser tab** and the **native desktop window** now show the current ontology's name (its `rdfs:label`, or the base-URI's last segment) as `<name> · OrionBelt`, so multiple open instances are easy to tell apart. The name updates live when you change the ontology's Label. On the desktop app the native window title tracks it too.

#### Navigation polish
Fixed an empty-session landing glitch where the sidebar highlighted "Dashboard" while showing the Import/Export page and the first nav click was swallowed. The tab title also no longer reverts to "Streamlit" after navigating.

#### Housekeeping
- README now uses a dynamic PyPI version badge.

### Notes
- 419 tests passing.
- Deployed to https://orionbelt.streamlit.app

## [1.16.0] - 2026-07-12

### Highlights

#### Namespaces (issue #87, part A)
Create classes, properties, and individuals in a namespace other than the base URI, and move existing entities between namespaces. The same local name (e.g. `Order`) can now be reused across namespaces without prefix clutter. A Namespace picker appears on the Add and edit forms, scoped to relevant namespaces (base, in-use, and user-bound prefixes).

#### Entity name validation (issue #93)
Entity names are now validated (relaxed NCName): spaces, `/`, `#`, `:` and stray punctuation are rejected, while Unicode letters, dots, hyphens, and leading digits are allowed. This closes a hole where a name like `Output Table` made the whole ontology un-serializable. Full `http(s)` URIs remain valid as explicit identifiers. Validation covers every create/rename/update path, including bulk add.

#### Bulk CSV improvements (issue #91)
Bulk Add now parses delimited rows without requiring a header, and supports `;` as a delimiter for labels that contain commas. The delimiter is inferred per line so a stray separator can't corrupt a valid CSV.

### Notes
- 417 tests passing.
- Deployed to https://orionbelt.streamlit.app

## [1.15.1] - 2026-07-01

*Desktop downloads (export, change report, graph image)*

### Fixes

- **Downloads now work in the desktop app.** The embedded desktop webview can't perform browser downloads, so these now save directly to disk (defaulting to your Downloads folder) with a confirmation toast, and the dead browser-download buttons are hidden on the desktop:
  - **Export** ontology
  - **Import change report**
  - **Graph image (PNG)** from the Visualization

On the web app, the normal browser downloads are unchanged.

To upgrade:

## [1.15.0] - 2026-07-01

*Edit properties & individuals from the graph; desktop export fix*

### Features

- **Inline editing for properties and individuals in the Visualization panel.** The Details side panel now edits object properties, data properties and individuals (name/label/comment, plus domain/range and class membership), not just classes. Object properties, which are drawn as edges, are editable too. (#85, #80)

### Fixes

- **Graph stays put on click.** Selecting a node no longer resets the zoom/pan or snaps back to a previously selected node; the layout and viewport are cached and restored across re-mounts. (#84)
- **Desktop export works.** The embedded desktop webview can't perform browser downloads, so the Export tab now offers a "Save to disk" option (defaulting to Downloads) in the desktop/local app. (#88, closes #86)
- **Cache-busting the graph component** so browsers and the desktop webview always load the current version. (#84)

To upgrade:

## [1.14.0] - 2026-06-30

*Visualization: edit from the graph + a Details side panel*

### Features

- **Edit a class straight from the graph.** Selecting a class shows an "Open full editor" action that jumps into Classes, Edit/Delete with the class preselected (no scrolling). A "← Back to graph" button returns you. (#81)
- **Auto-fit graph height.** The graph fills the available window height instead of a fixed size; "Fit to window" (on by default) replaces "Maximize", with the Graph Height slider as a manual override. (#82)
- **Collapsible Details side panel.** A right-hand panel (off by default, opened via the "‹" toggle on the right edge) shows the selected node's details, the IRI with a copy button, and inline editing for classes (name/label/comment/parent) so you can edit without leaving the graph. The selection persists across opening/closing the panel and the node stays highlighted. (#83)

Closes #80.

To upgrade:

## [1.12.0] - 2026-06-30

*Open a class in the editor from the graph*

### Features

- **Edit a class straight from the Visualization graph.** Selecting a class node now shows an "Open full editor" button that jumps directly into Classes, Edit/Delete with that class preselected, so the edit form appears at the top of the tab with no scrolling through the list. (#81, part of #80)

Other entity types keep their existing behavior for now and will be migrated to the same one-click edit jump in a follow-up.

## [1.11.0] - 2026-06-29

*Desktop app follows your OS theme*

### Features

- **The desktop app now follows your OS light/dark appearance by default.** It detects the system theme directly (via `darkdetect`), so it works even where the embedded webview can't report the OS colour scheme. If you pick a specific theme in the toolbar Settings menu, that choice is remembered across launches; to go back to following the system, clear the saved setting (`theme_base` in `~/.orionbelt_ontology_builder/config.json`). This also delivers the automatic dark-mode detection that #63 was about. (#79, closes #78)

To upgrade:

## [1.10.1] - 2026-06-29

*Desktop theme actually persists*

### Fixes

- **The desktop app now remembers your light/dark theme across restarts (for real this time).** The earlier attempts relied on browser localStorage, which the desktop app can't use reliably: it serves on a random port each launch, and localStorage is keyed by origin (host:port), so the saved theme was filed under a port that no longer existed next launch. (#76, closes #70)

  The theme is now persisted server-side to the app's on-disk config and re-applied via `--theme.base` on the next launch. The sidebar logo also picks the correct light/dark variant from the first paint instead of flashing the wrong one. On the hosted/cloud app nothing changes: the browser keeps the setting natively.

To upgrade:

## [1.10.0] - 2026-06-29

*Desktop backend extras + version-label fix*

### Features

- **Choose your desktop rendering backend.** New `qt` (PySide6, the default, an explicit alias of `desktop`) and `gtk` (Linux only) install extras. The launcher now selects the backend deterministically and exports `PYWEBVIEW_GUI`, which also silences the noisy "GTK cannot be loaded" traceback Qt-only Linux users saw. (#75, closes #73)

  ```bash
  pip install "orionbelt-ontology-builder[gtk]"   # GTK instead of Qt (see README for apt prerequisites)
  ```

### Fixes

- **Correct reported version.** The published 1.9.3 build reported itself as `v1.9.2` at runtime because the `APP_VERSION` bump was never staged into that release; 1.10.0 reports correctly. A new CI test now asserts `APP_VERSION` and the README badge stay in sync with `pyproject.toml`, so this cannot recur. (#75, closes #74)

Note: 1.9.3 was functionally newer than 1.9.2 (desktop theme persistence) despite the wrong label; upgrading to 1.10.0 fixes the label and adds the backend extras.

To upgrade:

## [1.9.3] - 2026-06-28

*Desktop app remembers your settings*

### Fixes

- **The native desktop app now remembers your Streamlit settings (theme, etc.) between launches.** Previously the embedded webview ran in private mode, so it discarded the localStorage where Streamlit keeps your theme choice, reverting to the bundled brand theme on every start. The launcher now opts pywebview into a persistent per-user storage directory. (#72, closes #70; follow-up to #63)

To upgrade:

## [1.9.2] - 2026-06-28

*Desktop app Qt backend fix (qtpy)*

### Fixes

- **Desktop launcher now actually opens on Linux/Windows.** v1.9.1 added PySide6 to the `desktop` extra, but pywebview's Qt backend loads through **qtpy** (`from qtpy import QtCore`), so PySide6 alone still failed with `ModuleNotFoundError: No module named 'qtpy'`. The extra now installs both qtpy and PySide6 (via pywebview's `pyside6` extra) on non-macOS platforms. (#71, follow-up to #68/#69)

Verified in a clean Linux container, and a new `desktop-extra` CI job now guards the Qt backend against regressions.

To upgrade:

Note: rendering uses QtWebEngine (Chromium), so a desktop Linux host also needs the usual system libraries (e.g. libnss3) which are normally already present.

## [1.9.1] - 2026-06-28

*Desktop app PySide6 backend fix*

### Fixes

- **Desktop launcher now works on Linux and Windows.** The `desktop` extra installed only `streamlit-desktop-app`, whose pywebview renderer needs a native GUI backend at runtime. macOS bundles one, but Linux and Windows ship none by default, so `orionbelt-ontology-builder-desktop` failed to open a window. The extra now also installs PySide6 (Qt + QtWebEngine) on non-macOS platforms to provide a portable backend. (#69, closes #68)

To upgrade:

## [1.9.0] - 2026-06-28

*Property reuse, local file storage, graph focus & dark mode*

### Highlights

**Reuse an object property across many class pairs** (#58)
Link an existing object property to another source/target class pair directly from **Properties → Add Object Property → Reuse existing property**, recorded as OWL-correct per-class restrictions (default `allValuesFrom`). One property, many pairs, intact reasoning.

**Local file storage for the desktop & console runs** (#55)
When launched locally (`orionbelt-ontology-builder` or the desktop app), the working ontology is autosaved to disk with crash recovery, and you can point it at a **linked working file** in a synced folder (Nextcloud, Dropbox, …) for automatic off-machine backups. Mutation-gated and debounced so even large ontologies don't churn; atomic writes; format follows the file extension.

**Ctrl/Cmd-click a node to focus it** (#56)
In the Visualization graph, Ctrl/Cmd-click a node to add it to the "Focus on one node" selection and narrow the graph to its neighbourhood — no typing.

**Dark-mode pass** (#62)
White logo in dark mode, themed graph canvas + readable edge labels, and brand-consistent controls. Streamlit's built-in Light/Dark theme presets otherwise revert the accent to red — the app now forces the brand colour on buttons, checkboxes, radios, and tabs/pills in both modes (lighter blue tab/pill accents in dark). Launchers apply the brand colour regardless of CWD.

### Other
- Copyright bumped to 2025–2026.
- Pinned `streamlit==1.49.1` (the dark-mode CSS targets Streamlit internals; the pin makes upgrades a deliberate, re-verify step).

### Known limitations
- **#63** — on Linux the native desktop window may not auto-detect the OS dark mode (a pywebview/QtWebEngine limitation). Workaround: set it via **⋮ → Settings → Theme → Dark**, which gives a fully consistent dark UI.

## [1.8.0] - 2026-06-27

*Native desktop app*

### Native desktop app

You can now run OrionBelt in a **native desktop window** instead of a browser tab, via the optional `desktop` extra (#53, addressing part of #40).

```bash
pip install "orionbelt-ontology-builder[desktop]"
orionbelt-ontology-builder-desktop
```

It uses [`streamlit-desktop-app`](https://pypi.org/project/streamlit-desktop-app/) (pywebview + a real Streamlit server), so every feature works as-is, including local-storage autosave. There is no browser tab to manage and no manual server start/stop.

This is fully opt-in. The plain install, the existing `orionbelt-ontology-builder` (browser) command, and the Docker image are unchanged.

#### Follow-up

Standalone, double-click installers (PyInstaller + per-OS CI artifacts) are tracked in #54.

## [1.7.2] - 2026-06-26

*Rename classes from the Edit/Delete tab*

A bug-fix release.

### Fixed
- **Classes could not be renamed from the Edit/Delete Class tab** (#42). Renaming a class (changing its name/URI with all references updated) was only available in the View Classes inline editor, not in the Edit/Delete Class tab where users naturally look, making it appear that class rename did not work. The Edit/Delete Class form now has a "Name (URI local part)" field, consistent with individuals and properties.

**Run it:** `docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder:1.7.2`

## [1.7.1] - 2026-06-26

*Fix annotation deletion*

A bug-fix release.

### Fixed
- **Annotations could not be deleted for many predicate types** (#47). `skos:example`, `rdfs:seeAlso`, the Dublin Core terms, and others silently failed to delete via the View Annotations bin button and via the Bulk Edit "delete" action. Root cause: `delete_annotation` used a predicate map that was a stale subset of the one `add_annotation` used, so unknown names resolved to the wrong (base) namespace and matched nothing; the Bulk Edit grid also showed a blank Predicate column. Predicate resolution is now unified into a single helper (full URI / known local name / `prefix:local` CURIE / bare name) shared by add and delete.

**Run it:** `docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder:1.7.1`

## [1.7.0] - 2026-06-26

*SKOS-aware search and renaming*

Two improvements aimed at working with SKOS vocabularies.

### Search now covers SKOS labels (#41)
Global search also matches **`skos:prefLabel`** and **`skos:altLabel`** (in addition to name, `rdfs:label`, and `rdfs:comment`), and now includes **SKOS concepts** as a result type. Matching altLabel synonyms makes entities far easier to find in large vocabularies. Results rank name > label > prefLabel > altLabel > comment.

### Rename entities by name, not just label (#42)
- New rename support for **SKOS concepts and concept schemes**, alongside the existing class/property/individual rename. Editing the **Name (URI local part)** field renames the entity and updates every reference, so nothing is lost (renaming a concept keeps its broader/narrower links; renaming a scheme keeps every concept's membership).
- Rename now enforces **cross-type uniqueness**: it refuses if the target name is already used by any class, property, individual, concept, or scheme, preventing URI collisions.
- Added help text to every Name field clarifying that rename updates all references (no delete-and-recreate needed).

Resolves #41 and the SKOS/rename gaps in #42.

**Run it:** `docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder:1.7.0`

## [1.6.2] - 2026-06-26

*Console entry point*

Adds a console command so the app can be installed and launched without `streamlit run`.

### What's new
- New `orionbelt-ontology-builder` console script. Installing the package now provides an executable that boots the app for you:

  ```bash
  uv tool install orionbelt-ontology-builder
  orionbelt-ontology-builder
  # or one-off, no install:
  uvx orionbelt-ontology-builder
  pipx run orionbelt-ontology-builder
  ```

  Extra arguments are forwarded to Streamlit, e.g. `orionbelt-ontology-builder --server.port 8502`.

This fixes `uv tool install` previously finding no executable to install. The native desktop wrapper discussed in #40 remains a separate follow-up.

Resolves the packaging part of #40.

**Run it:** `docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder:1.6.2`

## [1.6.1] - 2026-06-26

*Multi-seed focus, de-click fix*

Refines the focus-node graph view from v1.6.0 and fixes a crash.

### Improved
- **Focus seeds from your class selection.** Enabling **Focus on one node** now centres on the classes you had selected in the filter, instead of the first class alphabetically. The control is now a "Focus node(s)" multiselect pre-filled from your selection, and the neighbourhood grows from all seeds at once (single-class focus is just the one-seed case). This makes Focus a natural "grow my selection by N hops" filter.

### Fixed
- **Crash when un-ticking Focus** ("cannot access local variable 'focus_seed_id'"). Resolved by moving fully to the multi-seed code path.

Resolves #38.

**Run it:** `docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder:1.6.1`

## [1.6.0] - 2026-06-26

*Focus-node graph view with depth*

Adds a focused, depth-limited graph view for large ontologies, and fixes the Visualization class filter's "Clear all".

### What's new
- **Focus on one node (with depth).** In Visualization → *Filter Classes*, toggle **Focus on one node**, pick a class, individual or SKOS concept as the seed, and set a **Depth (1–5 hops)** slider. The graph shows only that node's neighbourhood.
  - Pruning runs over the **actual rendered edges**, so depth counts real links of *every* node type (subclass, object-property, individual assertions, SKOS broader/narrower, …) — not just subclass chains.
  - Great for large ontologies where showing everything at once is overwhelming.

### Fixes
- **"Clear all" under Filter Classes now works.** Clearing the class multiselect no longer snaps straight back to every class. The auto-refill that repopulated an empty selection now only runs when the ontology actually mutates (load/import/undo), not on a deliberate clear.

Resolves #23.

**Run it:** `docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder:1.6.0`

## [1.5.1] - 2026-06-26

*Configurable import upload size*

A small, backward-compatible release that makes the Import page's file-size limit easy to find and adjust.

### What's new
- The import upload cap is now an explicit, documented setting. It was always Streamlit's built-in `maxUploadSize` (200 MB default) — this release surfaces it rather than leaving it implicit.
- `.streamlit/config.toml` now sets `[server] maxUploadSize` so self-hosters can raise it in one place.
- The Import page's file-uploader help text shows the **active limit** and where to change it.
- README gained an **Upload size limit** section covering both ways to raise it (config file or `--server.maxUploadSize`), with a note that the real ceiling is host RAM since parsing is in-memory.

The hosted demo keeps the 200 MB default (Community Cloud is RAM-limited); raise the value when self-hosting with adequate memory.

Resolves #35.

**Run it:** `docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder:1.5.1`

## [1.5.0] - 2026-06-25

*Docker images + CI with a type-checked engine*

The first containerized release: official multi-arch **Docker images** on Docker Hub, a full **CI pipeline** (lint, format, type-check, tests), and a **fully type-annotated** rdflib engine.

### Docker
- Official image published to Docker Hub as `ralforion/orionbelt-ontology-builder` — run the app with no local Python setup.
- Multi-arch builds (`linux/amd64`, `linux/arm64`), tagged `:1.5.0`, `:1.5`, `:1`, `:latest`.
- Runs Streamlit headless on `0.0.0.0:8501` as a non-root user, with a container healthcheck.
- README gained a **Run with Docker** section plus Docker Hub / pulls / image-size badges; the Hub repo overview is auto-synced from `README.md`.

### Continuous integration
- New CI workflow runs **ruff** (lint + format check), **mypy**, and the **240-test** pytest suite on every push and PR.
- `ruff` and `mypy` versions are pinned so local and CI agree; mypy targets Python 3.12 (the CI runtime).

### Type safety
- The core engine (`ontology_manager.py`) is now **fully type-annotated** and passes mypy with zero errors — annotations only, no runtime behavior change (verified against the test suite).

### Release automation
- Docker images publish **only on `v*.*.*` tags** (`:1.5.0`, `:1.5`, `:1`, `:latest`) — no rolling `:main` / `:edge` tags.

**Run it:** `docker run --rm -p 8501:8501 ralforion/orionbelt-ontology-builder:1.5.0`

## [1.4.0] - 2026-06-24

### Features

- **Autosave to your browser, with automatic restore (#19)**: the working ontology is now mirrored into the browser's `localStorage` on every change and restored automatically when the page reloads — a refresh no longer wipes unsaved work. A sidebar **"Autosave to this browser"** toggle turns it off, and **"Discard saved session"** clears the saved copy and resets the workspace. Note: this is per-browser/per-device and not a replacement for Export.

### Fixes

- **SKOS concepts can be deleted again (#21)**: the concept Delete button set a session-state key that didn't match the one the confirmation handler checked (`confirm_delete_<id>` vs `confirm_delete_c_<id>`), so the confirm dialog never appeared and concepts could not be deleted. The keys now match. All other delete buttons (classes, properties, individuals, concept schemes) were audited and were already correct.

### Internals

- New `streamlit-local-storage` dependency for the autosave component.
- New `persist_autosave()` / `maybe_restore_autosave()` helpers; restore is hash-guarded, size-capped (~4 MB), tolerant of the localStorage component's two-pass handshake and its occasional value wrapping, and never clobbers an already-populated session.
- New `tests/test_autosave.py`; 240 tests pass.

## [1.3.2] - 2026-05-10

### Fixes

- **Property edit (Object + Data) Domain/Range no longer collapses to base namespace**: editing an object/data property whose domain or range pointed at an imported class (e.g. `foaf:Organization`) and clicking Save would silently rewrite the reference to `myont:Organization`. Dropdowns now use URI-keyed values.
- **Add Class / Property / Individual Relation now operates on URIs**: relation forms used local-name dropdowns, so adding a relation between two duplicate-named imported resources could land the triple on a fresh base-namespace resource instead of the one the user picked. Forms now key by URI.
- **Sidebar global search navigates to the exact resource**: previously search results used local-name session keys that no longer matched the v1.3.0 URI-keyed view panes. `search()` now exposes each result's URI and the sidebar uses URI-hash keys.
- **Visualization `rdf:type` edge points to the correct class**: an individual typed as `foaf:Organization` is now rendered against the foaf node, not whichever Organization class happened to be matched first by name.

### Internals

- New `build_uri_options(items, include_none)` helper for URI-keyed dropdowns over any entity list (classes / properties / individuals).
- `OntologyManager.get_individuals()` now exposes `class_uris` alongside the local-name `classes` list.
- `OntologyManager.search()` now includes `uri` in each result.
- 234 tests pass (+5 cross-namespace regressions).

## [1.3.1] - 2026-05-10

### What's New

- **PyPI package now ships all bundled data**: previous v1.x wheels included only the Python modules and broke for `pip install` users (samples, vis-network bundle, logos, favicon were missing). v1.3.1 ships a proper `orionbelt_ontology_builder` Python package with all data files included, so `pip install orionbelt-ontology-builder` produces a working installation.

### Fixes

- Restore the compact UI layout (reduced top padding, custom file uploader styling) that regressed during the v1.3.1 package restructure.

### Internals

- Source modules and data directories moved into `orionbelt_ontology_builder/`. Top-level `app.py`, `ontology_manager.py`, `templates.py` are kept as backward-compatible re-export shims so `streamlit run app.py` and existing tests keep working unchanged.
- Page config and custom CSS now applied inside `main()` so they re-emit on every Streamlit rerun.
- Wheel verified to contain 37 files (modules + samples + lib + assets + favicon); clean-venv install + sample loading verified.

### Notes

This is a packaging-only release on top of v1.3.0 — no behavior changes for the hosted app.

## [1.3.0] - 2026-05-10

### What's New

- **gUFO upper ontology**: NEMO/UFES gUFO v1.0.0 (Lightweight Unified Foundational Ontology) added as a second selectable upper ontology alongside gist. Suitable for OntoUML-style conceptual modeling with kinds, roles, phases, events, situations, qualities, and relators.
- **Reference Ontologies tab**: New Import / Export tab for importing widely-used domain vocabularies — currently PROV-O, FOAF, and GoodRelations (all bundled). The loader supports both bundled vocabularies and on-demand HTTPS downloads with SHA256 pinning and on-disk caching, ready for additional remote ontologies (urllib stdlib only — no new dependencies).
- **Cross-namespace duplicate handling**: When a reference vocabulary introduces a class, property, or individual whose local name already exists in your ontology (e.g. `gist:Organization` + `foaf:Organization`), the UI now shows the namespace prefix to disambiguate (`Organization (foaf)` / `Organization (gist)`) instead of crashing with duplicate-key errors. Operations like delete and rename target the specific URI without affecting the other.

### Fixes

- Visualization cache now invalidates on any ontology change — load, replace, undo, redo, or any edit — instead of relying on a brittle triple-count fingerprint that missed same-size loads.
- Visualization iframe re-mounts on every rebuild so the displayed graph always reflects the current data.
- Visualization 'Selected classes' filter now resets to all-selected on any ontology mutation, so a stale filter no longer hides newly loaded content.
- Graph viewer node identity is URI-based, fixing the case where two classes with the same local name from different namespaces were collapsed into a single visible node.
- Selectors throughout the app sort case-insensitively.

### Internals

- `OntologyManager.get_classes` / `get_object_properties` / `get_data_properties` / `get_*_relations` now expose URI fields (`parent_uris`, `child_uris`, `domain_uri`, `range_uri`, `subject_uri`, `object_uri`) that downstream callers use for disambiguation.
- Test count: 230 (+15 new regression tests for cross-namespace duplicates, the Reference Ontologies registry, and gUFO integration).

## [1.2.1] - 2026-05-03

### What's New

- **Graph PNG Download**: Download button in the graph viewer to export the current visualization as a PNG image
- **Local vis-network Bundle**: vis-network.js loaded locally instead of from CDN for reliable offline use

### Fixes

- Fix startup log message repeating on every Streamlit rerun
- Add favicon and startup version logging

## [1.2.0] - 2026-04-24

### What's New

- **Upper Ontologies**: Load [gist](https://www.semanticarts.com/gist/) (Semantic Arts) upper ontology with selectable modules as a foundation for your domain ontology
- **Segmented Controls**: Replaced all tab navigation with `st.segmented_control` for stable tab state and consistent branded UI
- **Theme**: ORIONBELT logo blue (`#0D2B7A`) as primary color across all UI elements
- **View/Edit buttons**: Now idempotent — clicking View or Edit when already open stays open instead of toggling closed

### Fixes

- Fix tab jumping to first tab on first button click (Import/Export page)
- Fix class dropdown closing when navigating from graph visualization and clicking View
- Fix gist `.ttl` files excluded by `.gitignore` on Streamlit Cloud deployment
- Replace bare `except:` with `except Exception:` in ontology_manager
- Remove unused imports, dead code, and fix lint issues in tests

## [1.1.3] - 2026-04-16

### Fixes
- **Graph visualization class filter**: Fixed a bug where loading a new ontology would lose all class nodes in the graph visualization. The persisted class filter now validates against the current ontology's classes and resets when stale.
- **Dead code cleanup**: Removed unused functions, methods, and fixed lint issues.

## [1.1.2] - 2026-04-12

### What's Changed

- Remove datatype range nodes from graph visualization — reduces clutter by eliminating separate datatype box nodes and their edges from the vis-network graph
- Suppress rdflib ConjunctiveGraph deprecation warning in tests
- Remove dead code: unused imports, variables, and assignments

## [1.1.1] - 2026-04-07

### Fixes
- **Dead View/Edit buttons**: Replaced `st.button()` return-value checks with `on_click` callbacks across all entity pages, fixing unreliable button clicks after repeated navigation
- **Duplicate key errors**: Use URI-based hash keys for individual widgets to prevent crashes when multiple individuals share the same name
- **Overlapping graph edges**: Spread parallel edges with alternating curve directions so multiple edges between the same nodes are visually separated

## [1.1.0] - 2026-04-02

### What's New

#### Graph Visualization Improvements
- **Dynamic legend** — only shows node/edge types actually present in the graph
- **Persistent settings** — all viz checkboxes, sliders, and class filters survive page navigation
- **Faster rendering** — replaced pyvis with lightweight graph builder, targeted triple queries instead of full graph scan
- **Optimized physics** — batch stabilization scaled by node count with brief settle animation
- **Render button** — forces fresh layout to fix overlapping nodes
- **Reorganized controls** — Ind. Edges and Triples moved to row 1, Maximize and Highlight Issues to row 2

#### SKOS UX Enhancements
- Graph triples view for visible nodes
- Individual edges toggle

#### Bug Fixes
- Fixed crash when filtering out classes referenced by individual edges
- Ind. Edges default changed to off

## [1.0.2] - 2026-04-01

### What's New

#### Improved Validation for Real-World Ontologies (#1, #2)
- Validation now accepts `skos:prefLabel` as a valid label (in addition to `rdfs:label`), eliminating false "missing label" warnings for ontologies like gist
- Validation recognizes `schema:domainIncludes`/`rangeIncludes` and `gist:domainIncludes`/`rangeIncludes` as valid domain/range declarations
- Missing domain/range checks are now **off by default** via a checkbox, since many ontologies intentionally omit `rdfs:domain`/`rdfs:range`
- Orphan class detection also considers `domainIncludes`/`rangeIncludes` usage

#### Fix Dead URI Links (#3)
- Placeholder `http://example.org/ontology#` URIs now render as plain text instead of clickable links
- Real ontology URIs (e.g. from gist, FOAF) remain clickable and open in a new tab
- Fixed in page header, class/property/individual detail views, and SKOS views

#### Other
- README images use absolute URLs for PyPI rendering

## [1.0.1] - 2026-03-31

### What's New

#### GitHub Issue Reporting
- GitHub icon and "Report Issue" link in the sidebar for easy bug reporting

#### Runtime Error Log
- Runtime errors are captured with full tracebacks and shown in an expandable sidebar panel
- Page rendering wrapped in error boundary — errors display inline with a link to report on GitHub
- "Clear errors" button to dismiss logged errors

#### Fixes
- Fixed iOS Safari image display (renamed asset files to use underscores)
- Fixed stale test references (unesco → geography-thesaurus sample)
- Updated sidebar logo path after file rename

## [1.0.0] - 2026-03-30

### OrionBelt Ontology Builder v1.0.0

#### New Features
- **Bulk Operations** — Add, edit, and delete entities in bulk across Classes, Properties, Individuals, and Annotations
- **SKOS Vocabulary** — Full concept scheme and concept management with hierarchy, validation, and graph visualization
- **Templates** — 5 built-in ontology templates (Organization, Product, Event, Person, SKOS Thesaurus)
- **Source View** — Live syntax-highlighted Turtle source view
- **SKOS in Graph** — SKOS concepts rendered with broader/narrower/related edges
- **Import UX** — Auto-navigate on start, incoming ontology name display, compact apply/cancel buttons
- **Graph Maximize** — Expand graph to full height with one click

#### Improvements
- Graph legend with edge/arrow colors
- Ontology name and URI shown in main content area
- SKOS concepts in sidebar Quick Stats
- Reduced UI padding for more screen real estate
- Import correctly handles SKOS-only ontologies (no silent overwrite)

#### Sample Ontologies
Includes 5 OWL ontologies (pizza, wine, foaf, prov-o, goodrelations) and 1 SKOS thesaurus (geography) for testing.

#### Testing
168+ unit tests covering bulk operations, SKOS vocabulary, templates, and sample ontology integration.

## [0.9.0] - 2026-03-30

*Import Review & Interoperability*

### What's New

#### Diff Engine & Import Review
- **Import preview**: Review changes before applying — see added, removed, and modified resources with plain-language summaries
- **Merge strategies**: Choose Replace, Merge (additive), or Merge-Overwrite when importing into an existing ontology
- **Conflict detection**: Identifies conflicting labels, domains, ranges and other predicates between current and incoming content
- **Change reports**: Download a Markdown diff report of import changes
- **Smart first import**: Empty ontologies import directly without the preview step

#### JSON-LD Import
- Full JSON-LD import support alongside Turtle, RDF/XML, N3, and N-Triples
- Automatic `@context` prefix extraction
- JSON-LD round-trip (import + export) verified

#### Prefix Management
- Add and remove custom namespace prefixes from the Dashboard
- All prefixes displayed with source classification (standard, custom)
- Prefix conflict detection during merge imports

#### Bug Fixes
- Fixed View button navigation jumping to Dashboard instead of the correct page
- Replaced deprecated `use_container_width` with `width` parameter in dataframe calls

#### Testing
- 39 new tests across 4 test modules (diff, merge, prefixes, JSON-LD)
- **115 total tests**, all passing

## [0.8.0] - 2026-03-30

### OrionBelt Ontology Builder v0.8.0

#### New Features
- **Interactive Graph Visualization** — Click nodes/edges to see details in a status bar with a View button that navigates directly to the element
- **Custom Graph Component** — Replaced pyvis HTML injection with a proper Streamlit custom component for reliable vis-network interaction
- **Undo/Redo** — Full undo/redo history for all ontology modifications
- **Global Search** — Search across all ontology elements with click-to-navigate
- **View/Edit/Delete UI** — Redesigned expander layout with button row and detail view panes
- **Auto-expand on Navigate** — Clicking View from graph or search expands the target element and collapses others

#### Improvements
- Floating color legend overlay on graph
- Dark status bar with selection info below graph
- Sidebar branding with logo, version, and copyright
- Graph node/edge tooltips with entity details

#### Bug Fixes
- Fixed vis-network loading in Streamlit iframe
- Fixed view pane not opening on search/graph navigation
- Graceful fallback for UndoManager import on Streamlit Cloud
