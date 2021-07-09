# helpers.py
from .core import *
from .util import _bslash, _flatten, _escapeRegexRangeChars


#
# global helpers
#
def delimitedList(expr, delim=",", combine=False):
    """Helper to define a delimited list of expressions - the delimiter
    defaults to ','. By default, the list elements and delimiters can
    have intervening whitespace, and comments, but this can be
    overridden by passing ``combine=True`` in the constructor. If
    ``combine`` is set to ``True``, the matching tokens are
    returned as a single token string, with the delimiters included;
    otherwise, the matching tokens are returned as a list of tokens,
    with the delimiters suppressed.

    Example::

        delimitedList(Word(alphas)).parseString("aa,bb,cc") # -> ['aa', 'bb', 'cc']
        delimitedList(Word(hexnums), delim=':', combine=True).parseString("AA:BB:CC:DD:EE") # -> ['AA:BB:CC:DD:EE']
    """
    dlName = str(expr) + " [" + str(delim) + " " + str(expr) + "]..."
    if combine:
        return Combine(expr + ZeroOrMore(delim + expr)).setName(dlName)
    else:
        return (expr + ZeroOrMore(Suppress(delim) + expr)).setName(dlName)


def countedArray(expr, intExpr=None):
    """Helper to define a counted list of expressions.

    This helper defines a pattern of the form::

        integer expr expr expr...

    where the leading integer tells how many expr expressions follow.
    The matched tokens returns the array of expr tokens as a list - the
    leading count token is suppressed.

    If ``intExpr`` is specified, it should be a pyparsing expression
    that produces an integer value.

    Example::

        countedArray(Word(alphas)).parseString('2 ab cd ef')  # -> ['ab', 'cd']

        # in this parser, the leading integer value is given in binary,
        # '10' indicating that 2 values are in the array
        binaryConstant = Word('01').setParseAction(lambda t: int(t[0], 2))
        countedArray(Word(alphas), intExpr=binaryConstant).parseString('10 ab cd ef')  # -> ['ab', 'cd']

        # if other fields must be parsed after the count but before the
        # list items, give the fields results names and they will
        # be preserved in the returned ParseResults:
        count_with_metadata = integer + Word(alphas)("type")
        typed_array = countedArray(Word(alphanums), intExpr=count_with_metadata)("items")
        result = typed_array.parseString("3 bool True True False")
        print(result.dump())

        # prints
        # ['True', 'True', 'False']
        # - items: ['True', 'True', 'False']
        # - type: 'bool'
    """
    arrayExpr = Forward()

    def countFieldParseAction(s, l, t):
        n = t[0]
        arrayExpr << (And([expr] * n) if n else empty)
        # clear list contents, but keep any named results
        del t[:]

    if intExpr is None:
        intExpr = Word(nums).setParseAction(lambda t: int(t[0]))
    else:
        intExpr = intExpr.copy()
    intExpr.setName("arrayLen")
    intExpr.addParseAction(countFieldParseAction, callDuringTry=True)
    return (intExpr + arrayExpr).setName("(len) " + str(expr) + "...")


def matchPreviousLiteral(expr):
    """Helper to define an expression that is indirectly defined from
    the tokens matched in a previous expression, that is, it looks for
    a 'repeat' of a previous expression.  For example::

        first = Word(nums)
        second = matchPreviousLiteral(first)
        matchExpr = first + ":" + second

    will match ``"1:1"``, but not ``"1:2"``.  Because this
    matches a previous literal, will also match the leading
    ``"1:1"`` in ``"1:10"``. If this is not desired, use
    :class:`matchPreviousExpr`. Do *not* use with packrat parsing
    enabled.
    """
    rep = Forward()

    def copyTokenToRepeater(s, l, t):
        if t:
            if len(t) == 1:
                rep << t[0]
            else:
                # flatten t tokens
                tflat = _flatten(t.asList())
                rep << And(Literal(tt) for tt in tflat)
        else:
            rep << Empty()

    expr.addParseAction(copyTokenToRepeater, callDuringTry=True)
    rep.setName("(prev) " + str(expr))
    return rep


def matchPreviousExpr(expr):
    """Helper to define an expression that is indirectly defined from
    the tokens matched in a previous expression, that is, it looks for
    a 'repeat' of a previous expression.  For example::

        first = Word(nums)
        second = matchPreviousExpr(first)
        matchExpr = first + ":" + second

    will match ``"1:1"``, but not ``"1:2"``.  Because this
    matches by expressions, will *not* match the leading ``"1:1"``
    in ``"1:10"``; the expressions are evaluated first, and then
    compared, so ``"1"`` is compared with ``"10"``. Do *not* use
    with packrat parsing enabled.
    """
    rep = Forward()
    e2 = expr.copy()
    rep <<= e2

    def copyTokenToRepeater(s, l, t):
        matchTokens = _flatten(t.asList())

        def mustMatchTheseTokens(s, l, t):
            theseTokens = _flatten(t.asList())
            if theseTokens != matchTokens:
                raise ParseException("", 0, "")

        rep.setParseAction(mustMatchTheseTokens, callDuringTry=True)

    expr.addParseAction(copyTokenToRepeater, callDuringTry=True)
    rep.setName("(prev) " + str(expr))
    return rep


def oneOf(strs, caseless=False, useRegex=True, asKeyword=False):
    """Helper to quickly define a set of alternative :class:`Literal` s,
    and makes sure to do longest-first testing when there is a conflict,
    regardless of the input order, but returns
    a :class:`MatchFirst` for best performance.

    Parameters:

     - ``strs`` - a string of space-delimited literals, or a collection of
       string literals
     - ``caseless`` - treat all literals as caseless - (default= ``False``)
     - ``useRegex`` - as an optimization, will
       generate a :class:`Regex` object; otherwise, will generate
       a :class:`MatchFirst` object (if ``caseless=True`` or ``asKeyword=True``, or if
       creating a :class:`Regex` raises an exception) - (default= ``True``)
     - ``asKeyword`` - enforce :class:`Keyword`-style matching on the
       generated expressions - (default= ``False``)

    Example::

        comp_oper = oneOf("< = > <= >= !=")
        var = Word(alphas)
        number = Word(nums)
        term = var | number
        comparison_expr = term + comp_oper + term
        print(comparison_expr.searchString("B = 12  AA=23 B<=AA AA>12"))

    prints::

        [['B', '=', '12'], ['AA', '=', '23'], ['B', '<=', 'AA'], ['AA', '>', '12']]
    """
    if isinstance(caseless, str_type):
        warnings.warn(
            "More than one string argument passed to oneOf, pass"
            " choices as a list or space-delimited string",
            stacklevel=2,
        )

    if caseless:
        isequal = lambda a, b: a.upper() == b.upper()
        masks = lambda a, b: b.upper().startswith(a.upper())
        parseElementClass = CaselessKeyword if asKeyword else CaselessLiteral
    else:
        isequal = lambda a, b: a == b
        masks = lambda a, b: b.startswith(a)
        parseElementClass = Keyword if asKeyword else Literal

    symbols = []
    if isinstance(strs, str_type):
        symbols = strs.split()
    elif isinstance(strs, Iterable):
        symbols = list(strs)
    else:
        raise TypeError("Invalid argument to oneOf, expected string or iterable")
    if not symbols:
        return NoMatch()

    if not asKeyword:
        # if not producing keywords, need to reorder to take care to avoid masking
        # longer choices with shorter ones
        i = 0
        while i < len(symbols) - 1:
            cur = symbols[i]
            for j, other in enumerate(symbols[i + 1 :]):
                if isequal(other, cur):
                    del symbols[i + j + 1]
                    break
                elif masks(cur, other):
                    del symbols[i + j + 1]
                    symbols.insert(i, other)
                    break
            else:
                i += 1

    if not (caseless or asKeyword) and useRegex:
        # ~ print(strs, "->", "|".join([_escapeRegexChars(sym) for sym in symbols]))
        try:
            if len(symbols) == len("".join(symbols)):
                return Regex(
                    "[%s]" % "".join(_escapeRegexRangeChars(sym) for sym in symbols)
                ).setName(" | ".join(symbols))
            else:
                return Regex("|".join(re.escape(sym) for sym in symbols)).setName(
                    " | ".join(symbols)
                )
        except sre_constants.error:
            warnings.warn(
                "Exception creating Regex for oneOf, building MatchFirst", stacklevel=2
            )

    # last resort, just use MatchFirst
    return MatchFirst(parseElementClass(sym) for sym in symbols).setName(
        " | ".join(symbols)
    )


def dictOf(key, value):
    """Helper to easily and clearly define a dictionary by specifying
    the respective patterns for the key and value.  Takes care of
    defining the :class:`Dict`, :class:`ZeroOrMore`, and
    :class:`Group` tokens in the proper order.  The key pattern
    can include delimiting markers or punctuation, as long as they are
    suppressed, thereby leaving the significant key text.  The value
    pattern can include named results, so that the :class:`Dict` results
    can include named token fields.

    Example::

        text = "shape: SQUARE posn: upper left color: light blue texture: burlap"
        attr_expr = (label + Suppress(':') + OneOrMore(data_word, stopOn=label).setParseAction(' '.join))
        print(OneOrMore(attr_expr).parseString(text).dump())

        attr_label = label
        attr_value = Suppress(':') + OneOrMore(data_word, stopOn=label).setParseAction(' '.join)

        # similar to Dict, but simpler call format
        result = dictOf(attr_label, attr_value).parseString(text)
        print(result.dump())
        print(result['shape'])
        print(result.shape)  # object attribute access works too
        print(result.asDict())

    prints::

        [['shape', 'SQUARE'], ['posn', 'upper left'], ['color', 'light blue'], ['texture', 'burlap']]
        - color: light blue
        - posn: upper left
        - shape: SQUARE
        - texture: burlap
        SQUARE
        SQUARE
        {'color': 'light blue', 'shape': 'SQUARE', 'posn': 'upper left', 'texture': 'burlap'}
    """
    return Dict(OneOrMore(Group(key + value)))


def originalTextFor(expr, asString=True):
    """Helper to return the original, untokenized text for a given
    expression.  Useful to restore the parsed fields of an HTML start
    tag into the raw tag text itself, or to revert separate tokens with
    intervening whitespace back to the original matching input text. By
    default, returns astring containing the original parsed text.

    If the optional ``asString`` argument is passed as
    ``False``, then the return value is
    a :class:`ParseResults` containing any results names that
    were originally matched, and a single token containing the original
    matched text from the input string.  So if the expression passed to
    :class:`originalTextFor` contains expressions with defined
    results names, you must set ``asString`` to ``False`` if you
    want to preserve those results name values.

    Example::

        src = "this is test <b> bold <i>text</i> </b> normal text "
        for tag in ("b", "i"):
            opener, closer = makeHTMLTags(tag)
            patt = originalTextFor(opener + SkipTo(closer) + closer)
            print(patt.searchString(src)[0])

    prints::

        ['<b> bold <i>text</i> </b>']
        ['<i>text</i>']
    """
    locMarker = Empty().setParseAction(lambda s, loc, t: loc)
    endlocMarker = locMarker.copy()
    endlocMarker.callPreparse = False
    matchExpr = locMarker("_original_start") + expr + endlocMarker("_original_end")
    if asString:
        extractText = lambda s, l, t: s[t._original_start : t._original_end]
    else:

        def extractText(s, l, t):
            t[:] = [s[t.pop("_original_start") : t.pop("_original_end")]]

    matchExpr.setParseAction(extractText)
    matchExpr.ignoreExprs = expr.ignoreExprs
    return matchExpr


def ungroup(expr):
    """Helper to undo pyparsing's default grouping of And expressions,
    even if all but one are non-empty.
    """
    return TokenConverter(expr).addParseAction(lambda t: t[0])


def locatedExpr(expr):
    """
    (DEPRECATED - future code should use the Located class)
    Helper to decorate a returned token with its starting and ending
    locations in the input string.

    This helper adds the following results names:

     - ``locn_start`` - location where matched expression begins
     - ``locn_end`` - location where matched expression ends
     - ``value`` - the actual parsed results

    Be careful if the input text contains ``<TAB>`` characters, you
    may want to call :class:`ParserElement.parseWithTabs`

    Example::

        wd = Word(alphas)
        for match in locatedExpr(wd).searchString("ljsdf123lksdjjf123lkkjj1222"):
            print(match)

    prints::

        [[0, 'ljsdf', 5]]
        [[8, 'lksdjjf', 15]]
        [[18, 'lkkjj', 23]]
    """
    locator = Empty().setParseAction(lambda s, l, t: l)
    return Group(
        locator("locn_start")
        + expr("value")
        + locator.copy().leaveWhitespace()("locn_end")
    )


def nestedExpr(opener="(", closer=")", content=None, ignoreExpr=quotedString.copy()):
    """Helper method for defining nested lists enclosed in opening and
    closing delimiters (``"("`` and ``")"`` are the default).

    Parameters:
     - ``opener`` - opening character for a nested list
       (default= ``"("``); can also be a pyparsing expression
     - ``closer`` - closing character for a nested list
       (default= ``")"``); can also be a pyparsing expression
     - ``content`` - expression for items within the nested lists
       (default= ``None``)
     - ``ignoreExpr`` - expression for ignoring opening and closing
       delimiters (default= :class:`quotedString`)

    If an expression is not provided for the content argument, the
    nested expression will capture all whitespace-delimited content
    between delimiters as a list of separate values.

    Use the ``ignoreExpr`` argument to define expressions that may
    contain opening or closing characters that should not be treated as
    opening or closing characters for nesting, such as quotedString or
    a comment expression.  Specify multiple expressions using an
    :class:`Or` or :class:`MatchFirst`. The default is
    :class:`quotedString`, but if no expressions are to be ignored, then
    pass ``None`` for this argument.

    Example::

        data_type = oneOf("void int short long char float double")
        decl_data_type = Combine(data_type + Optional(Word('*')))
        ident = Word(alphas+'_', alphanums+'_')
        number = pyparsing_common.number
        arg = Group(decl_data_type + ident)
        LPAR, RPAR = map(Suppress, "()")

        code_body = nestedExpr('{', '}', ignoreExpr=(quotedString | cStyleComment))

        c_function = (decl_data_type("type")
                      + ident("name")
                      + LPAR + Optional(delimitedList(arg), [])("args") + RPAR
                      + code_body("body"))
        c_function.ignore(cStyleComment)

        source_code = '''
            int is_odd(int x) {
                return (x%2);
            }

            int dec_to_hex(char hchar) {
                if (hchar >= '0' && hchar <= '9') {
                    return (ord(hchar)-ord('0'));
                } else {
                    return (10+ord(hchar)-ord('A'));
                }
            }
        '''
        for func in c_function.searchString(source_code):
            print("%(name)s (%(type)s) args: %(args)s" % func)


    prints::

        is_odd (int) args: [['int', 'x']]
        dec_to_hex (int) args: [['char', 'hchar']]
    """
    if opener == closer:
        raise ValueError("opening and closing strings cannot be the same")
    if content is None:
        if isinstance(opener, str_type) and isinstance(closer, str_type):
            if len(opener) == 1 and len(closer) == 1:
                if ignoreExpr is not None:
                    content = Combine(
                        OneOrMore(
                            ~ignoreExpr
                            + CharsNotIn(
                                opener + closer + ParserElement.DEFAULT_WHITE_CHARS,
                                exact=1,
                            )
                        )
                    ).setParseAction(lambda t: t[0].strip())
                else:
                    content = empty.copy() + CharsNotIn(
                        opener + closer + ParserElement.DEFAULT_WHITE_CHARS
                    ).setParseAction(lambda t: t[0].strip())
            else:
                if ignoreExpr is not None:
                    content = Combine(
                        OneOrMore(
                            ~ignoreExpr
                            + ~Literal(opener)
                            + ~Literal(closer)
                            + CharsNotIn(ParserElement.DEFAULT_WHITE_CHARS, exact=1)
                        )
                    ).setParseAction(lambda t: t[0].strip())
                else:
                    content = Combine(
                        OneOrMore(
                            ~Literal(opener)
                            + ~Literal(closer)
                            + CharsNotIn(ParserElement.DEFAULT_WHITE_CHARS, exact=1)
                        )
                    ).setParseAction(lambda t: t[0].strip())
        else:
            raise ValueError(
                "opening and closing arguments must be strings if no content expression is given"
            )
    ret = Forward()
    if ignoreExpr is not None:
        ret <<= Group(
            Suppress(opener) + ZeroOrMore(ignoreExpr | ret | content) + Suppress(closer)
        )
    else:
        ret <<= Group(Suppress(opener) + ZeroOrMore(ret | content) + Suppress(closer))
    ret.setName("nested %s%s expression" % (opener, closer))
    return ret


def _makeTags(tagStr, xml, suppress_LT=Suppress("<"), suppress_GT=Suppress(">")):
    """Internal helper to construct opening and closing tag expressions, given a tag name"""
    if isinstance(tagStr, str_type):
        resname = tagStr
        tagStr = Keyword(tagStr, caseless=not xml)
    else:
        resname = tagStr.name

    tagAttrName = Word(alphas, alphanums + "_-:")
    if xml:
        tagAttrValue = dblQuotedString.copy().setParseAction(removeQuotes)
        openTag = (
            suppress_LT
            + tagStr("tag")
            + Dict(ZeroOrMore(Group(tagAttrName + Suppress("=") + tagAttrValue)))
            + Optional("/", default=[False])("empty").setParseAction(
                lambda s, l, t: t[0] == "/"
            )
            + suppress_GT
        )
    else:
        tagAttrValue = quotedString.copy().setParseAction(removeQuotes) | Word(
            printables, excludeChars=">"
        )
        openTag = (
            suppress_LT
            + tagStr("tag")
            + Dict(
                ZeroOrMore(
                    Group(
                        tagAttrName.setParseAction(lambda t: t[0].lower())
                        + Optional(Suppress("=") + tagAttrValue)
                    )
                )
            )
            + Optional("/", default=[False])("empty").setParseAction(
                lambda s, l, t: t[0] == "/"
            )
            + suppress_GT
        )
    closeTag = Combine(Literal("</") + tagStr + ">", adjacent=False)

    openTag.setName("<%s>" % resname)
    # add start<tagname> results name in parse action now that ungrouped names are not reported at two levels
    openTag.addParseAction(
        lambda t: t.__setitem__(
            "start" + "".join(resname.replace(":", " ").title().split()), t.copy()
        )
    )
    closeTag = closeTag(
        "end" + "".join(resname.replace(":", " ").title().split())
    ).setName("</%s>" % resname)
    openTag.tag = resname
    closeTag.tag = resname
    openTag.tag_body = SkipTo(closeTag())
    return openTag, closeTag


def makeHTMLTags(tagStr):
    """Helper to construct opening and closing tag expressions for HTML,
    given a tag name. Matches tags in either upper or lower case,
    attributes with namespaces and with quoted or unquoted values.

    Example::

        text = '<td>More info at the <a href="https://github.com/pyparsing/pyparsing/wiki">pyparsing</a> wiki page</td>'
        # makeHTMLTags returns pyparsing expressions for the opening and
        # closing tags as a 2-tuple
        a, a_end = makeHTMLTags("A")
        link_expr = a + SkipTo(a_end)("link_text") + a_end

        for link in link_expr.searchString(text):
            # attributes in the <A> tag (like "href" shown here) are
            # also accessible as named results
            print(link.link_text, '->', link.href)

    prints::

        pyparsing -> https://github.com/pyparsing/pyparsing/wiki
    """
    return _makeTags(tagStr, False)


def makeXMLTags(tagStr):
    """Helper to construct opening and closing tag expressions for XML,
    given a tag name. Matches tags only in the given upper/lower case.

    Example: similar to :class:`makeHTMLTags`
    """
    return _makeTags(tagStr, True)


anyOpenTag, anyCloseTag = makeHTMLTags(
    Word(alphas, alphanums + "_:").setName("any tag")
)


_htmlEntityMap = dict(zip("gt lt amp nbsp quot apos".split(), "><& \"'"))
commonHTMLEntity = Regex(
    "&(?P<entity>" + "|".join(_htmlEntityMap.keys()) + ");"
).setName("common HTML entity")


def replaceHTMLEntity(t):
    """Helper parser action to replace common HTML entities with their special characters"""
    return _htmlEntityMap.get(t.entity)


class opAssoc(Enum):
    LEFT = 1
    RIGHT = 2


def infixNotation(baseExpr, opList, lpar=Suppress("("), rpar=Suppress(")")):
    """Helper method for constructing grammars of expressions made up of
    operators working in a precedence hierarchy.  Operators may be unary
    or binary, left- or right-associative.  Parse actions can also be
    attached to operator expressions. The generated parser will also
    recognize the use of parentheses to override operator precedences
    (see example below).

    Note: if you define a deep operator list, you may see performance
    issues when using infixNotation. See
    :class:`ParserElement.enablePackrat` for a mechanism to potentially
    improve your parser performance.

    Parameters:
     - ``baseExpr`` - expression representing the most basic element for the
       nested
     - ``opList`` - list of tuples, one for each operator precedence level
       in the expression grammar; each tuple is of the form ``(opExpr,
       numTerms, rightLeftAssoc, parseAction)``, where:

       - ``opExpr`` is the pyparsing expression for the operator; may also
         be a string, which will be converted to a Literal; if ``numTerms``
         is 3, ``opExpr`` is a tuple of two expressions, for the two
         operators separating the 3 terms
       - ``numTerms`` is the number of terms for this operator (must be 1,
         2, or 3)
       - ``rightLeftAssoc`` is the indicator whether the operator is right
         or left associative, using the pyparsing-defined constants
         ``opAssoc.RIGHT`` and ``opAssoc.LEFT``.
       - ``parseAction`` is the parse action to be associated with
         expressions matching this operator expression (the parse action
         tuple member may be omitted); if the parse action is passed
         a tuple or list of functions, this is equivalent to calling
         ``setParseAction(*fn)``
         (:class:`ParserElement.setParseAction`)
     - ``lpar`` - expression for matching left-parentheses
       (default= ``Suppress('(')``)
     - ``rpar`` - expression for matching right-parentheses
       (default= ``Suppress(')')``)

    Example::

        # simple example of four-function arithmetic with ints and
        # variable names
        integer = pyparsing_common.signed_integer
        varname = pyparsing_common.identifier

        arith_expr = infixNotation(integer | varname,
            [
            ('-', 1, opAssoc.RIGHT),
            (oneOf('* /'), 2, opAssoc.LEFT),
            (oneOf('+ -'), 2, opAssoc.LEFT),
            ])

        arith_expr.runTests('''
            5+3*6
            (5+3)*6
            -2--11
            ''', fullDump=False)

    prints::

        5+3*6
        [[5, '+', [3, '*', 6]]]

        (5+3)*6
        [[[5, '+', 3], '*', 6]]

        -2--11
        [[['-', 2], '-', ['-', 11]]]
    """
    # captive version of FollowedBy that does not do parse actions or capture results names
    class _FB(FollowedBy):
        def parseImpl(self, instring, loc, doActions=True):
            self.expr.tryParse(instring, loc)
            return loc, []

    ret = Forward()
    lastExpr = baseExpr | (lpar + ret + rpar)
    for i, operDef in enumerate(opList):
        opExpr, arity, rightLeftAssoc, pa = (operDef + (None,))[:4]
        if isinstance(opExpr, str_type):
            opExpr = ParserElement._literalStringClass(opExpr)
        if arity == 3:
            if not isinstance(opExpr, (tuple, list)) or len(opExpr) != 2:
                raise ValueError(
                    "if numterms=3, opExpr must be a tuple or list of two expressions"
                )
            opExpr1, opExpr2 = opExpr

        if not 1 <= arity <= 3:
            raise ValueError("operator must be unary (1), binary (2), or ternary (3)")

        if rightLeftAssoc not in (opAssoc.LEFT, opAssoc.RIGHT):
            raise ValueError("operator must indicate right or left associativity")

        termName = "%s term" % opExpr if arity < 3 else "%s%s term" % opExpr
        thisExpr = Forward().setName(termName)
        if rightLeftAssoc is opAssoc.LEFT:
            if arity == 1:
                matchExpr = _FB(lastExpr + opExpr) + Group(
                    lastExpr + opExpr + opExpr[...]
                )
            elif arity == 2:
                if opExpr is not None:
                    matchExpr = _FB(lastExpr + opExpr + lastExpr) + Group(
                        lastExpr + opExpr + lastExpr + (opExpr + lastExpr)[...]
                    )
                else:
                    matchExpr = _FB(lastExpr + lastExpr) + Group(
                        lastExpr + lastExpr + lastExpr[...]
                    )
            elif arity == 3:
                matchExpr = _FB(
                    lastExpr + opExpr1 + lastExpr + opExpr2 + lastExpr
                ) + Group(lastExpr + OneOrMore(opExpr1 + lastExpr + opExpr2 + lastExpr))
        elif rightLeftAssoc is opAssoc.RIGHT:
            if arity == 1:
                # try to avoid LR with this extra test
                if not isinstance(opExpr, Optional):
                    opExpr = Optional(opExpr)
                matchExpr = _FB(opExpr.expr + thisExpr) + Group(opExpr + thisExpr)
            elif arity == 2:
                if opExpr is not None:
                    matchExpr = _FB(lastExpr + opExpr + thisExpr) + Group(
                        lastExpr + opExpr + thisExpr + (opExpr + thisExpr)[...]
                    )
                else:
                    matchExpr = _FB(lastExpr + thisExpr) + Group(
                        lastExpr + thisExpr + thisExpr[...]
                    )
            elif arity == 3:
                matchExpr = _FB(
                    lastExpr + opExpr1 + thisExpr + opExpr2 + thisExpr
                ) + Group(lastExpr + opExpr1 + thisExpr + opExpr2 + thisExpr)
        if pa:
            if isinstance(pa, (tuple, list)):
                matchExpr.setParseAction(*pa)
            else:
                matchExpr.setParseAction(pa)
        thisExpr <<= matchExpr.setName(termName) | lastExpr
        lastExpr = thisExpr
    ret <<= lastExpr
    return ret


def indentedBlock(blockStatementExpr, indentStack, indent=True, backup_stacks=[]):
    """Helper method for defining space-delimited indentation blocks,
    such as those used to define block statements in Python source code.

    Parameters:

     - ``blockStatementExpr`` - expression defining syntax of statement that
       is repeated within the indented block
     - ``indentStack`` - list created by caller to manage indentation stack
       (multiple ``statementWithIndentedBlock`` expressions within a single
       grammar should share a common ``indentStack``)
     - ``indent`` - boolean indicating whether block must be indented beyond
       the current level; set to ``False`` for block of left-most
       statements (default= ``True``)

    A valid block must contain at least one ``blockStatement``.

    (Note that indentedBlock uses internal parse actions which make it
    incompatible with packrat parsing.)

    Example::

        data = '''
        def A(z):
          A1
          B = 100
          G = A2
          A2
          A3
        B
        def BB(a,b,c):
          BB1
          def BBA():
            bba1
            bba2
            bba3
        C
        D
        def spam(x,y):
             def eggs(z):
                 pass
        '''


        indentStack = [1]
        stmt = Forward()

        identifier = Word(alphas, alphanums)
        funcDecl = ("def" + identifier + Group("(" + Optional(delimitedList(identifier)) + ")") + ":")
        func_body = indentedBlock(stmt, indentStack)
        funcDef = Group(funcDecl + func_body)

        rvalue = Forward()
        funcCall = Group(identifier + "(" + Optional(delimitedList(rvalue)) + ")")
        rvalue << (funcCall | identifier | Word(nums))
        assignment = Group(identifier + "=" + rvalue)
        stmt << (funcDef | assignment | identifier)

        module_body = OneOrMore(stmt)

        parseTree = module_body.parseString(data)
        parseTree.pprint()

    prints::

        [['def',
          'A',
          ['(', 'z', ')'],
          ':',
          [['A1'], [['B', '=', '100']], [['G', '=', 'A2']], ['A2'], ['A3']]],
         'B',
         ['def',
          'BB',
          ['(', 'a', 'b', 'c', ')'],
          ':',
          [['BB1'], [['def', 'BBA', ['(', ')'], ':', [['bba1'], ['bba2'], ['bba3']]]]]],
         'C',
         'D',
         ['def',
          'spam',
          ['(', 'x', 'y', ')'],
          ':',
          [[['def', 'eggs', ['(', 'z', ')'], ':', [['pass']]]]]]]
    """
    backup_stacks.append(indentStack[:])

    def reset_stack():
        indentStack[:] = backup_stacks[-1]

    def checkPeerIndent(s, l, t):
        if l >= len(s):
            return
        curCol = col(l, s)
        if curCol != indentStack[-1]:
            if curCol > indentStack[-1]:
                raise ParseException(s, l, "illegal nesting")
            raise ParseException(s, l, "not a peer entry")

    def checkSubIndent(s, l, t):
        curCol = col(l, s)
        if curCol > indentStack[-1]:
            indentStack.append(curCol)
        else:
            raise ParseException(s, l, "not a subentry")

    def checkUnindent(s, l, t):
        if l >= len(s):
            return
        curCol = col(l, s)
        if not (indentStack and curCol in indentStack):
            raise ParseException(s, l, "not an unindent")
        if curCol < indentStack[-1]:
            indentStack.pop()

    NL = OneOrMore(LineEnd().setWhitespaceChars("\t ").suppress())
    INDENT = (Empty() + Empty().setParseAction(checkSubIndent)).setName("INDENT")
    PEER = Empty().setParseAction(checkPeerIndent).setName("")
    UNDENT = Empty().setParseAction(checkUnindent).setName("UNINDENT")
    if indent:
        smExpr = Group(
            Optional(NL)
            + INDENT
            + OneOrMore(PEER + Group(blockStatementExpr) + Optional(NL))
            + UNDENT
        )
    else:
        smExpr = Group(
            Optional(NL)
            + OneOrMore(PEER + Group(blockStatementExpr) + Optional(NL))
            + Optional(UNDENT)
        )

    # add a parse action to remove backup_stack from list of backups
    smExpr.addParseAction(
        lambda: backup_stacks.pop(-1) and None if backup_stacks else None
    )
    smExpr.setFailAction(lambda a, b, c, d: reset_stack())
    blockStatementExpr.ignore(_bslash + LineEnd())
    return smExpr.setName("indented block")


class IndentedBlock(ParseElementEnhance):
    """
    Expression to match one or more expressions at a given indentation level.
    Useful for parsing text where structure is implied by indentation (like Python source code).
    """

    def __init__(self, expr, recursive=True):
        super().__init__(expr, savelist=True)
        self._recursive = recursive

    def parseImpl(self, instring, loc, doActions=True):
        # see if self.expr matches at the current location - if not it will raise an exception
        # and no further work is necessary
        self.expr.parseImpl(instring, loc, doActions)

        indent_col = col(loc, instring)
        peer_parse_action = matchOnlyAtCol(indent_col)
        peer_expr = FollowedBy(self.expr).addParseAction(peer_parse_action)
        inner_expr = Empty() + peer_expr.suppress() + self.expr

        if self._recursive:
            indent_parse_action = conditionAsParseAction(
                lambda s, l, t, relative_to_col=indent_col: col(l, s) > relative_to_col
            )
            indent_expr = FollowedBy(self.expr).addParseAction(indent_parse_action)
            inner_expr += Optional(indent_expr + self)

        return OneOrMore(inner_expr).parseImpl(instring, loc, doActions)


# it's easy to get these comment structures wrong - they're very common, so may as well make them available
cStyleComment = Combine(Regex(r"/\*(?:[^*]|\*(?!/))*") + "*/").setName(
    "C style comment"
)
"Comment of the form ``/* ... */``"

htmlComment = Regex(r"<!--[\s\S]*?-->").setName("HTML comment")
"Comment of the form ``<!-- ... -->``"

restOfLine = Regex(r".*").leaveWhitespace().setName("rest of line")
dblSlashComment = Regex(r"//(?:\\\n|[^\n])*").setName("// comment")
"Comment of the form ``// ... (to end of line)``"

cppStyleComment = Combine(
    Regex(r"/\*(?:[^*]|\*(?!/))*") + "*/" | dblSlashComment
).setName("C++ style comment")
"Comment of either form :class:`cStyleComment` or :class:`dblSlashComment`"

javaStyleComment = cppStyleComment
"Same as :class:`cppStyleComment`"

pythonStyleComment = Regex(r"#.*").setName("Python style comment")
"Comment of the form ``# ... (to end of line)``"


# build list of built-in expressions, for future reference if a global default value
# gets updated
_builtin_exprs = [v for v in vars().values() if isinstance(v, ParserElement)]
