# actions.py

from .exceptions import ParseException
from .util import col


class OnlyOnce:
    """Wrapper for parse actions, to ensure they are only called once.
    """

    def __init__(self, methodCall):
        from .core import _trim_arity
        self.callable = _trim_arity(methodCall)
        self.called = False

    def __call__(self, s, l, t):
        if not self.called:
            results = self.callable(s, l, t)
            self.called = True
            return results
        raise ParseException(s, l, "OnlyOnce obj called multiple times w/out reset")

    def reset(self):
        """Allow the associated parse action to be called once more.
        """

        self.called = False


def matchOnlyAtCol(n):
    """Helper method for defining parse actions that require matching at
    a specific column in the input text.
    """

    def verifyCol(strg, locn, toks):
        if col(locn, strg) != n:
            raise ParseException(strg, locn, "matched token not at column {}".format(n))

    return verifyCol


def replaceWith(replStr):
    """Helper method for common parse actions that simply return
    a literal value.  Especially useful when used with
    :class:`transformString<ParserElement.transformString>` ().

    Example::

        num = Word(nums).setParseAction(lambda toks: int(toks[0]))
        na = oneOf("N/A NA").setParseAction(replaceWith(math.nan))
        term = na | num

        OneOrMore(term).parseString("324 234 N/A 234") # -> [324, 234, nan, 234]
    """
    return lambda s, l, t: [replStr]


def removeQuotes(s, l, t):
    """Helper parse action for removing quotation marks from parsed
    quoted strings.

    Example::

        # by default, quotation marks are included in parsed results
        quotedString.parseString("'Now is the Winter of our Discontent'") # -> ["'Now is the Winter of our Discontent'"]

        # use removeQuotes to strip quotation marks from parsed results
        quotedString.setParseAction(removeQuotes)
        quotedString.parseString("'Now is the Winter of our Discontent'") # -> ["Now is the Winter of our Discontent"]
    """
    return t[0][1:-1]


def withAttribute(*args, **attrDict):
    """Helper to create a validating parse action to be used with start
    tags created with :class:`makeXMLTags` or
    :class:`makeHTMLTags`. Use ``withAttribute`` to qualify
    a starting tag with a required attribute value, to avoid false
    matches on common tags such as ``<TD>`` or ``<DIV>``.

    Call ``withAttribute`` with a series of attribute names and
    values. Specify the list of filter attributes names and values as:

     - keyword arguments, as in ``(align="right")``, or
     - as an explicit dict with ``**`` operator, when an attribute
       name is also a Python reserved word, as in ``**{"class":"Customer", "align":"right"}``
     - a list of name-value tuples, as in ``(("ns1:class", "Customer"), ("ns2:align", "right"))``

    For attribute names with a namespace prefix, you must use the second
    form.  Attribute names are matched insensitive to upper/lower case.

    If just testing for ``class`` (with or without a namespace), use
    :class:`withClass`.

    To verify that the attribute exists, but without specifying a value,
    pass ``withAttribute.ANY_VALUE`` as the value.

    Example::

        html = '''
            <div>
            Some text
            <div type="grid">1 4 0 1 0</div>
            <div type="graph">1,3 2,3 1,1</div>
            <div>this has no type</div>
            </div>

        '''
        div,div_end = makeHTMLTags("div")

        # only match div tag having a type attribute with value "grid"
        div_grid = div().setParseAction(withAttribute(type="grid"))
        grid_expr = div_grid + SkipTo(div | div_end)("body")
        for grid_header in grid_expr.searchString(html):
            print(grid_header.body)

        # construct a match with any div tag having a type attribute, regardless of the value
        div_any_type = div().setParseAction(withAttribute(type=withAttribute.ANY_VALUE))
        div_expr = div_any_type + SkipTo(div | div_end)("body")
        for div_header in div_expr.searchString(html):
            print(div_header.body)

    prints::

        1 4 0 1 0

        1 4 0 1 0
        1,3 2,3 1,1
    """
    if args:
        attrs = args[:]
    else:
        attrs = attrDict.items()
    attrs = [(k, v) for k, v in attrs]

    def pa(s, l, tokens):
        for attrName, attrValue in attrs:
            if attrName not in tokens:
                raise ParseException(s, l, "no matching attribute " + attrName)
            if attrValue != withAttribute.ANY_VALUE and tokens[attrName] != attrValue:
                raise ParseException(
                    s,
                    l,
                    "attribute {!r} has value {!r}, must be {!r}".format(
                        attrName, tokens[attrName], attrValue
                    ),
                )

    return pa


withAttribute.ANY_VALUE = object()


def withClass(classname, namespace=""):
    """Simplified version of :class:`withAttribute` when
    matching on a div class - made difficult because ``class`` is
    a reserved word in Python.

    Example::

        html = '''
            <div>
            Some text
            <div class="grid">1 4 0 1 0</div>
            <div class="graph">1,3 2,3 1,1</div>
            <div>this &lt;div&gt; has no class</div>
            </div>

        '''
        div,div_end = makeHTMLTags("div")
        div_grid = div().setParseAction(withClass("grid"))

        grid_expr = div_grid + SkipTo(div | div_end)("body")
        for grid_header in grid_expr.searchString(html):
            print(grid_header.body)

        div_any_type = div().setParseAction(withClass(withAttribute.ANY_VALUE))
        div_expr = div_any_type + SkipTo(div | div_end)("body")
        for div_header in div_expr.searchString(html):
            print(div_header.body)

    prints::

        1 4 0 1 0

        1 4 0 1 0
        1,3 2,3 1,1
    """
    classattr = "{}:class".format(namespace) if namespace else "class"
    return withAttribute(**{classattr: classname})
