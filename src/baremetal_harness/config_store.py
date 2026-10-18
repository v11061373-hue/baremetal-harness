import contextlib
import errno
import inspect
import os
import re
import stat
import threading
import tomllib
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType

from baremetal_harness.config import (
    CONFIG_FIELDS,
    INTEGER_CONFIG_FIELDS,
    RUNTIME_FIELDS,
    ConfigDocument,
    coerce_config_value,
    default_config_path,
    default_config_values,
    validate_config_values,
)

_SECURE_DIR_FD_SUPPORTED = (
    os.name == "posix"
    and bool(getattr(os, "O_DIRECTORY", 0))
    and bool(getattr(os, "O_NOFOLLOW", 0))
    and all(
        function in os.supports_dir_fd
        for function in (os.open, os.mkdir, os.stat, os.unlink)
    )
    and os.stat in os.supports_follow_symlinks
    and {"src_dir_fd", "dst_dir_fd"}.issubset(inspect.signature(os.replace).parameters)
)


class ConfigPathError(ValueError):
    """Raised when a config path is unsafe or not a regular file."""


class ConfigPersistenceError(OSError):
    """Raised when an atomic config write cannot be completed."""


_TOML_ESCAPES = {
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
    '"': '\\"',
    "\\": "\\\\",
}
_CANONICAL_INTEGER = re.compile(r"[1-9][0-9]*")
_BARE_KEY_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)
_BASIC_KEY_ESCAPES = {
    "b": "\b",
    "t": "\t",
    "n": "\n",
    "f": "\f",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


def _skip_horizontal_whitespace(source: str, index: int) -> int:
    while index < len(source) and source[index] in " \t":
        index += 1
    return index


def _parse_basic_key(source: str, index: int) -> tuple[str, int] | None:
    value: list[str] = []
    index += 1
    while index < len(source):
        character = source[index]
        if character == '"':
            return "".join(value), index + 1
        if character in "\r\n":
            return None
        if character != "\\":
            value.append(character)
            index += 1
            continue
        index += 1
        if index >= len(source):
            return None
        escape = source[index]
        if escape in _BASIC_KEY_ESCAPES:
            value.append(_BASIC_KEY_ESCAPES[escape])
            index += 1
            continue
        if escape not in {"u", "U"}:
            return None
        width = 4 if escape == "u" else 8
        digits = source[index + 1 : index + 1 + width]
        if len(digits) != width or any(
            character not in "0123456789abcdefABCDEF" for character in digits
        ):
            return None
        codepoint = int(digits, 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            return None
        value.append(chr(codepoint))
        index += width + 1
    return None


def _parse_literal_key(source: str, index: int) -> tuple[str, int] | None:
    end = source.find("'", index + 1)
    if end < 0 or "\n" in source[index + 1 : end]:
        return None
    return source[index + 1 : end], end + 1


def _parse_key_segment(source: str, index: int) -> tuple[str, int] | None:
    if index >= len(source):
        return None
    if source[index] == '"':
        return _parse_basic_key(source, index)
    if source[index] == "'":
        return _parse_literal_key(source, index)
    start = index
    while index < len(source) and source[index] in _BARE_KEY_CHARACTERS:
        index += 1
    if index == start:
        return None
    return source[start:index], index


def _parse_key_path(
    source: str,
    index: int,
    terminator: str,
) -> tuple[tuple[str, ...], int] | None:
    segments: list[str] = []
    while True:
        index = _skip_horizontal_whitespace(source, index)
        segment = _parse_key_segment(source, index)
        if segment is None:
            return None
        value, index = segment
        segments.append(value)
        index = _skip_horizontal_whitespace(source, index)
        if index >= len(source):
            return None
        if source[index] == terminator:
            return tuple(segments), index + 1
        if source[index] != ".":
            return None
        index += 1


def _quote_run_end(source: str, index: int, quote: str) -> int:
    while index < len(source) and source[index] == quote:
        index += 1
    return index


def _skip_to_next_statement(source: str, index: int) -> int:
    nesting = 0
    state: str | None = None
    while index < len(source):
        character = source[index]
        if state is None:
            if character == "#":
                while index < len(source) and source[index] not in "\r\n":
                    index += 1
                if nesting == 0:
                    return index
                continue
            if source.startswith('"""', index):
                state = "multiline-basic"
                index += 3
                continue
            if source.startswith("'''", index):
                state = "multiline-literal"
                index += 3
                continue
            if character == '"':
                state = "basic"
                index += 1
                continue
            if character == "'":
                state = "literal"
                index += 1
                continue
            if character in "[{":
                nesting += 1
            elif character in "]}" and nesting:
                nesting -= 1
            elif character in "\r\n" and nesting == 0:
                return index + 1
            index += 1
            continue
        if state in {"basic", "multiline-basic"} and character == "\\":
            index += 2
            continue
        if state == "basic" and character == '"':
            state = None
            index += 1
            continue
        if state == "literal" and character == "'":
            state = None
            index += 1
            continue
        if state == "multiline-basic" and character == '"':
            end = _quote_run_end(source, index, '"')
            if end - index >= 3:
                state = None
            index = end
            continue
        if state == "multiline-literal" and character == "'":
            end = _quote_run_end(source, index, "'")
            if end - index >= 3:
                state = None
            index = end
            continue
        index += 1
    return index


def _skip_space_and_comments(source: str, index: int) -> int:
    while index < len(source):
        if source[index] in " \t\r\n":
            index += 1
            continue
        if source[index] == "#":
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        return index
    return index


def _has_canonical_integer_value(source: str, index: int) -> bool:
    index = _skip_horizontal_whitespace(source, index)
    match = _CANONICAL_INTEGER.match(source, index)
    if match is None:
        return False
    index = _skip_horizontal_whitespace(source, match.end())
    return index == len(source) or source[index] == "#" or source[index] in "\r\n"


def _inline_value_end(source: str, index: int) -> int | None:
    nesting = 0
    state: str | None = None
    while index < len(source):
        character = source[index]
        if state is None:
            if source.startswith('"""', index):
                state = "multiline-basic"
                index += 3
                continue
            if source.startswith("'''", index):
                state = "multiline-literal"
                index += 3
                continue
            if character == '"':
                state = "basic"
                index += 1
                continue
            if character == "'":
                state = "literal"
                index += 1
                continue
            if character in "[{":
                nesting += 1
            elif character in "]}":
                if nesting:
                    nesting -= 1
                else:
                    return index
            elif character == "," and nesting == 0:
                return index
            elif character in "#\r\n":
                return None
            index += 1
            continue
        if state in {"basic", "multiline-basic"} and character == "\\":
            index += 2
            continue
        if state == "basic" and character == '"':
            state = None
            index += 1
            continue
        if state == "literal" and character == "'":
            state = None
            index += 1
            continue
        if state == "multiline-basic" and character == '"':
            end = _quote_run_end(source, index, '"')
            if end - index >= 3:
                state = None
            index = end
            continue
        if state == "multiline-literal" and character == "'":
            end = _quote_run_end(source, index, "'")
            if end - index >= 3:
                state = None
            index = end
            continue
        index += 1
    return None


def _validate_inline_table_integers(
    source: str,
    index: int,
    validated: set[str],
) -> None:
    index = _skip_horizontal_whitespace(source, index)
    if index >= len(source) or source[index] != "{":
        return
    index += 1
    while True:
        index = _skip_horizontal_whitespace(source, index)
        if index >= len(source) or source[index] == "}":
            return
        assignment = _parse_key_path(source, index, "=")
        if assignment is None:
            return
        key_path, value_index = assignment
        value_end = _inline_value_end(source, value_index)
        if value_end is None:
            return
        if len(key_path) == 1 and key_path[0] in INTEGER_CONFIG_FIELDS:
            field = key_path[0]
            lexeme = source[value_index:value_end].strip(" \t")
            if _CANONICAL_INTEGER.fullmatch(lexeme) is None:
                raise ValueError(f"{field} must be a positive integer")
            validated.add(field)
        if source[value_end] == "}":
            return
        index = value_end + 1


def _validate_integer_lexemes(source: str) -> frozenset[str]:
    table_path: tuple[str, ...] = ()
    validated: set[str] = set()
    index = 0
    while True:
        index = _skip_space_and_comments(source, index)
        if index >= len(source):
            break
        if source.startswith("[[", index):
            table_path = ()
            index = _skip_to_next_statement(source, index)
            continue
        if source[index] == "[":
            table = _parse_key_path(source, index + 1, "]")
            if table is not None:
                table_path, index = table
            index = _skip_to_next_statement(source, index)
            continue
        assignment = _parse_key_path(source, index, "=")
        if assignment is None:
            index = _skip_to_next_statement(source, index)
            continue
        key_path, value_index = assignment
        semantic_path = (*table_path, *key_path)
        if semantic_path == ("baremetal_harness",):
            _validate_inline_table_integers(source, value_index, validated)
        if (
            len(semantic_path) == 2
            and semantic_path[0] == "baremetal_harness"
            and semantic_path[1] in INTEGER_CONFIG_FIELDS
        ):
            field = semantic_path[1]
            if not _has_canonical_integer_value(source, value_index):
                raise ValueError(f"{field} must be a positive integer")
            validated.add(field)
        index = _skip_to_next_statement(source, value_index)
    return frozenset(validated)


def _toml_basic_string(value: str) -> str:
    escaped: list[str] = ['"']
    for character in value:
        codepoint = ord(character)
        if character in _TOML_ESCAPES:
            escaped.append(_TOML_ESCAPES[character])
        elif codepoint < 0x20 or codepoint == 0x7F:
            escaped.append(f"\\u{codepoint:04X}")
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("config strings must contain only Unicode scalar values")
        else:
            escaped.append(character)
    escaped.append('"')
    return "".join(escaped)


def _toml_scalar(value: object) -> str:
    if isinstance(value, Path):
        return _toml_basic_string(str(value))
    if isinstance(value, str):
        return _toml_basic_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    raise TypeError(f"unsupported config value type: {value.__class__.__name__}")


def _serialize(values: Mapping[str, object]) -> str:
    lines = ["[baremetal_harness]"]
    for field in CONFIG_FIELDS:
        if field in values and values[field] is not None:
            lines.append(f"{field} = {_toml_scalar(values[field])}")
    return "\n".join(lines) + "\n"


def redact_secret(value: object | None) -> str:
    if value is None:
        return "not configured"
    text = str(value)
    if len(text) <= 4:
        return "********"
    return f"********{text[-4:]}"


def render_config_view(store: "ConfigStore") -> str:
    values = store.resolved_view()
    lines = [
        "# BareMetal Harness configuration display (display-only; not writable TOML)",
        f"# path = {store.path}",
        f"# exists = {str(store.exists()).lower()}",
        "",
        "[baremetal_harness]",
    ]
    for field in CONFIG_FIELDS:
        value = values.get(field)
        if field == "api_key":
            rendered = redact_secret(value)
        elif value is None:
            rendered = "not configured"
        else:
            rendered = value
        lines.append(f"{field} = {_toml_scalar(rendered)}")
    return "\n".join(lines) + "\n"


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        selected = path or default_config_path()
        expanded = selected.expanduser()
        self._path = Path(os.path.abspath(expanded))
        if self._path == Path(self._path.anchor):
            raise ConfigPathError(f"config path must be a regular file: {self._path}")
        self._uses_default_path = path is None
        self._transaction_lock = threading.RLock()
        self._transaction_descriptor: int | None = None
        self._transaction_depth = 0
        self._transaction_owner: int | None = None

    @property
    def path(self) -> Path:
        return self._path

    def _ensure_secure_primitives(self) -> None:
        if not _SECURE_DIR_FD_SUPPORTED or os.name != "posix":
            raise ConfigPathError(
                f"secure config path operations are unsupported on {os.name}"
            )

    def _component_error(
        self,
        parent_descriptor: int,
        component: str,
        error: OSError,
    ) -> ConfigPathError:
        try:
            status = os.stat(
                component,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError:
            status = None
        if status is not None and stat.S_ISLNK(status.st_mode):
            return ConfigPathError(
                f"config path must not contain a symbolic link: {self.path}"
            )
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            return ConfigPathError(
                f"config path parent must be a directory: {self.path.parent}"
            )
        return ConfigPathError(f"unsafe config path: {self.path}")

    def _verify_parent_binding(self, descriptor: int) -> None:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise ConfigPathError(
                f"config parent must be a directory: {self.path.parent}"
            )
        try:
            current = os.stat(self.path.parent, follow_symlinks=False)
        except FileNotFoundError as error:
            raise ConfigPathError(
                f"config parent changed while opening: {self.path.parent}"
            ) from error
        if (
            stat.S_ISLNK(current.st_mode)
            or current.st_dev != opened.st_dev
            or current.st_ino != opened.st_ino
        ):
            raise ConfigPathError(
                f"config parent changed while opening: {self.path.parent}"
            )

    def _verify_parent_path(self, descriptor: int) -> None:
        current_descriptor = self._open_parent(create=False)
        if current_descriptor is None:
            raise ConfigPathError(
                f"config parent changed while opening: {self.path.parent}"
            )
        try:
            expected = os.fstat(descriptor)
            current = os.fstat(current_descriptor)
            if expected.st_dev != current.st_dev or expected.st_ino != current.st_ino:
                raise ConfigPathError(
                    f"config parent changed while opening: {self.path.parent}"
                )
        finally:
            os.close(current_descriptor)

    def _open_parent(self, *, create: bool) -> int | None:
        self._ensure_secure_primitives()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(self.path.anchor, flags)
        components = self.path.parent.parts[1:]
        try:
            for component in components:
                created = False
                try:
                    child = os.open(
                        component,
                        flags,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    if not create:
                        os.close(descriptor)
                        return None
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                        created = True
                    except FileExistsError:
                        pass
                    try:
                        child = os.open(
                            component,
                            flags,
                            dir_fd=descriptor,
                        )
                    except OSError as error:
                        raise self._component_error(
                            descriptor,
                            component,
                            error,
                        ) from error
                except OSError as error:
                    raise self._component_error(
                        descriptor,
                        component,
                        error,
                    ) from error
                os.close(descriptor)
                descriptor = child
                if created:
                    os.fchmod(descriptor, 0o700)
            if self._uses_default_path:
                os.fchmod(descriptor, 0o700)
            self._verify_parent_binding(descriptor)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @contextmanager
    def _parent_descriptor(self, *, create: bool) -> Iterator[int | None]:
        with self._transaction_lock:
            if self._transaction_descriptor is not None:
                if self._transaction_owner != threading.get_ident():
                    raise RuntimeError("config transaction ownership is inconsistent")
                self._verify_parent_binding(self._transaction_descriptor)
                try:
                    yield self._transaction_descriptor
                except BaseException:
                    raise
                else:
                    self._verify_parent_path(self._transaction_descriptor)
                return
            descriptor = self._open_parent(create=create)
            try:
                yield descriptor
            except BaseException:
                raise
            else:
                if descriptor is not None:
                    self._verify_parent_path(descriptor)
            finally:
                if descriptor is not None:
                    os.close(descriptor)

    def _verify_config_descriptor(
        self,
        parent_descriptor: int,
        descriptor: int,
    ) -> os.stat_result:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ConfigPathError(f"config path must be a regular file: {self.path}")
        if stat.S_IMODE(opened.st_mode) & 0o077:
            raise ConfigPathError(f"config file must be owner-only: {self.path}")
        try:
            current = os.stat(
                self.path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError as error:
            raise ConfigPathError(
                f"config path changed while opening: {self.path}"
            ) from error
        if stat.S_ISLNK(current.st_mode):
            raise ConfigPathError(
                f"config path must not be a symbolic link: {self.path}"
            )
        if current.st_dev != opened.st_dev or current.st_ino != opened.st_ino:
            raise ConfigPathError(f"config path changed while opening: {self.path}")
        return opened

    def _open_config(
        self,
        parent_descriptor: int,
    ) -> tuple[int, os.stat_result] | None:
        try:
            descriptor = os.open(
                self.path.name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise ConfigPathError(
                    f"config path must not be a symbolic link: {self.path}"
                ) from error
            if error.errno == errno.EISDIR:
                raise ConfigPathError(
                    f"config path must be a regular file: {self.path}"
                ) from error
            raise
        try:
            return descriptor, self._verify_config_descriptor(
                parent_descriptor,
                descriptor,
            )
        except BaseException:
            os.close(descriptor)
            raise

    def exists(self) -> bool:
        with self._parent_descriptor(create=False) as parent_descriptor:
            if parent_descriptor is None:
                return False
            opened = self._open_config(parent_descriptor)
            if opened is None:
                return False
            descriptor, _ = opened
            os.close(descriptor)
            return True

    def _read_text(self) -> str | None:
        with self._parent_descriptor(create=False) as parent_descriptor:
            if parent_descriptor is None:
                return None
            result = self._open_config(parent_descriptor)
            if result is None:
                return None
            descriptor, opened = result
            try:
                with os.fdopen(descriptor, "r", encoding="utf-8") as file:
                    descriptor = -1
                    source = file.read()
                current = os.stat(
                    self.path.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISLNK(current.st_mode)
                    or current.st_dev != opened.st_dev
                    or current.st_ino != opened.st_ino
                ):
                    raise ConfigPathError(
                        f"config path changed while reading: {self.path}"
                    )
                return source
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

    def read(self) -> ConfigDocument:
        try:
            source = self._read_text()
        except IsADirectoryError as error:
            raise ConfigPathError(
                f"config path must be a regular file: {self.path}"
            ) from error
        if source is None:
            return ConfigDocument({})
        try:
            payload = tomllib.loads(source)
        except tomllib.TOMLDecodeError as error:
            raise ValueError(f"invalid config file: {self.path}") from error
        if set(payload) - {"baremetal_harness"}:
            raise ValueError(
                f"unknown root config fields: {sorted(set(payload) - {'baremetal_harness'})}"
            )
        section = payload.get("baremetal_harness", {})
        if not isinstance(section, dict):
            raise ValueError("[baremetal_harness] must be a TOML table")
        unknown = set(section) - set(CONFIG_FIELDS)
        if unknown:
            raise ValueError(f"unknown config fields: {sorted(unknown)}")
        validated_integer_fields = _validate_integer_lexemes(source)
        for field in INTEGER_CONFIG_FIELDS:
            if field in section and field not in validated_integer_fields:
                raise ValueError(f"{field} must be a positive integer")
        converted = {
            field: coerce_config_value(field, value) for field, value in section.items()
        }
        merged = default_config_values()
        merged.update(
            {
                field: value
                for field, value in converted.items()
                if field in RUNTIME_FIELDS
            }
        )
        validate_config_values(merged)
        return ConfigDocument(converted)

    def resolved_view(self) -> Mapping[str, object]:
        document = self.read()
        values = default_config_values()
        values.update(document.values)
        return MappingProxyType(values)

    @contextmanager
    def _transaction(self) -> Iterator[int]:
        import fcntl

        with self._transaction_lock:
            owner = threading.get_ident()
            if self._transaction_descriptor is not None:
                if self._transaction_owner != owner:
                    raise RuntimeError("config transaction ownership is inconsistent")
                self._transaction_depth += 1
                try:
                    yield self._transaction_descriptor
                finally:
                    self._transaction_depth -= 1
                return
            descriptor = self._open_parent(create=True)
            if descriptor is None:
                raise ConfigPathError(
                    f"config parent is unavailable: {self.path.parent}"
                )
            locked = False
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                locked = True
                self._verify_parent_binding(descriptor)
                self._transaction_descriptor = descriptor
                self._transaction_depth = 1
                self._transaction_owner = owner
                try:
                    yield descriptor
                except BaseException:
                    raise
                else:
                    self._verify_parent_path(descriptor)
            finally:
                self._transaction_descriptor = None
                self._transaction_depth = 0
                self._transaction_owner = None
                try:
                    if locked:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)

    @contextmanager
    def coordinate_first_run(self) -> Iterator[bool]:
        """Serialize first-run checks with kernel-owned cross-process locks.

        POSIX locks the verified parent directory inode and creates no lock
        artifact. Other platforms fail explicitly rather than silently use
        pathname-only coordination with stale-file semantics.
        """
        if os.name != "posix":
            raise ConfigPersistenceError(
                f"first-run coordination is unsupported on {os.name}"
            )
        with self._transaction():
            yield not self.exists()

    def _create_temporary(self, parent_descriptor: int) -> tuple[int, str]:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        for _ in range(10):
            name = f".{self.path.name}.baremetal_harness.{uuid.uuid4().hex}.tmp"
            try:
                descriptor = os.open(
                    name,
                    flags,
                    0o600,
                    dir_fd=parent_descriptor,
                )
            except FileExistsError:
                continue
            return descriptor, name
        raise ConfigPersistenceError(f"failed to create temporary config: {self.path}")

    def _write_locked(
        self,
        values: Mapping[str, object],
        parent_descriptor: int,
    ) -> None:
        candidate = dict(values)
        self._validate_candidate(candidate)
        existing = self._open_config(parent_descriptor)
        if existing is not None:
            existing_descriptor, _ = existing
            os.close(existing_descriptor)
        descriptor, temporary_name = self._create_temporary(parent_descriptor)
        try:
            temporary_status = os.fstat(descriptor)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                descriptor = -1
                os.fchmod(file.fileno(), 0o600)
                file.write(_serialize(candidate))
                file.flush()
                os.fsync(file.fileno())
                os.replace(
                    temporary_name,
                    self.path.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                )
            persisted = os.stat(
                self.path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                stat.S_ISLNK(persisted.st_mode)
                or persisted.st_dev != temporary_status.st_dev
                or persisted.st_ino != temporary_status.st_ino
                or stat.S_IMODE(persisted.st_mode) != 0o600
            ):
                raise ConfigPersistenceError(f"failed to persist config: {self.path}")
            self._verify_parent_binding(parent_descriptor)
            os.fsync(parent_descriptor)
        except OSError as error:
            raise ConfigPersistenceError(
                f"failed to persist config: {self.path}"
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_descriptor)

    def _validate_candidate(self, candidate: Mapping[str, object]) -> None:
        merged = default_config_values()
        merged.update(
            {
                field: value
                for field, value in candidate.items()
                if field in RUNTIME_FIELDS
            }
        )
        validate_config_values(merged)
        ConfigDocument(candidate)

    def set(self, field: str, value: object) -> None:
        converted = coerce_config_value(field, value)
        if not self.exists():
            self._validate_candidate({field: converted})
        with self._transaction() as parent_descriptor:
            document = self.read()
            candidate = dict(document.values)
            candidate[field] = converted
            self._validate_candidate(candidate)
            self._write_locked(candidate, parent_descriptor)

    def unset(self, field: str) -> None:
        if field not in CONFIG_FIELDS:
            raise ValueError(f"unknown config field: {field}")
        if not self.exists():
            self._validate_candidate({})
        with self._transaction() as parent_descriptor:
            document = self.read()
            candidate = dict(document.values)
            candidate.pop(field, None)
            self._validate_candidate(candidate)
            self._write_locked(candidate, parent_descriptor)

    def initialize(
        self,
        *,
        base_url: str | None,
        model: str | None,
        api_key: str | None,
    ) -> None:
        provided = {
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
        }
        converted = {
            field: coerce_config_value(field, value)
            for field, value in provided.items()
            if value is not None
        }
        if not self.exists():
            missing = set(provided) - set(converted)
            if missing:
                raise ValueError(
                    "base_url, model, and api_key are required for initialization"
                )
            initial = {**converted, "workspace": Path(".")}
            self._validate_candidate(initial)
        with self._transaction() as parent_descriptor:
            document = self.read()
            candidate = dict(document.values)
            candidate.update(converted)
            candidate.setdefault("workspace", Path("."))
            for field in provided:
                if candidate.get(field) is None:
                    raise ValueError(f"{field} is required for initialization")
            self._validate_candidate(candidate)
            self._write_locked(candidate, parent_descriptor)
