"""Carry exact request targets across Requests and urllib3 without ambient state."""

from urllib.parse import urlparse


def join_request_target(base_url: str, quoted_path: str) -> str:
    base_path = urlparse(base_url).path or "/"
    target = "/" if base_path == "/" else f"{base_path.rstrip('/')}/"
    return target + quoted_path.lstrip("/")


class RequestTargetURL(str):
    """A Requests URL with an explicit, already-quoted origin-form target.

    Requests expects a string URL and copies it unchanged for authentication
    retries. Redirect resolution replaces the URL, so a redirect cannot inherit
    the initial target. Keeping the value here also avoids adding undeclared
    attributes to third-party PreparedRequest objects.
    """

    __slots__ = ("_request_target",)

    def __new__(cls, url: str, request_target: str):
        value = super().__new__(cls, url)
        value._request_target = request_target
        return value

    @property
    def request_target(self) -> str:
        return self._request_target


class RawRequestTarget(str):
    """Mark the adapter's final wire target, including HTTP proxy absolute form."""

    __slots__ = ()


class PathPreservingPoolMixin:
    """Pass the target explicitly through urllib3's request/retry call chain.

    urllib3 normalizes URLs in urlopen(). Its extra request arguments survive
    retries, letting _make_request() restore the wire target just before the
    connection sends it. No target is stored on a pool, connection or thread.
    Requests owns redirects for these pools (HTTPAdapter uses redirect=False);
    reject raw-target calls that would delegate redirects to urllib3 instead.
    """

    def urlopen(
        self, method, url, body=None, headers=None, retries=None, redirect=True,
        assert_same_host=True, **kwargs,
    ):
        if isinstance(url, RawRequestTarget):
            kwargs["request_target"] = str(url)
        if kwargs.get("request_target") is not None and redirect:
            raise ValueError("Raw-target redirects must be handled by Requests")
        return super().urlopen(
            method, url, body, headers, retries, redirect, assert_same_host, **kwargs,
        )

    def _make_request(self, conn, method, url, *args, request_target=None, **kwargs):
        if request_target is not None:
            url = request_target
        return super()._make_request(conn, method, url, *args, **kwargs)
