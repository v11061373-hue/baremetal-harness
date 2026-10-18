from baremetal_harness.context.tokens import CharacterTokenEstimator, is_dense


def test_latin_text_keeps_the_character_ratio() -> None:
    assert CharacterTokenEstimator(chars_per_token=4).estimate("12345") == 2
    assert CharacterTokenEstimator(chars_per_token=1).estimate("abc") == 3


def test_cjk_is_not_counted_as_a_quarter_token() -> None:
    prompt = "帮我重构这个模块并补充测试"

    estimate = CharacterTokenEstimator().estimate(prompt)

    # The old len/4 rule gave 4 for this; real tokenizers charge roughly one
    # token per character, so the estimate must be in that range.
    assert estimate >= len(prompt)


def test_mixed_text_counts_each_script_separately() -> None:
    # 8 latin chars -> 2 tokens, 4 dense chars -> 4 tokens
    assert CharacterTokenEstimator().estimate("abcdefgh测试文本") == 6


def test_estimate_never_underestimates_dense_text() -> None:
    for text in ("日本語テキスト", "한국어 텍스트", "全角ＡＢＣ", "。、；："):
        assert CharacterTokenEstimator().estimate(text) >= sum(
            1 for character in text if is_dense(character)
        )


def test_dense_detection_covers_the_expected_scripts() -> None:
    assert is_dense("中") and is_dense("あ") and is_dense("한") and is_dense("　")
    assert not is_dense("a") and not is_dense("1") and not is_dense(" ")


def test_ratios_must_be_positive() -> None:
    import pytest

    with pytest.raises(ValueError):
        CharacterTokenEstimator(chars_per_token=0)
    with pytest.raises(ValueError):
        CharacterTokenEstimator(dense_chars_per_token=0)
