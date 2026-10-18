import math

# Ranges where one character is roughly one token for byte-pair encoders,
# rather than the ~4 characters per token that Latin text averages.
_DENSE_RANGES = (
    (0x3000, 0x303F),  # CJK punctuation
    (0x3040, 0x30FF),  # Hiragana and Katakana
    (0x3400, 0x4DBF),  # CJK extension A
    (0x4E00, 0x9FFF),  # CJK unified ideographs
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
    (0xFF00, 0xFFEF),  # Fullwidth forms
    (0x20000, 0x2FA1F),  # CJK extensions B and beyond
)


def is_dense(character: str) -> bool:
    code = ord(character)
    return any(low <= code <= high for low, high in _DENSE_RANGES)


class CharacterTokenEstimator:
    """Estimate tokens from characters, counting dense scripts separately.

    One ratio for all text badly underestimates Chinese, Japanese and Korean:
    those characters cost about a token each, not a quarter of one. Since this
    drives the context budget, each bucket rounds up — overestimating costs
    some headroom, underestimating gets the request rejected by the model.
    """

    def __init__(
        self,
        chars_per_token: int = 4,
        *,
        dense_chars_per_token: int = 1,
    ) -> None:
        if chars_per_token <= 0:
            raise ValueError("chars_per_token must be positive")
        if dense_chars_per_token <= 0:
            raise ValueError("dense_chars_per_token must be positive")
        self.chars_per_token = chars_per_token
        self.dense_chars_per_token = dense_chars_per_token

    def estimate(self, text: str) -> int:
        dense = sum(1 for character in text if is_dense(character))
        sparse = len(text) - dense
        return math.ceil(sparse / self.chars_per_token) + math.ceil(
            dense / self.dense_chars_per_token
        )
