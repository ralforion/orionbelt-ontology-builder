"""``st.components.v1.html`` is deprecated in favour of ``st.iframe``.

Streamlit logs a deprecation notice on every call, and the page shim is mounted
on every rerun, so one call filled the console of the desktop app. Its stated
removal date has passed, so a later Streamlit could drop it outright.
"""

import sources


def test_no_module_calls_components_v1_html():
    offenders = [
        f"{path.name}:{lineno}"
        for path in sources.ui_sources()
        for lineno, line in enumerate(path.read_text("utf-8").splitlines(), 1)
        if "components.v1.html(" in line
    ]
    assert not offenders, f"use st.iframe instead: {offenders}"
