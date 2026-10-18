from baremetal_harness.model.sse import SSEDecoder


def test_decoder_handles_partial_lines_and_multiple_events() -> None:
    decoder = SSEDecoder()

    assert decoder.feed(b'data: {"a":') == []
    assert decoder.feed(b"1}\n\ndata: [DONE]\n\n") == ['{"a":1}', "[DONE]"]


def test_decoder_handles_utf8_split_across_chunks() -> None:
    decoder = SSEDecoder()
    encoded = "data: 你好\n\n".encode()

    assert decoder.feed(encoded[:8]) == []
    assert decoder.feed(encoded[8:]) == ["你好"]


def test_decoder_joins_multiple_data_lines() -> None:
    decoder = SSEDecoder()

    assert decoder.feed(b"data: first\ndata: second\n\n") == ["first\nsecond"]
