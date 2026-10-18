import re
from html.parser import HTMLParser

# Content in these elements is markup machinery, never readable page text.
# "head" is deliberately absent: <title> lives there and is worth keeping.
SKIPPED = frozenset({"script", "style", "noscript", "template", "svg"})
# Elements that end a line of readable text.
BLOCK = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "div", "dd", "dl",
        "dt", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
        "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
        "section", "table", "tbody", "td", "th", "thead", "tr", "ul",
    }
)

# Blocks emit a newline on both open and close, so runs collapse to one break:
# one readable line per block keeps list items and paragraphs equally compact.
_BLANK_LINES = re.compile(r"\n{2,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")
_RUNS = re.compile(r"[ \t ]+")


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.links: list[tuple[str, str]] = []
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._link_href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIPPED:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            self._link_href = href
            self._link_text = []
        if tag in BLOCK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._link_href is not None:
            text = _RUNS.sub(" ", "".join(self._link_text)).strip()
            self.links.append((text, self._link_href))
            self._link_href = None
            self._link_text = []
        if tag in BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        self._chunks.append(data)
        if self._link_href is not None:
            self._link_text.append(data)

    def text(self) -> str:
        joined = _RUNS.sub(" ", "".join(self._chunks))
        joined = _TRAILING_SPACE.sub("\n", joined)
        return _BLANK_LINES.sub("\n", joined).strip()


def extract_readable(markup: str) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """Return (title, readable text, links) from an HTML document.

    Written against the standard library parser rather than a dependency so the
    whole tool chain stays installable and testable offline.
    """
    parser = _Extractor()
    parser.feed(markup)
    parser.close()
    return (
        _RUNS.sub(" ", parser.title).strip(),
        parser.text(),
        tuple(parser.links),
    )
