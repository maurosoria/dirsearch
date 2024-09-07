import httpx
from lib.core.settings import (
    DEFAULT_ENCODING,
    ITER_CHUNK_SIZE,
    MAX_RESPONSE_SIZE,
    UNKNOWN,
)
from lib.parse.url import clean_path, parse_path
from lib.utils.common import is_binary


class Response:
    def __init__(self, response: httpx.Response) -> None:
        self.url = str(response.url)
        self.full_path = parse_path(self.url)
        self.path = clean_path(self.full_path)
        self.status = response.status_code
        self.headers = response.headers
        self.redirect = self.headers.get("location") or ""
        self.history = [str(res.url) for res in response.history]
        self.content = ""
        self.body = b""

    @classmethod
    async def create(cls, response: httpx.Response) -> "Response":
        self = cls(response)
        async for chunk in response.aiter_bytes(chunk_size=ITER_CHUNK_SIZE):
            self.body += chunk

            if len(self.body) >= MAX_RESPONSE_SIZE or (
                "content-length" in self.headers and is_binary(self.body)
            ):
                break

        if not is_binary(self.body):
            try:
                self.content = self.body.decode(
                    response.encoding or DEFAULT_ENCODING, errors="ignore"
                )
            except LookupError:
                self.content = self.body.decode(DEFAULT_ENCODING, errors="ignore")

        return self

    @property
    def type(self) -> str:
        if "content-type" in self.headers:
            return self.headers.get("content-type").split(";")[0]

        return UNKNOWN

    @property
    def length(self) -> int:
        try:
            return int(self.headers.get("content-length"))
        except TypeError:
            return len(self.body)

    def __hash__(self) -> int:
        return hash(self.body)

    def __eq__(self, other: object) -> bool:
        return (self.status, self.body, self.redirect) == (
            other.status,
            other.body,
            other.redirect,
        )
