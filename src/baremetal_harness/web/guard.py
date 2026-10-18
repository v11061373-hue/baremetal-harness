import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit


class UnsafeUrl(ValueError):
    pass


def _default_resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        records = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise UnsafeUrl(f"cannot resolve host: {host}") from error
    return tuple(record[4][0] for record in records)


def _is_blocked(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    if parsed.version == 6 and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_multicast
        or parsed.is_reserved
        or parsed.is_unspecified
    )


class UrlGuard:
    """Reject URLs a model must not be able to reach.

    The agent chooses fetch targets, so an unguarded fetch tool is a
    server-side request forgery primitive: it can probe localhost, the private
    network and cloud metadata endpoints. Every hop of a redirect chain is
    checked, because only the first URL is the one a human ever sees.
    """

    def __init__(
        self,
        *,
        resolver: Callable[[str, int], tuple[str, ...]] | None = None,
        allow_private: bool = False,
    ) -> None:
        self._resolve = resolver or _default_resolver
        self._allow_private = allow_private

    def check(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            raise UnsafeUrl("only http and https URLs may be fetched")
        host = parts.hostname
        if not host:
            raise UnsafeUrl("URL must include a host")
        if parts.username or parts.password:
            raise UnsafeUrl("URL must not carry credentials")
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError as error:
            raise UnsafeUrl("URL has an invalid port") from error
        if self._allow_private:
            return
        for address in self._resolve(host, port):
            if _is_blocked(address):
                raise UnsafeUrl(
                    f"refusing to fetch a private or loopback address: {host}"
                )
