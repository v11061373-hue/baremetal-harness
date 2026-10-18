import os
import stat
import tomllib
from multiprocessing import Event, Process
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Thread, current_thread

import pytest

from baremetal_harness.config_store import (
    ConfigPathError,
    ConfigPersistenceError,
    ConfigStore,
    render_config_view,
)


def write_config(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o600)


def test_read_rejects_unknown_root_and_section_fields(tmp_path: Path) -> None:
    root_key = tmp_path / "root-key.toml"
    write_config(
        root_key,
        'unexpected = true\n[baremetal_harness]\nmodel = "demo"\n',
    )
    unknown_field = tmp_path / "unknown-field.toml"
    write_config(unknown_field, '[baremetal_harness]\nunknown = "value"\n')

    with pytest.raises(ValueError, match="root"):
        ConfigStore(root_key).read()
    with pytest.raises(ValueError, match="unknown config fields"):
        ConfigStore(unknown_field).read()


def test_read_rejects_symlink_without_following_it(tmp_path: Path) -> None:
    target = tmp_path / "target.toml"
    write_config(target, '[baremetal_harness]\nmodel = "demo"\n')
    link = tmp_path / "config.toml"
    link.symlink_to(target)

    with pytest.raises(ConfigPathError, match="symbolic link"):
        ConfigStore(link).read()


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_read_rejects_existing_config_with_group_or_other_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    secret = "must-not-appear-1234"
    path.write_text(f'[baremetal_harness]\napi_key = "{secret}"\n')
    path.chmod(0o644)

    with pytest.raises(ConfigPathError, match="owner-only") as error:
        ConfigStore(path).read()

    assert secret not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor traversal")
@pytest.mark.parametrize("operation", ["read", "set"])
def test_config_rejects_symlinked_intermediate_parent(
    tmp_path: Path,
    operation: str,
) -> None:
    real_parent = tmp_path / "real" / "nested"
    real_parent.mkdir(parents=True)
    path = real_parent / "config.toml"
    write_config(path, '[baremetal_harness]\nmodel = "before"\n')
    link_parent = tmp_path / "linked"
    link_parent.symlink_to(tmp_path / "real", target_is_directory=True)
    store = ConfigStore(link_parent / "nested" / "config.toml")

    with pytest.raises(ConfigPathError, match="symbolic link"):
        if operation == "read":
            store.read()
        else:
            store.set("model", "after")

    assert path.read_text() == '[baremetal_harness]\nmodel = "before"\n'


def test_read_rejects_symlink_swapped_at_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[baremetal_harness]\nmodel = "original"\n')
    target = tmp_path / "target.toml"
    write_config(target, '[baremetal_harness]\nmodel = "swapped"\n')
    original_open = os.open
    swapped = False

    def swap_then_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if not swapped and dir_fd is not None and Path(file) == Path(path.name):
            path.unlink()
            path.symlink_to(target)
            swapped = True
        if dir_fd is None:
            return original_open(file, flags, mode)
        return original_open(file, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_then_open)

    with pytest.raises(ConfigPathError, match="symbolic link"):
        ConfigStore(path).read()


def test_read_fails_closed_when_secure_primitives_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[baremetal_harness]\nmodel = "demo"\n')
    monkeypatch.setattr(
        "baremetal_harness.config_store._SECURE_DIR_FD_SUPPORTED",
        False,
    )

    with pytest.raises(ConfigPathError, match="unsupported"):
        ConfigStore(path).read()


def test_read_closes_opened_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, '[baremetal_harness]\nmodel = "demo"\n')
    original_open = os.open
    descriptors: list[int] = []

    def capture_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is None:
            descriptor = original_open(file, flags, mode)
        else:
            descriptor = original_open(file, flags, mode, dir_fd=dir_fd)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", capture_open)

    assert ConfigStore(path).read().get("model") == "demo"
    assert descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("mutation", ["set", "unset", "initialize"])
def test_mutations_reject_config_symlink(
    tmp_path: Path,
    mutation: str,
) -> None:
    target = tmp_path / "target.toml"
    write_config(target, '[baremetal_harness]\nmodel = "demo"\n')
    link = tmp_path / "config.toml"
    link.symlink_to(target)
    store = ConfigStore(link)

    with pytest.raises(ConfigPathError, match="symbolic link"):
        if mutation == "set":
            store.set("model", "changed")
        elif mutation == "unset":
            store.unset("model")
        else:
            store.initialize(
                base_url="https://model.invalid/v1",
                model="changed",
                api_key="file-secret",
            )


def test_read_missing_file_is_empty_and_directory_is_rejected(
    tmp_path: Path,
) -> None:
    assert ConfigStore(tmp_path / "missing.toml").read().values == {}

    directory = tmp_path / "config.toml"
    directory.mkdir()
    with pytest.raises(ConfigPathError, match="regular file"):
        ConfigStore(directory).read()


def test_root_config_path_is_rejected_as_not_a_regular_file() -> None:
    with pytest.raises(ConfigPathError, match="regular file"):
        ConfigStore(Path(Path.cwd().anchor))


def test_relative_config_path_resolves_safely_and_round_trips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    store = ConfigStore(Path(".baremetal_harness-test/config.toml"))

    store.set("model", "relative-model")

    assert store.path == tmp_path / ".baremetal_harness-test/config.toml"
    assert store.read().get("model") == "relative-model"


@pytest.mark.parametrize(
    "toml_value",
    ["1.9", "inf", "nan", "true", '"1e3"', '"+1"', '" 1"', '"01"'],
)
def test_toml_integer_fields_reject_noncanonical_values(
    tmp_path: Path,
    toml_value: str,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, f"[baremetal_harness]\nmax_turns = {toml_value}\n")

    with pytest.raises(
        ValueError,
        match="max_turns must be a positive integer",
    ):
        ConfigStore(path).read()


@pytest.mark.parametrize(
    "toml_value",
    ["+1", "0x10", "0o10", "0b10", "1_000", "1.0", "1e3"],
)
def test_toml_integer_fields_reject_noncanonical_source_lexemes(
    tmp_path: Path,
    toml_value: str,
) -> None:
    path = tmp_path / "config.toml"
    secret = "lexeme-secret-must-not-appear"
    write_config(
        path,
        (f'[baremetal_harness]\napi_key = "{secret}"\nmax_turns = {toml_value}\n'),
    )

    with pytest.raises(
        ValueError,
        match="max_turns must be a positive integer",
    ) as error:
        ConfigStore(path).read()

    assert secret not in str(error.value)
    assert toml_value not in str(error.value)


def test_toml_parser_remains_authoritative_for_invalid_leading_zero_integer(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, "[baremetal_harness]\nmax_turns = 01\n")

    with pytest.raises(ValueError, match="invalid config file") as error:
        ConfigStore(path).read()

    assert "01" not in str(error.value)


@pytest.mark.parametrize(("toml_value", "expected"), [("1", 1), ("24", 24)])
def test_toml_integer_fields_accept_canonical_ascii_digits(
    tmp_path: Path,
    toml_value: str,
    expected: int,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        (
            "# max_turns = 0x10\n"
            "[baremetal_harness]\n"
            'docker_image = """a string containing\n'
            "max_turns = 0o10\n"
            '"""\n'
            f"max_turns = {toml_value} # context_tokens = 1_000\n"
        ),
    )

    assert ConfigStore(path).read().get("max_turns") == expected


@pytest.mark.parametrize(
    "source",
    [
        '["baremetal_harness"]\nmax_turns = 16\n',
        "['baremetal_harness']\nmax_turns = 16\n",
        '[baremetal_harness]\n"max_turns" = 16\n',
        "[baremetal_harness]\n'max_turns' = 16\n",
        "baremetal_harness.max_turns = 16\n",
        '"baremetal_harness"."max_turns" = 16\n',
        "'baremetal_harness'.'max_turns' = 16\n",
        '[baremetal_harness]\n"max\\u005fturns" = 16\n',
        '["mini\\u0063law"]\nmax_turns = 16\n',
        'baremetal_harness."max\\u005fturns" = 16\n',
    ],
)
def test_toml_integer_fields_accept_semantic_key_aliases(
    tmp_path: Path,
    source: str,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, source)

    assert ConfigStore(path).read().get("max_turns") == 16


@pytest.mark.parametrize(
    "source",
    [
        '["baremetal_harness"]\nmax_turns = 0x10\n',
        "['baremetal_harness']\nmax_turns = 0x10\n",
        '[baremetal_harness]\n"max_turns" = 0x10\n',
        "[baremetal_harness]\n'max_turns' = 0x10\n",
        "baremetal_harness.max_turns = 0x10\n",
        '"baremetal_harness"."max_turns" = 0x10\n',
        "'baremetal_harness'.'max_turns' = 0x10\n",
        '[baremetal_harness]\n"max\\u005fturns" = 0x10\n',
        '["mini\\u0063law"]\nmax_turns = 0x10\n',
        'baremetal_harness."max\\u005fturns" = 0x10\n',
    ],
)
def test_toml_integer_key_aliases_reject_noncanonical_scalar_lexemes(
    tmp_path: Path,
    source: str,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, source)

    with pytest.raises(
        ValueError,
        match="max_turns must be a positive integer",
    ) as error:
        ConfigStore(path).read()

    assert "0x10" not in str(error.value)


@pytest.mark.parametrize(
    ("string_source", "decoded"),
    [
        ('"""value""""', 'value"'),
        ('"""value"""""', 'value""'),
        ("'''value''''", "value'"),
        ("'''value'''''", "value''"),
    ],
)
def test_toml_multiline_quote_runs_preserve_following_canonical_integer(
    tmp_path: Path,
    string_source: str,
    decoded: str,
) -> None:
    source = f"[baremetal_harness]\ndocker_image = {string_source}\nmax_turns = 16\n"
    assert tomllib.loads(source)["baremetal_harness"]["docker_image"] == decoded
    path = tmp_path / "config.toml"
    write_config(path, source)

    document = ConfigStore(path).read()

    assert document.get("docker_image") == decoded
    assert document.get("max_turns") == 16


@pytest.mark.parametrize(
    ("string_source", "decoded"),
    [
        ('"""value""""', 'value"'),
        ('"""value"""""', 'value""'),
        ("'''value''''", "value'"),
        ("'''value'''''", "value''"),
    ],
)
def test_toml_multiline_quote_runs_expose_following_noncanonical_integer(
    tmp_path: Path,
    string_source: str,
    decoded: str,
) -> None:
    source = f"[baremetal_harness]\ndocker_image = {string_source}\nmax_turns = 0x10\n"
    parsed = tomllib.loads(source)
    assert parsed["baremetal_harness"]["docker_image"] == decoded
    assert parsed["baremetal_harness"]["max_turns"] == 16
    path = tmp_path / "config.toml"
    write_config(path, source)

    with pytest.raises(
        ValueError,
        match="max_turns must be a positive integer",
    ) as error:
        ConfigStore(path).read()

    assert "0x10" not in str(error.value)


@pytest.mark.parametrize(
    "key",
    ["max_turns", '"max_turns"', "'max_turns'", '"max\\u005fturns"'],
)
def test_root_inline_baremetal_harness_table_accepts_canonical_integer_key_aliases(
    tmp_path: Path,
    key: str,
) -> None:
    source = f'baremetal_harness = {{ model = "demo", {key} = 16 }}\n'
    assert tomllib.loads(source)["baremetal_harness"]["max_turns"] == 16
    path = tmp_path / "config.toml"
    write_config(path, source)

    document = ConfigStore(path).read()

    assert document.get("model") == "demo"
    assert document.get("max_turns") == 16


@pytest.mark.parametrize(
    "key",
    ["max_turns", '"max_turns"', "'max_turns'", '"max\\u005fturns"'],
)
@pytest.mark.parametrize("toml_value", ["+1", "0x10", "1_000", "1.0"])
def test_root_inline_baremetal_harness_table_rejects_noncanonical_integer_lexemes(
    tmp_path: Path,
    key: str,
    toml_value: str,
) -> None:
    secret = "inline-secret-must-not-appear"
    source = f'baremetal_harness = {{ api_key = "{secret}", {key} = {toml_value} }}\n'
    assert tomllib.loads(source)["baremetal_harness"]["max_turns"] is not None
    path = tmp_path / "config.toml"
    write_config(path, source)

    with pytest.raises(
        ValueError,
        match="max_turns must be a positive integer",
    ) as error:
        ConfigStore(path).read()

    assert secret not in str(error.value)
    assert toml_value not in str(error.value)


def test_root_inline_baremetal_harness_table_ignores_strings_and_trailing_comment(
    tmp_path: Path,
) -> None:
    source = (
        'baremetal_harness = { model = "fake max_turns = 0x10 # text", '
        "max_turns = 16 } # max_turns = 0x10\n"
    )
    path = tmp_path / "config.toml"
    write_config(path, source)

    document = ConfigStore(path).read()

    assert document.get("model") == "fake max_turns = 0x10 # text"
    assert document.get("max_turns") == 16


def test_tomllib_rejects_comment_inside_root_inline_table(tmp_path: Path) -> None:
    source = (
        "baremetal_harness = { max_turns = 16, # comments are not allowed here\n"
        'model = "demo" }\n'
    )
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads(source)
    path = tmp_path / "config.toml"
    write_config(path, source)

    with pytest.raises(ValueError, match="invalid config file"):
        ConfigStore(path).read()


@pytest.mark.parametrize(
    "nested",
    [
        '{ max_turns = 0x10, text = "max_turns = +1" }',
        '[{ max_turns = 0x10 }, "max_turns = 1_000"]',
    ],
)
def test_root_inline_baremetal_harness_table_ignores_nested_fake_assignments(
    tmp_path: Path,
    nested: str,
) -> None:
    source = f"baremetal_harness = {{ max_turns = 16, unknown = {nested} }}\n"
    path = tmp_path / "config.toml"
    write_config(path, source)

    with pytest.raises(ValueError, match="unknown config fields"):
        ConfigStore(path).read()


@pytest.mark.parametrize(
    "source",
    [
        "baremetal_harness = { max_turns = 16, max_turns = 0x10 }\n",
        ('baremetal_harness = { max_turns = 0x10 }\n[baremetal_harness]\nmodel = "demo"\n'),
        ("[baremetal_harness]\nmax_turns = 16\nmax_turns = 0x10\n"),
        ("baremetal_harness = { max_turns = 0x10 }\nbaremetal_harness = { max_turns = 24 }\n"),
    ],
)
def test_tomllib_remains_authoritative_for_duplicate_or_redefined_keys(
    tmp_path: Path,
    source: str,
) -> None:
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads(source)
    path = tmp_path / "config.toml"
    write_config(path, source)

    with pytest.raises(ValueError, match="invalid config file") as error:
        ConfigStore(path).read()

    assert "0x10" not in str(error.value)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "unexpected = true\nbaremetal_harness = { max_turns = 0x10 }\n",
            "unknown root config fields",
        ),
        (
            "baremetal_harness = { unknown = true, max_turns = 0x10 }\n",
            "unknown config fields",
        ),
    ],
)
def test_strict_schema_errors_precede_inline_integer_lexeme_errors(
    tmp_path: Path,
    source: str,
    message: str,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, source)

    with pytest.raises(ValueError, match=message) as error:
        ConfigStore(path).read()

    assert "0x10" not in str(error.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://model.invalid:not-a-port/v1",
        "https://model.invalid:99999/v1",
    ],
)
def test_file_base_url_rejects_invalid_ports(
    tmp_path: Path,
    base_url: str,
) -> None:
    path = tmp_path / "config.toml"
    write_config(path, f'[baremetal_harness]\nbase_url = "{base_url}"\n')

    with pytest.raises(ValueError, match="base_url"):
        ConfigStore(path).read()


def test_resolved_view_merges_defaults_without_environment(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path, '[baremetal_harness]\nmodel = "file-model"\napi_key = "file-secret-1234"\n'
    )

    view = ConfigStore(path).resolved_view()

    assert view["model"] == "file-model"
    assert view["max_turns"] == 16
    assert view["api_key"] == "file-secret-1234"


def test_strings_round_trip_as_valid_toml_without_changing_secret(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    model = 'quoted "model" with \\ slash\n雪 and DEL \x7f inside'
    api_key = ' exact "key" with \\ slash\n雪 and DEL \x7f '

    store.initialize(
        base_url="https://model.invalid/v1",
        model=model,
        api_key=api_key,
    )

    document = store.read()
    assert document.get("model") == model
    assert document.get("api_key") == api_key


def test_string_with_lone_surrogate_is_rejected_without_secret_value(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")

    with pytest.raises(ValueError, match="Unicode scalar") as error:
        store.set("api_key", "secret-\ud800-value")

    assert "secret-" not in str(error.value)


def test_initialize_set_and_unset_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "private" / "config.toml")

    store.initialize(
        base_url="https://model.invalid/v1",
        model="demo-model",
        api_key="file-secret-1234",
    )
    store.set("max_turns", "24")
    store.unset("model")

    document = store.read()
    view = store.resolved_view()
    assert document.get("workspace") == Path(".")
    assert document.get("api_key") == "file-secret-1234"
    assert view["model"] == "fake"
    assert view["max_turns"] == 24


def test_set_none_keeps_optional_base_url_absent(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")

    store.set("base_url", None)

    assert "base_url" not in store.read().values


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_new_directory_and_config_use_owner_only_modes(tmp_path: Path) -> None:
    parent = tmp_path / "private"
    store = ConfigStore(parent / "config.toml")

    store.set("model", "demo")

    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_existing_custom_parent_mode_is_not_changed(tmp_path: Path) -> None:
    parent = tmp_path / "project"
    parent.mkdir(mode=0o755)

    ConfigStore(parent / "config.toml").set("model", "demo")

    assert stat.S_IMODE(parent.stat().st_mode) == 0o755


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_write_applies_file_mode_by_descriptor_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    original_chmod = os.chmod
    original_fchmod = os.fchmod
    original_replace = os.replace
    file_descriptor: int | None = None
    fchmod_called = False

    def track_chmod(path: os.PathLike[str] | str, mode: int) -> None:
        if Path(path) == tmp_path:
            original_chmod(path, mode)
            return
        raise AssertionError(f"unexpected file pathname chmod: {path}")

    def track_fchmod(descriptor: int, mode: int) -> None:
        nonlocal file_descriptor, fchmod_called
        file_descriptor = descriptor
        fchmod_called = True
        original_fchmod(descriptor, mode)

    def track_replace(
        source: Path,
        target: Path,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        assert fchmod_called
        assert file_descriptor is not None
        assert stat.S_IMODE(os.fstat(file_descriptor).st_mode) == 0o600
        original_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "chmod", track_chmod)
    monkeypatch.setattr(os, "fchmod", track_fchmod)
    monkeypatch.setattr(os, "replace", track_replace)

    store.set("model", "demo")

    assert fchmod_called
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor contract")
def test_write_uses_verified_parent_descriptor_for_create_and_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    original_open = os.open
    original_replace = os.replace
    relative_create_dir_fds: list[int] = []
    replace_dir_fds: list[tuple[int | None, int | None]] = []

    def track_open(
        file: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if (
            dir_fd is not None
            and flags & os.O_CREAT
            and str(file).startswith(".config.toml.baremetal_harness.")
        ):
            relative_create_dir_fds.append(dir_fd)
        if dir_fd is None:
            return original_open(file, flags, mode)
        return original_open(file, flags, mode, dir_fd=dir_fd)

    def track_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        replace_dir_fds.append((src_dir_fd, dst_dir_fd))
        original_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "replace", track_replace)

    store.set("model", "demo")

    assert len(relative_create_dir_fds) == 1
    assert replace_dir_fds == [(relative_create_dir_fds[0], relative_create_dir_fds[0])]


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor contract")
def test_write_rejects_intermediate_parent_replaced_by_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "ancestor"
    store = ConfigStore(ancestor / "nested" / "config.toml")
    store.set("model", "before")
    original_replace = os.replace
    moved_ancestor = tmp_path / "moved-ancestor"
    swapped = False

    def swap_parent_then_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        nonlocal swapped
        if not swapped:
            ancestor.rename(moved_ancestor)
            ancestor.symlink_to(moved_ancestor, target_is_directory=True)
            swapped = True
        original_replace(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(os, "replace", swap_parent_then_replace)

    with pytest.raises(ConfigPathError, match="symbolic link"):
        store.set("model", "after")


def test_failed_replace_preserves_original_and_cleans_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.set("model", "before")
    original = store.path.read_bytes()

    def fail_replace(
        source: Path,
        target: Path,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(ConfigPersistenceError, match="persist"):
        store.set("model", "after")

    assert store.path.read_bytes() == original
    assert list(tmp_path.glob(".config.toml.baremetal_harness.*.tmp")) == []


def _set_config_field_after_read(
    path: str,
    field: str,
    value: str,
    ready: Event,
    release: Event,
) -> None:
    from baremetal_harness.config_store import ConfigStore

    store = ConfigStore(Path(path))
    original_read = store.read

    def coordinated_read():
        document = original_read()
        ready.set()
        if not release.wait(timeout=10):
            raise RuntimeError("timed out waiting for concurrent mutation")
        return document

    store.read = coordinated_read  # type: ignore[method-assign]
    store.set(field, value)


def _initialize_config_after_read(
    path: str,
    ready: Event,
    release: Event,
) -> None:
    from baremetal_harness.config_store import ConfigStore

    store = ConfigStore(Path(path))
    original_read = store.read

    def coordinated_read():
        document = original_read()
        ready.set()
        if not release.wait(timeout=10):
            raise RuntimeError("timed out waiting for concurrent mutation")
        return document

    store.read = coordinated_read  # type: ignore[method-assign]
    store.initialize(
        base_url="https://after.invalid/v1",
        model="after",
        api_key="after-secret-1234",
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock contract")
def test_concurrent_distinct_mutations_do_not_lose_updates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    ConfigStore(path).set("model", "before")
    first_ready = Event()
    second_ready = Event()
    first_release = Event()
    second_release = Event()
    first = Process(
        target=_set_config_field_after_read,
        args=(
            str(path),
            "model",
            "after",
            first_ready,
            first_release,
        ),
    )
    second = Process(
        target=_set_config_field_after_read,
        args=(
            str(path),
            "max_turns",
            "24",
            second_ready,
            second_release,
        ),
    )
    first.start()
    assert first_ready.wait(timeout=10)
    second.start()

    second_was_blocked = not second_ready.wait(timeout=0.2)
    first_release.set()
    first.join(timeout=10)
    assert first.exitcode == 0
    assert second_ready.wait(timeout=10)
    second_release.set()
    second.join(timeout=10)
    assert second.exitcode == 0

    document = ConfigStore(path).read()
    assert second_was_blocked
    assert document.get("model") == "after"
    assert document.get("max_turns") == 24


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock contract")
def test_explicit_init_preserves_concurrent_field_update(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    ConfigStore(path).set("model", "before")
    init_ready = Event()
    update_ready = Event()
    init_release = Event()
    update_release = Event()
    initializer = Process(
        target=_initialize_config_after_read,
        args=(str(path), init_ready, init_release),
    )
    updater = Process(
        target=_set_config_field_after_read,
        args=(
            str(path),
            "max_turns",
            "24",
            update_ready,
            update_release,
        ),
    )
    initializer.start()
    assert init_ready.wait(timeout=10)
    updater.start()

    update_was_blocked = not update_ready.wait(timeout=0.2)
    init_release.set()
    initializer.join(timeout=10)
    assert initializer.exitcode == 0
    assert update_ready.wait(timeout=10)
    update_release.set()
    updater.join(timeout=10)
    assert updater.exitcode == 0

    document = ConfigStore(path).read()
    assert update_was_blocked
    assert document.get("model") == "after"
    assert document.get("max_turns") == 24


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock contract")
def test_same_store_threads_serialize_distinct_mutations(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.set("model", "before")
    first_read = ThreadEvent()
    release_first = ThreadEvent()
    second_read = ThreadEvent()
    failures: list[BaseException] = []
    original_read = store.read

    def coordinated_read():
        document = original_read()
        if current_thread().name == "first-config-mutation":
            first_read.set()
            if not release_first.wait(timeout=10):
                raise RuntimeError("timed out waiting to release first mutation")
        else:
            second_read.set()
        return document

    def mutate(field: str, value: str) -> None:
        try:
            store.set(field, value)
        except BaseException as error:
            failures.append(error)

    store.read = coordinated_read  # type: ignore[method-assign]
    first = Thread(
        target=mutate,
        args=("model", "after"),
        name="first-config-mutation",
    )
    second = Thread(
        target=mutate,
        args=("max_turns", "24"),
        name="second-config-mutation",
    )
    first.start()
    assert first_read.wait(timeout=10)
    second.start()

    second_entered_transaction = second_read.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert not second_entered_transaction
    document = ConfigStore(store.path).read()
    assert document.get("model") == "after"
    assert document.get("max_turns") == 24


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock contract")
def test_transaction_is_reentrant_and_cleans_up_after_nested_exception(
    tmp_path: Path,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    failed_descriptor: int | None = None

    with pytest.raises(RuntimeError, match="nested failure"):
        with store._transaction() as outer_descriptor:
            failed_descriptor = outer_descriptor
            with store._transaction() as nested_descriptor:
                assert nested_descriptor == outer_descriptor
                raise RuntimeError("nested failure")

    assert store._transaction_descriptor is None
    assert store._transaction_depth == 0
    assert store._transaction_owner is None
    assert failed_descriptor is not None
    with pytest.raises(OSError):
        os.fstat(failed_descriptor)

    with store._transaction() as recovered_descriptor:
        assert recovered_descriptor >= 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX coordination contract")
def test_first_run_coordination_releases_lock_and_descriptor_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fcntl

    store = ConfigStore(tmp_path / "config.toml")
    original_flock = fcntl.flock
    lock_descriptors: list[int] = []
    operations: list[int] = []

    def track_flock(descriptor: int, operation: int) -> None:
        lock_descriptors.append(descriptor)
        operations.append(operation)
        original_flock(descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", track_flock)

    with pytest.raises(RuntimeError, match="cancelled"):
        with store.coordinate_first_run() as needs_initialization:
            assert needs_initialization is True
            raise RuntimeError("cancelled")

    assert operations == [fcntl.LOCK_EX, fcntl.LOCK_UN]
    assert len(set(lock_descriptors)) == 1
    with pytest.raises(OSError):
        os.fstat(lock_descriptors[0])
    assert list(tmp_path.glob("*.lock")) == []

    with store.coordinate_first_run() as needs_initialization:
        assert needs_initialization is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX coordination contract")
def test_first_run_coordination_closes_descriptor_when_unlock_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fcntl

    store = ConfigStore(tmp_path / "config.toml")
    original_flock = fcntl.flock
    lock_descriptor: int | None = None

    def fail_unlock(descriptor: int, operation: int) -> None:
        nonlocal lock_descriptor
        lock_descriptor = descriptor
        if operation == fcntl.LOCK_UN:
            raise OSError("injected unlock failure")
        original_flock(descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", fail_unlock)

    with pytest.raises(OSError, match="unlock failure"):
        with store.coordinate_first_run() as needs_initialization:
            assert needs_initialization is True

    assert lock_descriptor is not None
    with pytest.raises(OSError):
        os.fstat(lock_descriptor)


@pytest.mark.parametrize("platform_name", ["nt", "unsupported"])
def test_first_run_coordination_rejects_unsupported_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    monkeypatch.setattr("baremetal_harness.config_store.os.name", platform_name)

    with pytest.raises(
        ConfigPersistenceError,
        match="coordination is unsupported",
    ), store.coordinate_first_run():
        pytest.fail("must not enter coordination")


def test_directory_fsync_failure_reports_replaced_file_without_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.set("model", "before")
    original_fsync = os.fsync

    def fail_directory_fsync(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("injected directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory_fsync)

    with pytest.raises(ConfigPersistenceError, match="persist"):
        store.set("model", "after")

    assert store.read().get("model") == "after"
    assert list(tmp_path.glob(".config.toml.baremetal_harness.*.tmp")) == []


def test_rendered_view_redacts_api_key(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.toml")
    store.initialize(
        base_url="https://model.invalid/v1",
        model="demo",
        api_key="file-secret-1234",
    )

    rendered = render_config_view(store)

    assert "file-secret-1234" not in rendered
    assert "********1234" in rendered


def test_rendered_view_has_exact_display_only_toml_layout(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    write_config(
        path,
        """
[baremetal_harness]
model = "demo"
base_url = "https://model.invalid/v1"
api_key = "file-secret-1234"
require_strong_sandbox = true
""".strip(),
    )

    assert render_config_view(ConfigStore(path)) == (
        "# BareMetal Harness configuration display (display-only; not writable TOML)\n"
        f"# path = {path}\n"
        "# exists = true\n"
        "\n"
        "[baremetal_harness]\n"
        f'data_dir = "{Path.home() / ".baremetal_harness"}"\n'
        f'workspace = "{Path.cwd()}"\n'
        'model = "demo"\n'
        'base_url = "https://model.invalid/v1"\n'
        'api_key = "********1234"\n'
        "require_strong_sandbox = true\n"
        'docker_image = "python:3.12-slim"\n'
        "max_turns = 16\n"
        "max_tool_calls = 32\n"
        "context_tokens = 32000\n"
        "reserve_output_tokens = 4000\n"
    )
