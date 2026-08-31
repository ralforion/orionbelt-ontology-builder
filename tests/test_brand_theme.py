"""Guard the brand-colour fallback CSS.

Streamlit's built-in theme presets (the Appearance / theme picker, and Streamlit
Cloud's default) drop the configured brand primaryColor and fall back to the
default red. The app re-forces the brand navy onto the accent widgets with CSS
(``_BRAND_CSS``). If a widget is dropped from that CSS, it silently reverts to
red in the reset case, which is hard to catch by eye — this test fails loudly
instead.
"""

from orionbelt_ontology_builder import app


def test_brand_css_forces_the_brand_colour_on_every_accent_widget():
    css = app._BRAND_CSS
    assert app._BRAND in css  # the navy is actually referenced

    # Each accent widget Streamlit would otherwise render in default red, named
    # by the hook it carries in the pinned Streamlit. These are internal DOM
    # details: 1.62 moved these widgets to react-aria and every
    # ``[data-baseweb=...]`` hook here stopped matching in silence (issue #368),
    # so they want re-checking in the browser whenever the pin moves.
    required_hooks = [
        'data-testid="stBaseButton-primary"',  # primary buttons
        # A checked checkbox's box, and the track of a toggle that is on:
        # st.toggle reuses stCheckbox's testid and marks state the same way.
        '[data-testid="stCheckbox"] label[data-selected="true"] > div:not([data-testid])',
        # The dot inside a selected radio.
        'label[data-testid="stRadioOption"][data-selected="true"]',
        # The active pill of a segmented control: every page picker in the app.
        'button[data-variant="segmented_control"][aria-checked="true"]',
        '[data-testid="stSlider"] div:has(> [data-testid="stSliderThumbValue"])',  # thumb
        'data-testid="stSliderThumbValue"',  # slider value label
        'data-testid="stMultiSelectTagsContainer"',  # multiselect chips
    ]
    missing = [h for h in required_hooks if h not in css]
    assert not missing, f"_BRAND_CSS no longer styles: {missing}"


def test_dark_css_relightens_every_accent_the_navy_is_too_dark_for():
    """On a dark backdrop the navy is 1.48:1 against the background — text drawn
    in it cannot be read, and a control filled with it barely separates from the
    page. Both directions are covered here: text/line accents take the lighter
    accent, filled shapes take the fill.
    """
    dark = app._DARK_CSS
    assert app._DARK_ACCENT in dark

    for hook in [
        'data-testid="stSliderThumbValue"',  # a text accent
        'button[data-variant="segmented_control"][aria-checked="true"]',  # its label
        'data-testid="stBaseButton-primary"',  # and the filled controls
        '[data-testid="stCheckbox"] label[data-selected="true"] > div:not([data-testid])',
        'label[data-testid="stRadioOption"][data-selected="true"]',
        '[data-testid="stSlider"] div:has(> [data-testid="stSliderThumbValue"])',
        'data-testid="stMultiSelectTagsContainer"',
        # Links: Streamlit's own link blue belongs to no other accent here.
        "a:visited",
    ]:
        assert hook in dark, f"_DARK_CSS missing a dark override for {hook}"


def test_text_accents_and_filled_controls_take_their_own_blue():
    """Two blues a step apart, on purpose. A filled control carries a white
    label, which wants the darker one; text on the page wants the lighter one,
    and for a colour used both ways those two demands move together — so one
    colour cannot serve both without giving up 1.5:1 somewhere. The rules are
    asserted by job, so a future edit cannot quietly swap them."""
    dark = app._DARK_CSS

    def rule_for(selector):
        rule = dark[dark.index(selector) :]
        return rule[: rule.index("}")]

    for selector in [
        "a,",  # links
        'data-testid="stSliderThumbValue"',  # the slider's value label
    ]:
        assert app._DARK_ACCENT in rule_for(selector), (
            f"{selector} is not text-accented"
        )

    for selector in [
        '[data-testid="stBaseButton-primary"]',
        'button[data-variant="segmented_control"][aria-checked="true"]',  # a filled pill
        '[data-testid="stCheckbox"] label[data-selected="true"] > div:not([data-testid])',
    ]:
        assert app._DARK_FILL in rule_for(selector), f"{selector} is not filled"
