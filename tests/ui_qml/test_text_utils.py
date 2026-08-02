from ai_novel_studio.ui_qml.bridge.text_utils import count_words, format_word_count


def test_count_words_counts_cjk_and_latin() -> None:
    assert count_words("雾港来信") == 4
    assert count_words("Hello world") == 2
    assert count_words("第 1 章 雾港的清晨") == 8


def test_count_words_ignores_punctuation_and_whitespace() -> None:
    assert count_words("……") == 0
    assert count_words("") == 0
    assert count_words("  ") == 0


def test_format_word_count_thousands() -> None:
    assert format_word_count(1234) == "约 1.2K"
    assert format_word_count(18600) == "约 18.6K"


def test_format_word_count_small() -> None:
    assert format_word_count(42) == "42"
    assert format_word_count(0) == "0"
