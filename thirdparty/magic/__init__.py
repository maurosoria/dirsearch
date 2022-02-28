"""
magic is a wrapper around the libmagic file identification library.

See README for more information.

Usage:

>>> import magic
>>> magic.from_file("testdata/test.pdf")
'PDF document, version 1.2'
>>> magic.from_file("testdata/test.pdf", mime=True)
'application/pdf'
>>> magic.from_buffer(open("testdata/test.pdf").read(1024))
'PDF document, version 1.2'
>>>

"""

import sys
import glob
import ctypes
import ctypes.util
import threading
import logging

from ctypes import c_char_p, c_int, c_size_t, c_void_p, byref, POINTER

# avoid shadowing the real open with the version from compat.py
_real_open = open


class MagicException(Exception):
    def __init__(self, message):
        super(Exception, self).__init__(message)
        self.message = message


class Magic:
    """
    Magic is a wrapper around the libmagic C library.
    """

    def __init__(self, mime=False, magic_file=None, mime_encoding=False,
                 keep_going=False, uncompress=False, raw=False, extension=False):
        """
        Create a new libmagic wrapper.

        mime - if True, mimetypes are returned instead of textual descriptions
        mime_encoding - if True, codec is returned
        magic_file - use a mime database other than the system default
        keep_going - don't stop at the first match, keep going
        uncompress - Try to look inside compressed files.
        raw - Do not try to decode "non-printable" chars.
        extension - Print a slash-separated list of valid extensions for the file type found.
        """
        self.flags = MAGIC_NONE
        if mime:
            self.flags |= MAGIC_MIME_TYPE
        if mime_encoding:
            self.flags |= MAGIC_MIME_ENCODING
        if keep_going:
            self.flags |= MAGIC_CONTINUE
        if uncompress:
            self.flags |= MAGIC_COMPRESS
        if raw:
            self.flags |= MAGIC_RAW
        if extension:
            self.flags |= MAGIC_EXTENSION

        self.cookie = magic_open(self.flags)
        self.lock = threading.Lock()

        magic_load(self.cookie, magic_file)

        # MAGIC_EXTENSION was added in 523 or 524, so bail if
        # it doesn't appear to be available
        if extension and (not _has_version or version() < 524):
            raise NotImplementedError('MAGIC_EXTENSION is not supported in this version of libmagic')

        # For https://github.com/ahupp/python-magic/issues/190
        # libmagic has fixed internal limits that some files exceed, causing
        # an error.  We can avoid this (at least for the sample file given)
        # by bumping the limit up.  It's not clear if this is a general solution
        # or whether other internal limits should be increased, but given
        # the lack of other reports I'll assume this is rare.
        if _has_param:
            try:
                self.setparam(MAGIC_PARAM_NAME_MAX, 64)
            except MagicException as e:
                # some versions of libmagic fail this call,
                # so rather than fail hard just use default behavior
                pass

    def from_buffer(self, buf):
        """
        Identify the contents of `buf`
        """
        with self.lock:
            try:
                # if we're on python3, convert buf to bytes
                # otherwise this string is passed as wchar*
                # which is not what libmagic expects
                # NEXTBREAK: only take bytes
                if type(buf) == str and str != bytes:
                    buf = buf.encode('utf-8', errors='replace')
                return maybe_decode(magic_buffer(self.cookie, buf))
            except MagicException as e:
                return self._handle509Bug(e)

    def from_file(self, filename):
        # raise FileNotFoundException or IOError if the file does not exist
        with _real_open(filename):
            pass

        with self.lock:
            try:
                return maybe_decode(magic_file(self.cookie, filename))
            except MagicException as e:
                return self._handle509Bug(e)

    def from_descriptor(self, fd):
        with self.lock:
            try:
                return maybe_decode(magic_descriptor(self.cookie, fd))
            except MagicException as e:
                return self._handle509Bug(e)

    def _handle509Bug(self, e):
        # libmagic 5.09 has a bug where it might fail to identify the
        # mimetype of a file and returns null from magic_file (and
        # likely _buffer), but also does not return an error message.
        if e.message is None and (self.flags & MAGIC_MIME_TYPE):
            return "application/octet-stream"
        else:
            raise e

    def setparam(self, param, val):
        return magic_setparam(self.cookie, param, val)

    def getparam(self, param):
        return magic_getparam(self.cookie, param)

    def __del__(self):
        # no _thread_check here because there can be no other
        # references to this object at this point.

        # during shutdown magic_close may have been cleared already so
        # make sure it exists before using it.

        # the self.cookie check should be unnecessary and was an
        # incorrect fix for a threading problem, however I'm leaving
        # it in because it's harmless and I'm slightly afraid to
        # remove it.
        if hasattr(self, 'cookie') and self.cookie and magic_close:
            magic_close(self.cookie)
            self.cookie = None


_instances = {}


def _get_magic_type(mime):
    i = _instances.get(mime)
    if i is None:
        i = _instances[mime] = Magic(mime=mime)
    return i


def from_file(filename, mime=False):
    """"
    Accepts a filename and returns the detected filetype.  Return
    value is the mimetype if mime=True, otherwise a human readable
    name.

    >>> magic.from_file("testdata/test.pdf", mime=True)
    'application/pdf'
    """
    m = _get_magic_type(mime)
    return m.from_file(filename)


def from_buffer(buffer, mime=False):
    """
    Accepts a binary string and returns the detected filetype.  Return
    value is the mimetype if mime=True, otherwise a human readable
    name.

    >>> magic.from_buffer(open("testdata/test.pdf").read(1024))
    'PDF document, version 1.2'
    """
    m = _get_magic_type(mime)
    return m.from_buffer(buffer)


def from_descriptor(fd, mime=False):
    """
    Accepts a file descriptor and returns the detected filetype.  Return
    value is the mimetype if mime=True, otherwise a human readable
    name.

    >>> f = open("testdata/test.pdf")
    >>> magic.from_descriptor(f.fileno())
    'PDF document, version 1.2'
    """
    m = _get_magic_type(mime)
    return m.from_descriptor(fd)

from . import loader
libmagic = loader.load_lib()

magic_t = ctypes.c_void_p


def errorcheck_null(result, func, args):
    if result is None:
        err = magic_error(args[0])
        raise MagicException(err)
    else:
        return result


def errorcheck_negative_one(result, func, args):
    if result == -1:
        err = magic_error(args[0])
        raise MagicException(err)
    else:
        return result


# return str on python3.  Don't want to unconditionally
# decode because that results in unicode on python2
def maybe_decode(s):
    # NEXTBREAK: remove
    if str == bytes:
        return s
    else:
        # backslashreplace here because sometimes libmagic will return metadata in the charset
        # of the file, which is unknown to us (e.g the title of a Word doc)
        return s.decode('utf-8', 'backslashreplace')


try:
    from os import PathLike
    def unpath(filename):
        if isinstance(filename, PathLike):
            return filename.__fspath__()
        else:
            return filename
except ImportError:
    def unpath(filename):
        return filename

def coerce_filename(filename):
    if filename is None:
        return None

    filename = unpath(filename)

    # ctypes will implicitly convert unicode strings to bytes with
    # .encode('ascii').  If you use the filesystem encoding
    # then you'll get inconsistent behavior (crashes) depending on the user's
    # LANG environment variable
    # NEXTBREAK: remove
    is_unicode = (sys.version_info[0] <= 2 and
                 isinstance(filename, unicode)) or \
                 (sys.version_info[0] >= 3 and
                  isinstance(filename, str))
    if is_unicode:
        return filename.encode('utf-8', 'surrogateescape')
    else:
        return filename


magic_open = libmagic.magic_open
magic_open.restype = magic_t
magic_open.argtypes = [c_int]

magic_close = libmagic.magic_close
magic_close.restype = None
magic_close.argtypes = [magic_t]

magic_error = libmagic.magic_error
magic_error.restype = c_char_p
magic_error.argtypes = [magic_t]

magic_errno = libmagic.magic_errno
magic_errno.restype = c_int
magic_errno.argtypes = [magic_t]

_magic_file = libmagic.magic_file
_magic_file.restype = c_char_p
_magic_file.argtypes = [magic_t, c_char_p]
_magic_file.errcheck = errorcheck_null


def magic_file(cookie, filename):
    return _magic_file(cookie, coerce_filename(filename))


_magic_buffer = libmagic.magic_buffer
_magic_buffer.restype = c_char_p
_magic_buffer.argtypes = [magic_t, c_void_p, c_size_t]
_magic_buffer.errcheck = errorcheck_null


def magic_buffer(cookie, buf):
    return _magic_buffer(cookie, buf, len(buf))


magic_descriptor = libmagic.magic_descriptor
magic_descriptor.restype = c_char_p
magic_descriptor.argtypes = [magic_t, c_int]
magic_descriptor.errcheck = errorcheck_null

_magic_descriptor = libmagic.magic_descriptor
_magic_descriptor.restype = c_char_p
_magic_descriptor.argtypes = [magic_t, c_int]
_magic_descriptor.errcheck = errorcheck_null


def magic_descriptor(cookie, fd):
    return _magic_descriptor(cookie, fd)


_magic_load = libmagic.magic_load
_magic_load.restype = c_int
_magic_load.argtypes = [magic_t, c_char_p]
_magic_load.errcheck = errorcheck_negative_one


def magic_load(cookie, filename):
    return _magic_load(cookie, coerce_filename(filename))


magic_setflags = libmagic.magic_setflags
magic_setflags.restype = c_int
magic_setflags.argtypes = [magic_t, c_int]

magic_check = libmagic.magic_check
magic_check.restype = c_int
magic_check.argtypes = [magic_t, c_char_p]

magic_compile = libmagic.magic_compile
magic_compile.restype = c_int
magic_compile.argtypes = [magic_t, c_char_p]

_has_param = False
if hasattr(libmagic, 'magic_setparam') and hasattr(libmagic, 'magic_getparam'):
    _has_param = True
    _magic_setparam = libmagic.magic_setparam
    _magic_setparam.restype = c_int
    _magic_setparam.argtypes = [magic_t, c_int, POINTER(c_size_t)]
    _magic_setparam.errcheck = errorcheck_negative_one

    _magic_getparam = libmagic.magic_getparam
    _magic_getparam.restype = c_int
    _magic_getparam.argtypes = [magic_t, c_int, POINTER(c_size_t)]
    _magic_getparam.errcheck = errorcheck_negative_one


def magic_setparam(cookie, param, val):
    if not _has_param:
        raise NotImplementedError("magic_setparam not implemented")
    v = c_size_t(val)
    return _magic_setparam(cookie, param, byref(v))


def magic_getparam(cookie, param):
    if not _has_param:
        raise NotImplementedError("magic_getparam not implemented")
    val = c_size_t()
    _magic_getparam(cookie, param, byref(val))
    return val.value


_has_version = False
if hasattr(libmagic, "magic_version"):
    _has_version = True
    magic_version = libmagic.magic_version
    magic_version.restype = c_int
    magic_version.argtypes = []


def version():
    if not _has_version:
        raise NotImplementedError("magic_version not implemented")
    return magic_version()


MAGIC_NONE = 0x000000  # No flags
MAGIC_DEBUG = 0x000001  # Turn on debugging
MAGIC_SYMLINK = 0x000002  # Follow symlinks
MAGIC_COMPRESS = 0x000004  # Check inside compressed files
MAGIC_DEVICES = 0x000008  # Look at the contents of devices
MAGIC_MIME_TYPE = 0x000010  # Return a mime string
MAGIC_MIME_ENCODING = 0x000400  # Return the MIME encoding
# TODO:  should be
# MAGIC_MIME = MAGIC_MIME_TYPE | MAGIC_MIME_ENCODING
MAGIC_MIME = 0x000010  # Return a mime string
MAGIC_EXTENSION = 0x1000000  # Return a /-separated list of extensions

MAGIC_CONTINUE = 0x000020  # Return all matches
MAGIC_CHECK = 0x000040  # Print warnings to stderr
MAGIC_PRESERVE_ATIME = 0x000080  # Restore access time on exit
MAGIC_RAW = 0x000100  # Don't translate unprintable chars
MAGIC_ERROR = 0x000200  # Handle ENOENT etc as real errors

MAGIC_NO_CHECK_COMPRESS = 0x001000  # Don't check for compressed files
MAGIC_NO_CHECK_TAR = 0x002000  # Don't check for tar files
MAGIC_NO_CHECK_SOFT = 0x004000  # Don't check magic entries
MAGIC_NO_CHECK_APPTYPE = 0x008000  # Don't check application type
MAGIC_NO_CHECK_ELF = 0x010000  # Don't check for elf details
MAGIC_NO_CHECK_ASCII = 0x020000  # Don't check for ascii files
MAGIC_NO_CHECK_TROFF = 0x040000  # Don't check ascii/troff
MAGIC_NO_CHECK_FORTRAN = 0x080000  # Don't check ascii/fortran
MAGIC_NO_CHECK_TOKENS = 0x100000  # Don't check ascii/tokens

MAGIC_PARAM_INDIR_MAX = 0  # Recursion limit for indirect magic
MAGIC_PARAM_NAME_MAX = 1  # Use count limit for name/use magic
MAGIC_PARAM_ELF_PHNUM_MAX = 2  # Max ELF notes processed
MAGIC_PARAM_ELF_SHNUM_MAX = 3  # Max ELF program sections processed
MAGIC_PARAM_ELF_NOTES_MAX = 4  # # Max ELF sections processed
MAGIC_PARAM_REGEX_MAX = 5  # Length limit for regex searches
MAGIC_PARAM_BYTES_MAX = 6  # Max number of bytes to read from file


# This package name conflicts with the one provided by upstream
# libmagic.  This is a common source of confusion for users.  To
# resolve, We ship a copy of that module, and expose it's functions
# wrapped in deprecation warnings.
def _add_compat(to_module):
    import warnings, re
    from magic import compat

    def deprecation_wrapper(fn):
        def _(*args, **kwargs):
            warnings.warn(
                "Using compatibility mode with libmagic's python binding. "
                "See https://github.com/ahupp/python-magic/blob/master/COMPAT.md for details.",
                PendingDeprecationWarning)

            return fn(*args, **kwargs)

        return _

    fn = ['detect_from_filename',
          'detect_from_content',
          'detect_from_fobj',
          'open']
    for fname in fn:
        to_module[fname] = deprecation_wrapper(compat.__dict__[fname])

    # copy constants over, ensuring there's no conflicts
    is_const_re = re.compile("^[A-Z_]+$")
    allowed_inconsistent = set(['MAGIC_MIME'])
    for name, value in compat.__dict__.items():
        if is_const_re.match(name):
            if name in to_module:
                if name in allowed_inconsistent:
                    continue
                if to_module[name] != value:
                    raise Exception("inconsistent value for " + name)
                else:
                    continue
            else:
                to_module[name] = value


_add_compat(globals())
