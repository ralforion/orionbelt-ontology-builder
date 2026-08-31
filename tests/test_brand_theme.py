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

    # Each accent widget Streamlit would otherwise render in default red.
    required_hooks = [
        'data-testid="stBaseButton-primary"',  # primary buttons
        'data-testid="stCheckbox"',  # checked checkbox
        # The toggle track. st.toggle reuses stCheckbox's testid, so only the
        # full selector tells its rule apart from the checkbox's.
        (
            '[data-testid="stCheckbox"] label[data-baseweb="checkbox"]'
            ":has(input:checked) > div:first-child"
        ),
        'data-testid="stRadio"',  # selected radio
        'data-testid="stSlider"',  # slider thumb
        'data-testid="stSliderThumbValue"',  # slider value label
        'data-testid="stMultiSelect"',  # multiselect chips + focus border
        'data-baseweb="tag"',  # the selected chips themselves
        # The active pill of a segmented control, which is how every page picker
        # on this app is drawn. Named by its ARIA state: the testid this rule
        # used to use is not on the button in Streamlit 1.62, so it quietly
        # matched nothing (issue #368). Worth re-checking in the DOM whenever
        # the Streamlit pin moves.
        'button[data-variant="segmented_control"][aria-checked="true"]',
    ]
    missing = [h for h in required_hooks if h not in css]
    assert not missing, f"_BRAND_CSS no longer styles: {missing}"


def test_dark_css_relightens_text_and_indicator_accents():
    # Navy is too dark for text/indicator accents on a dark backdrop, so the
    # dark-mode CSS must re-colour those to the lighter accent. The slider value
    # label and the multiselect focus outline are text/line accents and must be
    # covered (filled shapes like the thumb and chips stay navy).
    dark = app._DARK_CSS
    assert app._DARK_ACCENT in dark
    for hook in [
        'data-testid="stSliderThumbValue"',
        'data-testid="stMultiSelect"',
        # The active pill's label: Streamlit paints it with the configured
        # primaryColor, and the brand navy is 1.48:1 on Streamlit's dark
        # background — unreadable, and the reason for issue #368.
        'button[data-variant="segmented_control"][aria-checked="true"]',
    ]:
        assert hook in dark, f"_DARK_CSS missing a dark override for {hook}"
