# exceptions.py

import sys
from .util import col, line, lineno


class ParseBaseException(Exception):
    """base exception class for all parsing runtime exceptions"""

    # Performance tuning: we construct a *lot* of these, so keep this
    # constructor as small and fast as possible
    def __init__(self, pstr, loc=0, msg=None, elem=None):
        self.loc = loc
        if msg is None:
            self.msg = pstr
            self.pstr = ""
        else:
            self.msg = msg
            self.pstr = pstr
        self.parserElement = elem
        self.args = (pstr, loc, msg)

    @staticmethod
    def explain_exception(exc, depth=16):
        """
        Method to take an exception and translate the Python internal traceback into a list
        of the pyparsing expressions that caused the exception to be raised.

        Parameters:

         - exc - exception raised during parsing (need not be a ParseException, in support
           of Python exceptions that might be raised in a parse action)
         - depth (default=16) - number of levels back in the stack trace to list expression
           and function names; if None, the full stack trace names will be listed; if 0, only
           the failing input line, marker, and exception string will be shown

        Returns a multi-line string listing the ParserElements and/or function names in the
        exception's stack trace.
        """
        import inspect
        from .core import ParserElement

        if depth is None:
            depth = sys.getrecursionlimit()
        ret = []
        if isinstance(exc, ParseBaseException):
            ret.append(exc.line)
            ret.append(" " * (exc.col - 1) + "^")
        ret.append("{}: {}".format(type(exc).__name__, exc))

        if depth > 0:
            callers = inspect.getinnerframes(exc.__traceback__, context=depth)
            seen = set()
            for i, ff in enumerate(callers[-depth:]):
                frm = ff[0]

                f_self = frm.f_locals.get("self", None)
                if isinstance(f_self, ParserElement):
                    if frm.f_code.co_name not in ("parseImpl", "_parseNoCache"):
                        continue
                    if id(f_self) in seen:
                        continue
                    seen.add(id(f_self))

                    self_type = type(f_self)
                    ret.append(
                        "{}.{} - {}".format(
                            self_type.__module__, self_type.__name__, f_self
                        )
                    )

                elif f_self is not None:
                    self_type = type(f_self)
                    ret.append("{}.{}".format(self_type.__module__, self_type.__name__))

                else:
                    code = frm.f_code
                    if code.co_name in ("wrapper", "<module>"):
                        continue

                    ret.append("{}".format(code.co_name))

                depth -= 1
                if not depth:
                    break

        return "\n".join(ret)

    @classmethod
    def _from_exception(cls, pe):
        """
        internal factory method to simplify creating one type of ParseException
        from another - avoids having __init__ signature conflicts among subclasses
        """
        return cls(pe.pstr, pe.loc, pe.msg, pe.parserElement)

    def __getattr__(self, aname):
        """supported attributes by name are:
            - lineno - returns the line number of the exception text
            - col - returns the column number of the exception text
            - line - returns the line containing the exception text
        """
        if aname == "lineno":
            return lineno(self.loc, self.pstr)
        elif aname in ("col", "column"):
            return col(self.loc, self.pstr)
        elif aname == "line":
            return line(self.loc, self.pstr)
        else:
            raise AttributeError(aname)

    def __str__(self):
        if self.pstr:
            if self.loc >= len(self.pstr):
                foundstr = ", found end of text"
            else:
                foundstr = (", found %r" % self.pstr[self.loc : self.loc + 1]).replace(
                    r"\\", "\\"
                )
        else:
            foundstr = ""
        return "{}{}  (at char {}), (line:{}, col:{})".format(
            self.msg, foundstr, self.loc, self.lineno, self.column
        )

    def __repr__(self):
        return str(self)

    def markInputline(self, markerString=">!<"):
        """Extracts the exception line from the input string, and marks
           the location of the exception with a special symbol.
        """
        line_str = self.line
        line_column = self.column - 1
        if markerString:
            line_str = "".join(
                (line_str[:line_column], markerString, line_str[line_column:])
            )
        return line_str.strip()

    def __dir__(self):
        return "lineno col line".split() + dir(type(self))

    def explain(self, depth=16):
        """
        Method to translate the Python internal traceback into a list
        of the pyparsing expressions that caused the exception to be raised.

        Parameters:

         - depth (default=16) - number of levels back in the stack trace to list expression
           and function names; if None, the full stack trace names will be listed; if 0, only
           the failing input line, marker, and exception string will be shown

        Returns a multi-line string listing the ParserElements and/or function names in the
        exception's stack trace.

        Example::

            expr = pp.Word(pp.nums) * 3
            try:
                expr.parseString("123 456 A789")
            except pp.ParseException as pe:
                print(pe.explain(depth=0))

        prints::

            123 456 A789
                    ^
            ParseException: Expected W:(0-9), found 'A'  (at char 8), (line:1, col:9)

        Note: the diagnostic output will include string representations of the expressions
        that failed to parse. These representations will be more helpful if you use `setName` to
        give identifiable names to your expressions. Otherwise they will use the default string
        forms, which may be cryptic to read.

        Note: pyparsing's default truncation of exception tracebacks may also truncate the
        stack of expressions that are displayed in the ``explain`` output. To get the full listing
        of parser expressions, you may have to set ``ParserElement.verbose_stacktrace = True``
        """
        return self.explain_exception(self, depth)


class ParseException(ParseBaseException):
    """
    Exception thrown when parse expressions don't match class;
    supported attributes by name are:
     - lineno - returns the line number of the exception text
     - col - returns the column number of the exception text
     - line - returns the line containing the exception text

    Example::

        try:
            Word(nums).setName("integer").parseString("ABC")
        except ParseException as pe:
            print(pe)
            print("column: {}".format(pe.col))

    prints::

       Expected integer (at char 0), (line:1, col:1)
        column: 1

    """


class ParseFatalException(ParseBaseException):
    """user-throwable exception thrown when inconsistent parse content
       is found; stops all parsing immediately"""


class ParseSyntaxException(ParseFatalException):
    """just like :class:`ParseFatalException`, but thrown internally
    when an :class:`ErrorStop<And._ErrorStop>` ('-' operator) indicates
    that parsing is to stop immediately because an unbacktrackable
    syntax error has been found.
    """


# ~ class ReparseException(ParseBaseException):
# ~ """Experimental class - parse actions can raise this exception to cause
# ~ pyparsing to reparse the input string:
# ~ - with a modified input string, and/or
# ~ - with a modified start location
# ~ Set the values of the ReparseException in the constructor, and raise the
# ~ exception in a parse action to cause pyparsing to use the new string/location.
# ~ Setting the values as None causes no change to be made.
# ~ """
# ~ def __init_( self, newstring, restartLoc ):
# ~ self.newParseText = newstring
# ~ self.reparseLoc = restartLoc


class RecursiveGrammarException(Exception):
    """exception thrown by :class:`ParserElement.validate` if the
    grammar could be improperly recursive
    """

    def __init__(self, parseElementList):
        self.parseElementTrace = parseElementList

    def __str__(self):
        return "RecursiveGrammarException: {}".format(self.parseElementTrace)
