from notegrep.parse import extract_links, extract_title, extract_words


def test_title_is_first_h1():
    text = "intro\n## not this\n# Garden Plans\n# Second"
    assert extract_title(text) == "Garden Plans"


def test_title_missing():
    assert extract_title("no heading here") == ""


def test_words_drop_stop_words_and_case():
    words = extract_words("The Tomato and the Basil, tomato!")
    assert words == {"tomato", "basil"}


def test_words_keep_contractions():
    assert "don't" in extract_words("Don't water at noon")


def test_links_strip_heading_and_alias():
    text = "See [[Compost]] and [[Seeds#Spring|spring seeds]] and [[Compost]] again."
    assert extract_links(text) == ["Compost", "Seeds"]


def test_links_none():
    assert extract_links("plain [link](x.md) only") == []
