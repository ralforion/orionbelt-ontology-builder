"""Which backdrop the app thinks it is drawn on.

``st.context.theme`` reports a theme's *base*, and a config.toml that overrides
only colours has no base — so an app themed to a near-black background reported
``light``, the dark styling never loaded, and the navy accents landed on black
(issue #368). These cover the reading of the configured colour that fixes it.
"""

import pytest

from orionbelt_ontology_builder.ui import (
    _DARK_BACKGROUND_LUMINANCE,
    _relative_luminance,
    theme_is_dark,
)


class TestRelativeLuminance:
    @pytest.mark.parametrize(
        ("colour", "dark"),
        [
            ("#030405", True),  # the background from issue #368
            ("#0e1117", True),  # Streamlit's own dark
            ("#0D2B7A", True),  # the brand navy, which is why it needs a lighter accent
            ("#ffffff", False),
            ("#fff", False),  # three-digit form
            ("  #FFFFFF  ", False),  # whitespace and case
        ],
    )
    def test_a_colour_is_measured(self, colour, dark):
        luminance = _relative_luminance(colour)
        assert luminance is not None
        assert (luminance < _DARK_BACKGROUND_LUMINANCE) is dark

    @pytest.mark.parametrize(
        "colour", ["", "#", "red", "#12345", "#gggggg", "rgb(0,0,0)"]
    )
    def test_a_colour_this_cannot_read_says_so(self, colour):
        """None rather than 0.0: an unparsable colour must not read as black and
        flip the whole app into dark styling."""
        assert _relative_luminance(colour) is None


class TestThemeIsDark:
    """The two signals, in order: the reported type, then the configured colour."""

    def _patch(self, monkeypatch, *, reported, background):
        from orionbelt_ontology_builder import ui

        class _Ctx:
            def __init__(self, reported):
                self.theme = {"type": reported}

        monkeypatch.setattr(ui.st, "context", _Ctx(reported))
        monkeypatch.setattr(ui.st, "get_option", lambda name: background)

    def test_a_theme_reporting_dark_is_dark(self, monkeypatch):
        self._patch(monkeypatch, reported="dark", background=None)
        assert theme_is_dark() is True

    def test_a_dark_background_is_dark_even_when_the_type_says_light(self, monkeypatch):
        """The reported case: colours customised, no base, so Streamlit says
        light while the app is drawn on near-black."""
        self._patch(monkeypatch, reported="light", background="#030405")
        assert theme_is_dark() is True

    def test_a_light_theme_stays_light(self, monkeypatch):
        self._patch(monkeypatch, reported="light", background="#ffffff")
        assert theme_is_dark() is False

    def test_no_configured_background_stays_light(self, monkeypatch):
        self._patch(monkeypatch, reported="light", background=None)
        assert theme_is_dark() is False

    def test_an_unreadable_background_stays_light(self, monkeypatch):
        self._patch(monkeypatch, reported="light", background="whatever")
        assert theme_is_dark() is False

    def test_an_unavailable_theme_does_not_raise(self, monkeypatch):
        """Both lookups are guarded: st.context is unavailable outside a script
        run, and a page that raised here would be a page that did not render."""
        from orionbelt_ontology_builder import ui

        class _Boom:
            @property
            def theme(self):
                raise RuntimeError("no context")

        monkeypatch.setattr(ui.st, "context", _Boom())

        def _explode(name):
            raise RuntimeError("no options either")

        monkeypatch.setattr(ui.st, "get_option", _explode)
        assert theme_is_dark() is False
