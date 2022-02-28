import ctypes.util
import threading
from typing import Any, Text, Optional, Union
from os import PathLike

class MagicException(Exception):
    message: Any = ...
    def __init__(self, message: Any) -> None: ...

class Magic:
    flags: int = ...
    cookie: Any = ...
    lock: threading.Lock = ...
    def __init__(self, mime: bool = ..., magic_file: Optional[Any] = ..., mime_encoding: bool = ..., keep_going: bool = ..., uncompress: bool = ..., raw: bool = ...) -> None: ...
    def from_buffer(self, buf: Union[bytes, str]) -> Text: ...
    def from_file(self, filename: Union[bytes, str, PathLike]) -> Text: ...
    def from_descriptor(self, fd: int, mime: bool = ...) -> Text: ...
    def setparam(self, param: Any, val: Any): ...
    def getparam(self, param: Any): ...
    def __del__(self) -> None: ...

def from_file(filename: Union[bytes, str, PathLike], mime: bool = ...) -> Text: ...
def from_buffer(buffer: Union[bytes, str], mime: bool = ...) -> Text: ...
def from_descriptor(fd: int, mime: bool = ...) -> Text: ...

libmagic: Any
dll: Any
windows_dlls: Any
platform_to_lib: Any
platform: Any
magic_t = ctypes.c_void_p

def errorcheck_null(result: Any, func: Any, args: Any): ...
def errorcheck_negative_one(result: Any, func: Any, args: Any): ...
def maybe_decode(s: Union[bytes, str]) -> str: ...
def coerce_filename(filename: Any): ...

magic_open: Any
magic_close: Any
magic_error: Any
magic_errno: Any

def magic_file(cookie: Any, filename: Any): ...
def magic_buffer(cookie: Any, buf: Any): ...
def magic_descriptor(cookie: Any, fd: int): ...
def magic_load(cookie: Any, filename: Any): ...

magic_setflags: Any
magic_check: Any
magic_compile: Any

def magic_setparam(cookie: Any, param: Any, val: Any): ...
def magic_getparam(cookie: Any, param: Any): ...

magic_version: Any

def version(): ...

MAGIC_NONE: int
MAGIC_DEBUG: int
MAGIC_SYMLINK: int
MAGIC_COMPRESS: int
MAGIC_DEVICES: int
MAGIC_MIME_TYPE: int
MAGIC_MIME_ENCODING: int
MAGIC_MIME: int
MAGIC_CONTINUE: int
MAGIC_CHECK: int
MAGIC_PRESERVE_ATIME: int
MAGIC_RAW: int
MAGIC_ERROR: int
MAGIC_NO_CHECK_COMPRESS: int
MAGIC_NO_CHECK_TAR: int
MAGIC_NO_CHECK_SOFT: int
MAGIC_NO_CHECK_APPTYPE: int
MAGIC_NO_CHECK_ELF: int
MAGIC_NO_CHECK_ASCII: int
MAGIC_NO_CHECK_TROFF: int
MAGIC_NO_CHECK_FORTRAN: int
MAGIC_NO_CHECK_TOKENS: int
MAGIC_PARAM_INDIR_MAX: int
MAGIC_PARAM_NAME_MAX: int
MAGIC_PARAM_ELF_PHNUM_MAX: int
MAGIC_PARAM_ELF_SHNUM_MAX: int
MAGIC_PARAM_ELF_NOTES_MAX: int
MAGIC_PARAM_REGEX_MAX: int
MAGIC_PARAM_BYTES_MAX: int
