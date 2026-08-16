"""Language codes offered in the annotation Language fields (issue #252).

The language tag is the one part of an annotation that cannot be looked up in
the ontology itself: ``eng`` and ``enm`` are one letter apart and six hundred
years apart, so a field that takes one offers a searchable list of codes with
the language they name instead of an empty text box.

Two packs ship with the app. Both are projected from the single
:data:`_LANGUAGES` table below, so a language's alpha-2 and alpha-3 codes can
never drift apart, and a name is written once. On top of those the user can
define **custom packs** — own codes, own labels — which live in the UI layer
(``ui.custom_language_packs``); this module only knows their shape and how to
validate, read and write one.

Everything here is plain data plus string helpers: no Streamlit, so the packs
can be tested without an app run.
"""

import json
import re

#: ``(alpha-3, alpha-2, English name)``, alpha-2 empty where ISO 639-1 has no
#: code for the language. The list covers every ISO 639-1 language, plus the
#: historical languages an ontology is most likely to need a tag for (which is
#: the whole reason to reach for alpha-3), plus ISO 639-2/3's special-purpose
#: codes for "undetermined" and friends.
_LANGUAGES: tuple[tuple[str, str, str], ...] = (
    # -- ISO 639-1 languages, alpha-3 (T) code first --------------------------
    ("aar", "aa", "Afar"),
    ("abk", "ab", "Abkhazian"),
    ("afr", "af", "Afrikaans"),
    ("aka", "ak", "Akan"),
    ("amh", "am", "Amharic"),
    ("ara", "ar", "Arabic"),
    ("arg", "an", "Aragonese"),
    ("asm", "as", "Assamese"),
    ("ava", "av", "Avaric"),
    ("ave", "ae", "Avestan"),
    ("aym", "ay", "Aymara"),
    ("aze", "az", "Azerbaijani"),
    ("bak", "ba", "Bashkir"),
    ("bam", "bm", "Bambara"),
    ("bel", "be", "Belarusian"),
    ("ben", "bn", "Bengali"),
    ("bih", "bh", "Bihari languages"),
    ("bis", "bi", "Bislama"),
    ("bod", "bo", "Tibetan"),
    ("bos", "bs", "Bosnian"),
    ("bre", "br", "Breton"),
    ("bul", "bg", "Bulgarian"),
    ("cat", "ca", "Catalan"),
    ("ces", "cs", "Czech"),
    ("cha", "ch", "Chamorro"),
    ("che", "ce", "Chechen"),
    ("chu", "cu", "Church Slavonic"),
    ("chv", "cv", "Chuvash"),
    ("cor", "kw", "Cornish"),
    ("cos", "co", "Corsican"),
    ("cre", "cr", "Cree"),
    ("cym", "cy", "Welsh"),
    ("dan", "da", "Danish"),
    ("deu", "de", "German"),
    ("div", "dv", "Divehi"),
    ("dzo", "dz", "Dzongkha"),
    ("ell", "el", "Greek, Modern"),
    ("eng", "en", "English"),
    ("epo", "eo", "Esperanto"),
    ("est", "et", "Estonian"),
    ("eus", "eu", "Basque"),
    ("ewe", "ee", "Ewe"),
    ("fao", "fo", "Faroese"),
    ("fas", "fa", "Persian"),
    ("fij", "fj", "Fijian"),
    ("fin", "fi", "Finnish"),
    ("fra", "fr", "French"),
    ("fry", "fy", "Western Frisian"),
    ("ful", "ff", "Fulah"),
    ("gla", "gd", "Gaelic, Scottish"),
    ("gle", "ga", "Irish"),
    ("glg", "gl", "Galician"),
    ("glv", "gv", "Manx"),
    ("grn", "gn", "Guarani"),
    ("guj", "gu", "Gujarati"),
    ("hat", "ht", "Haitian Creole"),
    ("hau", "ha", "Hausa"),
    ("heb", "he", "Hebrew"),
    ("her", "hz", "Herero"),
    ("hin", "hi", "Hindi"),
    ("hmo", "ho", "Hiri Motu"),
    ("hrv", "hr", "Croatian"),
    ("hun", "hu", "Hungarian"),
    ("hye", "hy", "Armenian"),
    ("ibo", "ig", "Igbo"),
    ("ido", "io", "Ido"),
    ("iii", "ii", "Sichuan Yi"),
    ("iku", "iu", "Inuktitut"),
    ("ile", "ie", "Interlingue"),
    ("ina", "ia", "Interlingua"),
    ("ind", "id", "Indonesian"),
    ("ipk", "ik", "Inupiaq"),
    ("isl", "is", "Icelandic"),
    ("ita", "it", "Italian"),
    ("jav", "jv", "Javanese"),
    ("jpn", "ja", "Japanese"),
    ("kal", "kl", "Kalaallisut"),
    ("kan", "kn", "Kannada"),
    ("kas", "ks", "Kashmiri"),
    ("kat", "ka", "Georgian"),
    ("kau", "kr", "Kanuri"),
    ("kaz", "kk", "Kazakh"),
    ("khm", "km", "Khmer"),
    ("kik", "ki", "Kikuyu"),
    ("kin", "rw", "Kinyarwanda"),
    ("kir", "ky", "Kyrgyz"),
    ("kom", "kv", "Komi"),
    ("kon", "kg", "Kongo"),
    ("kor", "ko", "Korean"),
    ("kua", "kj", "Kuanyama"),
    ("kur", "ku", "Kurdish"),
    ("lao", "lo", "Lao"),
    ("lat", "la", "Latin"),
    ("lav", "lv", "Latvian"),
    ("lim", "li", "Limburgish"),
    ("lin", "ln", "Lingala"),
    ("lit", "lt", "Lithuanian"),
    ("ltz", "lb", "Luxembourgish"),
    ("lub", "lu", "Luba-Katanga"),
    ("lug", "lg", "Ganda"),
    ("mah", "mh", "Marshallese"),
    ("mal", "ml", "Malayalam"),
    ("mar", "mr", "Marathi"),
    ("mkd", "mk", "Macedonian"),
    ("mlg", "mg", "Malagasy"),
    ("mlt", "mt", "Maltese"),
    ("mon", "mn", "Mongolian"),
    ("mri", "mi", "Maori"),
    ("msa", "ms", "Malay"),
    ("mya", "my", "Burmese"),
    ("nau", "na", "Nauru"),
    ("nav", "nv", "Navajo"),
    ("nbl", "nr", "Ndebele, South"),
    ("nde", "nd", "Ndebele, North"),
    ("ndo", "ng", "Ndonga"),
    ("nep", "ne", "Nepali"),
    ("nld", "nl", "Dutch"),
    ("nno", "nn", "Norwegian Nynorsk"),
    ("nob", "nb", "Norwegian Bokmål"),
    ("nor", "no", "Norwegian"),
    ("nya", "ny", "Nyanja"),
    ("oci", "oc", "Occitan"),
    ("oji", "oj", "Ojibwa"),
    ("ori", "or", "Oriya"),
    ("orm", "om", "Oromo"),
    ("oss", "os", "Ossetian"),
    ("pan", "pa", "Punjabi"),
    ("pli", "pi", "Pali"),
    ("pol", "pl", "Polish"),
    ("por", "pt", "Portuguese"),
    ("pus", "ps", "Pashto"),
    ("que", "qu", "Quechua"),
    ("roh", "rm", "Romansh"),
    ("ron", "ro", "Romanian"),
    ("run", "rn", "Rundi"),
    ("rus", "ru", "Russian"),
    ("sag", "sg", "Sango"),
    ("san", "sa", "Sanskrit"),
    ("sin", "si", "Sinhala"),
    ("slk", "sk", "Slovak"),
    ("slv", "sl", "Slovenian"),
    ("sme", "se", "Northern Sami"),
    ("smo", "sm", "Samoan"),
    ("sna", "sn", "Shona"),
    ("snd", "sd", "Sindhi"),
    ("som", "so", "Somali"),
    ("sot", "st", "Sotho, Southern"),
    ("spa", "es", "Spanish"),
    ("sqi", "sq", "Albanian"),
    ("srd", "sc", "Sardinian"),
    ("srp", "sr", "Serbian"),
    ("ssw", "ss", "Swati"),
    ("sun", "su", "Sundanese"),
    ("swa", "sw", "Swahili"),
    ("swe", "sv", "Swedish"),
    ("tah", "ty", "Tahitian"),
    ("tam", "ta", "Tamil"),
    ("tat", "tt", "Tatar"),
    ("tel", "te", "Telugu"),
    ("tgk", "tg", "Tajik"),
    ("tgl", "tl", "Tagalog"),
    ("tha", "th", "Thai"),
    ("tir", "ti", "Tigrinya"),
    ("ton", "to", "Tongan"),
    ("tsn", "tn", "Tswana"),
    ("tso", "ts", "Tsonga"),
    ("tuk", "tk", "Turkmen"),
    ("tur", "tr", "Turkish"),
    ("twi", "tw", "Twi"),
    ("uig", "ug", "Uighur"),
    ("ukr", "uk", "Ukrainian"),
    ("urd", "ur", "Urdu"),
    ("uzb", "uz", "Uzbek"),
    ("ven", "ve", "Venda"),
    ("vie", "vi", "Vietnamese"),
    ("vol", "vo", "Volapük"),
    ("wln", "wa", "Walloon"),
    ("wol", "wo", "Wolof"),
    ("xho", "xh", "Xhosa"),
    ("yid", "yi", "Yiddish"),
    ("yor", "yo", "Yoruba"),
    ("zha", "za", "Zhuang"),
    ("zho", "zh", "Chinese"),
    ("zul", "zu", "Zulu"),
    # -- Historical languages, which ISO 639-1 has no code for ----------------
    ("akk", "", "Akkadian"),
    ("ang", "", "English, Old"),
    ("arc", "", "Aramaic, Imperial"),
    ("chb", "", "Chibcha"),
    ("cop", "", "Coptic"),
    ("dum", "", "Dutch, Middle"),
    ("egy", "", "Egyptian, Ancient"),
    ("elx", "", "Elamite"),
    ("enm", "", "English, Middle"),
    ("frm", "", "French, Middle"),
    ("fro", "", "French, Old"),
    ("gez", "", "Geez"),
    ("gmh", "", "German, Middle High"),
    ("goh", "", "German, Old High"),
    ("got", "", "Gothic"),
    ("grc", "", "Greek, Ancient"),
    ("hit", "", "Hittite"),
    ("lzh", "", "Chinese, Literary"),
    ("mga", "", "Irish, Middle"),
    ("non", "", "Norse, Old"),
    ("osc", "", "Oscan"),
    ("ota", "", "Turkish, Ottoman"),
    ("pal", "", "Pahlavi"),
    ("peo", "", "Persian, Old"),
    ("phn", "", "Phoenician"),
    ("pro", "", "Provençal, Old"),
    ("sga", "", "Irish, Old"),
    ("sux", "", "Sumerian"),
    ("syc", "", "Syriac, Classical"),
    ("uga", "", "Ugaritic"),
    ("xno", "", "Anglo-Norman"),
    # -- Living languages an alpha-3 user is likely to reach for ---------------
    ("arb", "", "Arabic, Standard"),
    ("ceb", "", "Cebuano"),
    ("cmn", "", "Chinese, Mandarin"),
    ("fil", "", "Filipino"),
    ("nds", "", "German, Low"),
    ("pes", "", "Persian, Iranian"),
    ("tpi", "", "Tok Pisin"),
    ("yue", "", "Chinese, Cantonese"),
    # -- Special-purpose codes, for when the language is not one language ------
    ("mis", "", "Uncoded languages"),
    ("mul", "", "Multiple languages"),
    ("qaa", "", "Reserved for local use (qaa–qtz)"),
    ("und", "", "Undetermined"),
    ("zxx", "", "No linguistic content"),
)

#: Display name of the alpha-3 pack — the default, since alpha-3 is the reason
#: this exists: it can name a language ISO 639-1 has no code for.
ALPHA3_PACK = "ISO 639-3 (alpha-3)"
#: Display name of the alpha-2 pack, for an ontology in modern languages only.
ALPHA2_PACK = "ISO 639-1 (alpha-2)"
#: The packs that ship with the app, in the order the picker offers them.
BUILTIN_PACKS: tuple[str, ...] = (ALPHA3_PACK, ALPHA2_PACK)
DEFAULT_PACK = ALPHA3_PACK

#: Between the code and the language name in a dropdown option. The same
#: separator the rest of the UI puts between a name and its label.
OPTION_SEPARATOR = " · "

#: What rdflib accepts as a language tag (``rdflib.term._lang_tag_regex``).
#: Mirrored rather than imported: it is private, and a tag it rejects raises out
#: of ``add_annotation`` — a custom pack has to be refused where it is written,
#: not where it is used.
_TAG_RE = re.compile(r"^[a-zA-Z]+(?:-[a-zA-Z0-9]+)*$")


def builtin_pack(name: str) -> list[dict]:
    """The ``[{"code", "label"}, ...]`` entries of a built-in pack.

    Unknown names give the default pack rather than raising: the active pack is
    persisted, and a saved custom pack that has since been deleted must not take
    every Language field down with it.
    """
    if name == ALPHA2_PACK:
        rows = [(a2, name_) for _a3, a2, name_ in _LANGUAGES if a2]
    else:
        rows = [(a3, name_) for a3, _a2, name_ in _LANGUAGES]
    return [{"code": code, "label": label} for code, label in sorted(rows)]


def format_option(code: str, label: str) -> str:
    """``"eng · English"`` — what a language dropdown shows for one entry."""
    label = (label or "").strip()
    return f"{code}{OPTION_SEPARATOR}{label}" if label else code


def code_from_option(option: str | None) -> str:
    """The bare tag behind a dropdown option, or a typed one unchanged.

    Every language field accepts a code that is in no pack, so this has to cope
    with both ``"eng · English"`` and a plain ``"pt-BR"``.
    """
    if not option:
        return ""
    return option.split(OPTION_SEPARATOR, 1)[0].strip()


def is_valid_tag(tag: str) -> bool:
    """True when rdflib will accept ``tag`` as a literal's language."""
    return bool(_TAG_RE.match(tag or ""))


def invalid_tag_reason(tag: str) -> str | None:
    """Why ``tag`` cannot be a language tag, or ``None`` when it can.

    Written for the pack editor and the add forms, so the two refusals a user
    actually hits — a digit in the primary subtag (``xx1``), an underscore
    (``en_GB``) — come back as advice rather than as a traceback.
    """
    tag = (tag or "").strip()
    if not tag:
        return "A language code is required."
    if is_valid_tag(tag):
        return None
    return (
        f"'{tag}' is not a valid language tag. A tag is letters, optionally "
        "followed by '-' and more letters or digits — 'de', 'grc', 'pt-BR'. "
        "For a language of your own, use a private-use tag such as 'x-mycode' "
        "or a code from the 'qaa'–'qtz' range."
    )


def normalize_pack(entries) -> tuple[list[dict], list[str]]:
    """Clean a pack's rows, returning ``(entries, errors)``.

    Rows come from a spreadsheet editor or an imported file, so anything can be
    in them: blank rows (dropped), a code twice (first kept), a code rdflib
    would reject (refused, with a reason). A pack is saved only when ``errors``
    is empty, so a bad row is never quietly discarded.
    """
    cleaned: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for entry in entries or []:
        if isinstance(entry, dict):
            code = str(entry.get("code") or "").strip()
            label = str(entry.get("label") or "").strip()
        else:
            code, label = str(entry or "").strip(), ""
        if not code and not label:
            continue  # an empty row is the editor's, not the user's
        if reason := invalid_tag_reason(code):
            errors.append(reason)
            continue
        if code in seen:
            errors.append(f"'{code}' is listed more than once.")
            continue
        seen.add(code)
        cleaned.append({"code": code, "label": label})
    return cleaned, errors


def pack_to_json(name: str, entries) -> str:
    """Serialize one custom pack for download."""
    return json.dumps(
        {"name": name, "entries": [dict(e) for e in entries]},
        ensure_ascii=False,
        indent=2,
    )


def pack_from_json(text: str) -> tuple[str, list[dict]]:
    """Read a downloaded pack back, raising ``ValueError`` on anything else.

    Accepts the shape :func:`pack_to_json` writes and, for a hand-written file,
    a bare list of entries (which carries no name — the caller names it).
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Not a readable JSON file: {exc}") from exc
    name = str(data.get("name") or "") if isinstance(data, dict) else ""
    raw = data if isinstance(data, list) else None
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        raw = data["entries"]
    # Anything else — a number, a string, an object with no entries — falls
    # through as nothing found, which is the one message worth giving: a file
    # that is not a pack and a pack with no codes are the same mistake here.
    entries, errors = normalize_pack(raw or [])
    if errors:
        raise ValueError(errors[0])
    if not entries:
        raise ValueError("No language codes in that file.")
    return name, entries
