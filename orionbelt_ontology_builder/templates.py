"""Built-in ontology templates for bootstrapping new ontologies."""

import hashlib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

TEMPLATES = [
    {
        "name": "Organization",
        "description": "Organization structure with departments, persons, and roles. Includes properties for organizational relationships.",
        "turtle": """@prefix : <{base_uri}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Organization a owl:Class ;
    rdfs:label "Organization" .

:Department a owl:Class ;
    rdfs:label "Department" ;
    rdfs:subClassOf :Organization .

:Person a owl:Class ;
    rdfs:label "Person" .

:Role a owl:Class ;
    rdfs:label "Role" .

:worksFor a owl:ObjectProperty ;
    rdfs:label "works for" ;
    rdfs:domain :Person ;
    rdfs:range :Organization .

:hasDepartment a owl:ObjectProperty ;
    rdfs:label "has department" ;
    rdfs:domain :Organization ;
    rdfs:range :Department .

:hasRole a owl:ObjectProperty ;
    rdfs:label "has role" ;
    rdfs:domain :Person ;
    rdfs:range :Role .

:manages a owl:ObjectProperty ;
    rdfs:label "manages" ;
    rdfs:domain :Person ;
    rdfs:range :Department .

:hasName a owl:DatatypeProperty ;
    rdfs:label "has name" ;
    rdfs:domain :Person ;
    rdfs:range xsd:string .

:hasEmail a owl:DatatypeProperty ;
    rdfs:label "has email" ;
    rdfs:domain :Person ;
    rdfs:range xsd:string .

:foundedYear a owl:DatatypeProperty ;
    rdfs:label "founded year" ;
    rdfs:domain :Organization ;
    rdfs:range xsd:integer .
""",
    },
    {
        "name": "Product Catalog",
        "description": "Product catalog with categories, brands, and reviews. Suitable for e-commerce or inventory ontologies.",
        "turtle": """@prefix : <{base_uri}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Product a owl:Class ;
    rdfs:label "Product" .

:Category a owl:Class ;
    rdfs:label "Category" .

:Brand a owl:Class ;
    rdfs:label "Brand" .

:Review a owl:Class ;
    rdfs:label "Review" .

:belongsToCategory a owl:ObjectProperty ;
    rdfs:label "belongs to category" ;
    rdfs:domain :Product ;
    rdfs:range :Category .

:hasBrand a owl:ObjectProperty ;
    rdfs:label "has brand" ;
    rdfs:domain :Product ;
    rdfs:range :Brand .

:hasReview a owl:ObjectProperty ;
    rdfs:label "has review" ;
    rdfs:domain :Product ;
    rdfs:range :Review .

:hasSubCategory a owl:ObjectProperty ;
    rdfs:label "has sub-category" ;
    rdfs:domain :Category ;
    rdfs:range :Category .

:productName a owl:DatatypeProperty ;
    rdfs:label "product name" ;
    rdfs:domain :Product ;
    rdfs:range xsd:string .

:price a owl:DatatypeProperty ;
    rdfs:label "price" ;
    rdfs:domain :Product ;
    rdfs:range xsd:decimal .

:rating a owl:DatatypeProperty ;
    rdfs:label "rating" ;
    rdfs:domain :Review ;
    rdfs:range xsd:integer .

:reviewText a owl:DatatypeProperty ;
    rdfs:label "review text" ;
    rdfs:domain :Review ;
    rdfs:range xsd:string .
""",
    },
    {
        "name": "Event",
        "description": "Events with locations, participants, and organizers. Useful for conference, meetup, or calendar ontologies.",
        "turtle": """@prefix : <{base_uri}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Event a owl:Class ;
    rdfs:label "Event" .

:Location a owl:Class ;
    rdfs:label "Location" .

:Participant a owl:Class ;
    rdfs:label "Participant" .

:Organizer a owl:Class ;
    rdfs:label "Organizer" ;
    rdfs:subClassOf :Participant .

:hasLocation a owl:ObjectProperty ;
    rdfs:label "has location" ;
    rdfs:domain :Event ;
    rdfs:range :Location .

:hasParticipant a owl:ObjectProperty ;
    rdfs:label "has participant" ;
    rdfs:domain :Event ;
    rdfs:range :Participant .

:organizedBy a owl:ObjectProperty ;
    rdfs:label "organized by" ;
    rdfs:domain :Event ;
    rdfs:range :Organizer .

:eventName a owl:DatatypeProperty ;
    rdfs:label "event name" ;
    rdfs:domain :Event ;
    rdfs:range xsd:string .

:startDate a owl:DatatypeProperty ;
    rdfs:label "start date" ;
    rdfs:domain :Event ;
    rdfs:range xsd:dateTime .

:endDate a owl:DatatypeProperty ;
    rdfs:label "end date" ;
    rdfs:domain :Event ;
    rdfs:range xsd:dateTime .

:locationName a owl:DatatypeProperty ;
    rdfs:label "location name" ;
    rdfs:domain :Location ;
    rdfs:range xsd:string .

:address a owl:DatatypeProperty ;
    rdfs:label "address" ;
    rdfs:domain :Location ;
    rdfs:range xsd:string .
""",
    },
    {
        "name": "Person / Contact",
        "description": "Person and contact information with addresses. Ideal for CRM or directory ontologies.",
        "turtle": """@prefix : <{base_uri}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Person a owl:Class ;
    rdfs:label "Person" .

:Address a owl:Class ;
    rdfs:label "Address" .

:ContactInfo a owl:Class ;
    rdfs:label "Contact Info" .

:hasAddress a owl:ObjectProperty ;
    rdfs:label "has address" ;
    rdfs:domain :Person ;
    rdfs:range :Address .

:hasContact a owl:ObjectProperty ;
    rdfs:label "has contact" ;
    rdfs:domain :Person ;
    rdfs:range :ContactInfo .

:knows a owl:ObjectProperty ;
    rdfs:label "knows" ;
    rdfs:domain :Person ;
    rdfs:range :Person ;
    a owl:SymmetricProperty .

:firstName a owl:DatatypeProperty ;
    rdfs:label "first name" ;
    rdfs:domain :Person ;
    rdfs:range xsd:string .

:lastName a owl:DatatypeProperty ;
    rdfs:label "last name" ;
    rdfs:domain :Person ;
    rdfs:range xsd:string .

:birthDate a owl:DatatypeProperty ;
    rdfs:label "birth date" ;
    rdfs:domain :Person ;
    rdfs:range xsd:date .

:email a owl:DatatypeProperty ;
    rdfs:label "email" ;
    rdfs:domain :ContactInfo ;
    rdfs:range xsd:string .

:phone a owl:DatatypeProperty ;
    rdfs:label "phone" ;
    rdfs:domain :ContactInfo ;
    rdfs:range xsd:string .

:street a owl:DatatypeProperty ;
    rdfs:label "street" ;
    rdfs:domain :Address ;
    rdfs:range xsd:string .

:city a owl:DatatypeProperty ;
    rdfs:label "city" ;
    rdfs:domain :Address ;
    rdfs:range xsd:string .

:postalCode a owl:DatatypeProperty ;
    rdfs:label "postal code" ;
    rdfs:domain :Address ;
    rdfs:range xsd:string .

:country a owl:DatatypeProperty ;
    rdfs:label "country" ;
    rdfs:domain :Address ;
    rdfs:range xsd:string .
""",
    },
    {
        "name": "SKOS Thesaurus",
        "description": "SKOS ConceptScheme with sample broader/narrower concepts. Starting point for controlled vocabularies and taxonomies.",
        "turtle": """@prefix : <{base_uri}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

:MainScheme a skos:ConceptScheme ;
    rdfs:label "Main Scheme" .

:Science a skos:Concept ;
    skos:prefLabel "Science" ;
    skos:inScheme :MainScheme .

:NaturalScience a skos:Concept ;
    skos:prefLabel "Natural Science" ;
    skos:broader :Science ;
    skos:inScheme :MainScheme .

:SocialScience a skos:Concept ;
    skos:prefLabel "Social Science" ;
    skos:broader :Science ;
    skos:inScheme :MainScheme .

:Physics a skos:Concept ;
    skos:prefLabel "Physics" ;
    skos:broader :NaturalScience ;
    skos:inScheme :MainScheme .

:Biology a skos:Concept ;
    skos:prefLabel "Biology" ;
    skos:broader :NaturalScience ;
    skos:inScheme :MainScheme .

:Economics a skos:Concept ;
    skos:prefLabel "Economics" ;
    skos:broader :SocialScience ;
    skos:inScheme :MainScheme .

:Science skos:narrower :NaturalScience, :SocialScience .
:NaturalScience skos:narrower :Physics, :Biology .
:SocialScience skos:narrower :Economics .
""",
    },
]


def get_template_names() -> list:
    """Return list of template names."""
    return [t["name"] for t in TEMPLATES]


def get_template(name: str) -> Optional[dict]:
    """Return a template by name, or None if not found."""
    for t in TEMPLATES:
        if t["name"] == name:
            return t
    return None


def render_template(template: dict, base_uri: str) -> str:
    """Render a template's Turtle with the given base URI."""
    return template["turtle"].replace("{base_uri}", base_uri)


SAMPLES_DIR = Path(__file__).parent / "samples"

UPPER_ONTOLOGIES = [
    {
        "name": "gist (Semantic Arts)",
        "version": "14.1.0",
        "description": (
            "A minimalist upper ontology for the enterprise by Semantic Arts. "
            "Covers ~100 foundational classes (Event, Person, Organization, "
            "Agreement, Specification, etc.) and ~100 properties. "
            "Licensed under CC BY 4.0."
        ),
        "url": "https://www.semanticarts.com/gist/",
        "license": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "attribution": "Semantic Arts, Inc.",
        "modules": [
            {
                "name": "gistCore",
                "file": "gist/gistCore14.1.0.ttl",
                "description": "Main ontology with all classes, properties, and restrictions",
                "required": True,
            },
            {
                "name": "gistRdfsAnnotations",
                "file": "gist/gistRdfsAnnotations14.1.0.ttl",
                "description": "rdfs:label and rdfs:comment annotations for compatibility",
                "required": False,
                "default": True,
            },
            {
                "name": "gistSubClassAssertions",
                "file": "gist/gistSubClassAssertions14.1.0.ttl",
                "description": "Materialized subclass inferences (useful without a DL reasoner)",
                "required": False,
                "default": True,
            },
            {
                "name": "gistMediaTypes",
                "file": "gist/gistMediaTypes14.1.0.ttl",
                "description": "Common internet media type instances",
                "required": False,
                "default": False,
            },
        ],
    },
    {
        "name": "gUFO (UFO / OntoUML)",
        "version": "1.0.0",
        "description": (
            "A lightweight OWL 2 DL implementation of the Unified Foundational "
            "Ontology (UFO). Designed for ontologically precise modeling of "
            "kinds, roles, phases, events, situations, qualities, and relators. "
            "Suitable for OntoUML-style conceptual modeling. Licensed under CC BY 4.0."
        ),
        "url": "https://nemo-ufes.github.io/gufo/",
        "license": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "attribution": (
            "Almeida, J.P.A.; Guizzardi, G.; Sales, T.P.; Falbo, R.A. — "
            "NEMO, Federal University of Espírito Santo"
        ),
        "modules": [
            {
                "name": "gufo",
                "file": "gufo/gufo.ttl",
                "description": (
                    "Core gUFO ontology — foundational UFO classes (Endurant, "
                    "Event, Situation, Quality, Relator, etc.) and properties"
                ),
                "required": True,
            },
        ],
    },
]


def get_upper_ontology_names() -> list:
    """Return upper ontology names, sorted alphabetically (case-insensitive)."""
    return sorted((o["name"] for o in UPPER_ONTOLOGIES), key=str.lower)


def get_upper_ontology(name: str) -> Optional[dict]:
    """Return an upper ontology definition by name, or None if not found."""
    for o in UPPER_ONTOLOGIES:
        if o["name"] == name:
            return o
    return None


def load_upper_ontology_module(module: dict) -> str:
    """Load a module's Turtle content from file."""
    file_path = SAMPLES_DIR / module["file"]
    return file_path.read_text(encoding="utf-8")


CACHE_DIR = Path.home() / ".cache" / "orionbelt" / "ontologies"

REFERENCE_ONTOLOGIES = [
    {
        "name": "PROV-O",
        "version": "W3C Recommendation 2013-04-30",
        "description": (
            "The W3C PROV Ontology for representing provenance: agents, "
            "activities, entities, and how they were generated, derived, and "
            "used. The standard vocabulary for tracking 'who did what when' "
            "in any domain."
        ),
        "url": "https://www.w3.org/TR/prov-o/",
        "license": "W3C Document License (royalty-free)",
        "attribution": "W3C Provenance Working Group",
        "modules": [
            {
                "name": "prov-o",
                "file": "prov-o.ttl",
                "format": "turtle",
                "description": "PROV-O ontology (bundled, offline-ready)",
                "required": True,
            },
        ],
    },
    {
        "name": "FOAF (Friend of a Friend)",
        "version": "0.99",
        "description": (
            "Friend of a Friend — a Linked Data vocabulary for describing "
            "people, organizations, social networks, and online identity. "
            "One of the original Linked Data vocabularies and widely embedded "
            "in other ontologies."
        ),
        "url": "http://xmlns.com/foaf/spec/",
        "license": "Creative Commons Attribution 1.0",
        "attribution": "Dan Brickley, Libby Miller",
        "modules": [
            {
                "name": "foaf",
                "file": "foaf.rdf",
                "format": "xml",
                "description": "FOAF specification (bundled, RDF/XML)",
                "required": True,
            },
        ],
    },
    {
        "name": "GoodRelations",
        "version": "1.0",
        "description": (
            "GoodRelations — an OWL ontology for e-commerce: products, "
            "offers, prices, payment methods, and business entities. Underlies "
            "much of the schema.org Product/Offer model."
        ),
        "url": "http://www.heppnetz.de/ontologies/goodrelations/v1.html",
        "license": "Creative Commons Attribution 3.0",
        "attribution": "Martin Hepp",
        "modules": [
            {
                "name": "goodrelations",
                "file": "goodrelations.owl",
                "format": "xml",
                "description": "GoodRelations e-commerce vocabulary (bundled, RDF/XML)",
                "required": True,
            },
        ],
    },
]


def get_reference_ontology_names() -> list:
    """Return reference ontology names, sorted alphabetically (case-insensitive)."""
    return sorted((o["name"] for o in REFERENCE_ONTOLOGIES), key=str.lower)


def get_reference_ontology(name: str) -> Optional[dict]:
    """Return a reference ontology definition by name, or None if not found."""
    for o in REFERENCE_ONTOLOGIES:
        if o["name"] == name:
            return o
    return None


def load_reference_ontology_module(module: dict) -> str:
    """Load a reference-ontology module from bundle (file:) or HTTPS (url:).

    Downloaded files are cached on disk under CACHE_DIR keyed by SHA256 (or by
    URL hash when no SHA256 is pinned). When a SHA256 is provided, the
    downloaded bytes are verified against it before caching — a mismatch
    raises rather than silently loading altered content.
    """
    if "file" in module:
        return (SAMPLES_DIR / module["file"]).read_text(encoding="utf-8")
    if "url" in module:
        return _fetch_with_cache(module["url"], module.get("sha256"))
    raise ValueError(f"Module '{module.get('name')}' has neither 'file' nor 'url'")


def _fetch_with_cache(url: str, expected_sha256: str | None = None) -> str:
    """Download a URL with on-disk caching and optional SHA256 verification."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = expected_sha256 or hashlib.sha256(url.encode("utf-8")).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.dat"

    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "orionbelt-ontology-builder/1.3"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not download ontology from {url}: {e.reason}") from e

    if expected_sha256:
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha256:
            raise RuntimeError(
                f"SHA256 mismatch for {url}: expected {expected_sha256}, "
                f"got {actual}. The remote file may have been updated; "
                "please verify and update the registry."
            )

    text = data.decode("utf-8")
    cache_file.write_text(text, encoding="utf-8")
    return text
