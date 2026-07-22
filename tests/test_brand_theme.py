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
        'data-testid="stRadio"',  # selected radio
        'data-testid="stSlider"',  # slider thumb
        'data-testid="stSliderThumbValue"',  # slider value label
        'data-testid="stMultiSelect"',  # multiselect chips + focus border
        'data-baseweb="tag"',  # the selected chips themselves
        ".stTabs",  # selected tab
    ]
    missing = [h for h in required_hooks if h not in css]
    assert not missing, f"_BRAND_CSS no longer styles: {missing}"
