import codecs


class SSEDecoder:
    def __init__(self) -> None:
        self._buffer = ""
        self._data_lines: list[str] = []
        self._utf8_decoder = codecs.getincrementaldecoder("utf-8")()

    def feed(self, chunk: bytes) -> list[str]:
        self._buffer += self._utf8_decoder.decode(chunk)
        output: list[str] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if not line:
                if self._data_lines:
                    output.append("\n".join(self._data_lines))
                    self._data_lines.clear()
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                self._data_lines.append(line[5:].lstrip())
        return output
