"""Read and set a ``case_picker.case_selectbox`` in an AppTest run.

AppTest has no accessor for a custom component: it renders as an unknown
``bidi_component`` element whose proto carries the ``data`` the page sent. That
payload holds the options, their captions and the value, which is what a test
of the picker wants. Setting goes through ``st.session_state[key]``, which is
where the picker keeps its value, the same place a pick in the browser lands.
"""

import json


def rendered_picker(at, key):
    """The data of the picker keyed ``key``, or ``None`` if it was not drawn."""
    suffix = f"-{key}_case_picker"
    for element in at.get("bidi_component"):
        if element.proto.id.endswith(suffix):
            return json.loads(element.proto.json)
    return None


def rendered_picker_keys(at):
    """The keys of every picker drawn, in page order."""
    keys = []
    for element in at.get("bidi_component"):
        base = element.proto.id.split("-", 2)[-1]  # "$$ID-<hash>-<key>"
        if base.endswith("_case_picker"):
            keys.append(base.removesuffix("_case_picker"))
    return keys


class Picker:
    """What a test does with a picker, shaped like AppTest's ``Selectbox``:
    ``.value``, ``.options``, ``.set_value(v)`` and ``.run()``."""

    def __init__(self, at, key):
        data = rendered_picker(at, key)
        assert data is not None, f"no picker keyed {key!r} was drawn"
        self._at = at
        self.key = key
        self.label = data["label"]
        self.options = data["options"]
        self.value = data["value"]

    def set_value(self, value):
        self._at.session_state[self.key] = value
        self.value = value
        return self

    def run(self, **kwargs):
        return self._at.run(**kwargs)


def picker(at, key):
    """The picker keyed ``key``; fails if it was not drawn."""
    return Picker(at, key)


def pickers(at):
    """Every picker drawn, in page order, like ``at.selectbox``."""
    return [Picker(at, key) for key in rendered_picker_keys(at)]


def rank_in_component(captions, query):
    """``captions`` in the order the component's search lists them for
    ``query``, run under Node; the test is skipped where Node is missing."""
    import pathlib
    import shutil
    import subprocess
    import tempfile

    import pytest
    import sources

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    js = sources.PKG / "lib" / "case_picker" / "case_picker.js"
    with tempfile.TemporaryDirectory() as tmp:
        # As .mjs, so Node reads it as the ES module it is.
        module = pathlib.Path(tmp) / "case_picker.mjs"
        module.write_text(js.read_text("utf-8"), "utf-8")
        script = (
            f"import {{ rankOptions }} from {json.dumps(module.as_uri())};"
            f"const captions = {json.dumps(list(captions))};"
            f"console.log(JSON.stringify("
            f"rankOptions(captions, {json.dumps(query)}).map((i) => captions[i])));"
        )
        result = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
    return json.loads(result.stdout)
