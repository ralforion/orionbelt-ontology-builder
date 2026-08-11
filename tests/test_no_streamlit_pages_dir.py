"""No entry script may have a ``pages`` directory beside it.

``pages`` is a magic name to Streamlit. ``PagesManager`` sets
``uses_pages_directory`` when ``<entry script>/../pages`` exists, and the script
runner then dispatches through legacy multipage mode instead of simply running
the entry script, which renders an automatic sidebar nav built from the
filenames in that directory.

The page modules were called ``pages`` when app.py was split up (PR #262). The
console and desktop launchers run ``streamlit_entry.py`` from inside the
package, so both grew a second, phantom sidebar list -- ``advanced``,
``annotations``, ``classes``, ... -- whose every entry was dead, because these
are relative-import modules and not standalone scripts (issue #269). Streamlit
Cloud runs the top-level ``app.py``, which has no such sibling, so the hosted
app never showed it and no test would have caught the regression.

Hence this: the invariant is about a directory *name*, so it is checked by
name, next to every entry script the repo ships.
"""

import pathlib

import sources

REPO = pathlib.Path(sources.PKG).parent

# Every script handed to `streamlit run`: the Cloud/`streamlit run app.py`
# entry point, and the in-package one both launchers use (cli.py, desktop.py).
ENTRY_SCRIPTS = [
    REPO / "app.py",
    sources.PKG / "streamlit_entry.py",
]


def test_the_entry_scripts_are_where_the_launchers_look():
    """Guard the guard: a moved entry script must not silently empty this test."""
    missing = [str(p) for p in ENTRY_SCRIPTS if not p.is_file()]
    assert not missing, f"entry scripts not found: {missing}"

    launchers = (sources.PKG / "cli.py").read_text("utf-8") + (
        sources.PKG / "desktop.py"
    ).read_text("utf-8")
    assert launchers.count('Path(__file__).parent / "streamlit_entry.py"') == 2


def test_no_entry_script_has_a_pages_directory_beside_it():
    offenders = [
        str((entry.parent / "pages").relative_to(REPO))
        for entry in ENTRY_SCRIPTS
        if (entry.parent / "pages").is_dir()
    ]
    assert not offenders, (
        "Streamlit turns a `pages` directory next to an entry script into an "
        "automatic multipage nav (issue #269). Rename it -- the page modules "
        "live in `views`:\n  " + "\n  ".join(offenders)
    )
