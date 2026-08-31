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
    """Streamlit hands a theme colour to the browser untouched, so a config can
    hold any CSS colour — verified against 1.62, ``rgb(3,4,5)``, ``#030405ff``
    and ``black`` all render. The hex and ``rgb()`` forms are read; the rest are
    not, and say so rather than guessing.
    """

    @pytest.mark.parametrize(
        ("colour", "dark"),
        [
            ("#030405", True),  # the background from issue #368
            ("#0e1117", True),  # Streamlit's own dark
            ("#0D2B7A", True),  # the brand navy, which is why it needs an accent
            ("#ffffff", False),
            ("#fff", False),  # three-digit
            ("#0345", True),  # four-digit, alpha ignored
            ("#030405ff", True),  # eight-digit, alpha ignored
            ("rgb(3,4,5)", True),
            ("rgb(3 4 5)", True),  # space-separated, CSS Color 4
            ("rgba(3, 4, 5, 0.5)", True),
            ("rgb(3 4 5 / 50%)", True),  # slash alpha
            ("rgb(255, 255, 255)", False),
            ("  #FFFFFF  ", False),  # whitespace and case
            ("RGB(3,4,5)", True),
        ],
    )
    def test_a_colour_is_measured(self, colour, dark):
        luminance = _relative_luminance(colour)
        assert luminance is not None
        assert (luminance < _DARK_BACKGROUND_LUMINANCE) is dark

    @pytest.mark.parametrize(
        "colour",
        [
            "",
            "#",
            "#12345",  # not a hex length CSS has
            "#gggggg",
            "rgb(3,4)",  # a channel short
            "rgb(300, 0, 0)",  # out of range
            "rgb(50%, 0%, 0%)",  # percentages are not read
            # Deliberately not known: naming every CSS colour means carrying all
            # 148 of them, and hsl()/oklch() mean carrying colour spaces. The
            # caller falls back to the theme's reported type for these.
            "black",
            "red",
            "hsl(0 0% 0%)",
            "oklch(0.2 0 0)",
        ],
    )
    def test_a_colour_this_cannot_read_says_so(self, colour):
        """None rather than 0.0: an unreadable colour must not read as black and
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

    @pytest.mark.parametrize("background", ["#030405", "rgb(3,4,5)", "#030405ff"])
    def test_a_dark_background_is_dark_even_when_the_type_says_light(
        self, monkeypatch, background
    ):
        """The reported case: colours customised, no base, so Streamlit says
        light while the app is drawn on near-black. All three spellings render
        identically in Streamlit 1.62, so all three have to be read."""
        self._patch(monkeypatch, reported="light", background=background)
        assert theme_is_dark() is True

    def test_a_background_this_cannot_read_falls_back_to_the_reported_type(
        self, monkeypatch
    ):
        """``black`` renders in Streamlit but is not a colour this measures. The
        answer is the reported type, not a guess — being wrong towards light
        leaves the app looking as it does today rather than inverting it."""
        self._patch(monkeypatch, reported="light", background="black")
        assert theme_is_dark() is False
        self._patch(monkeypatch, reported="dark", background="black")
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
