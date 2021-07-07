# common.py
from .core import *
from .helpers import delimitedList, anyOpenTag, anyCloseTag
from datetime import datetime

# some other useful expressions - using lower-case class name since we are really using this as a namespace
class pyparsing_common:
    """Here are some common low-level expressions that may be useful in
    jump-starting parser development:

     - numeric forms (:class:`integers<integer>`, :class:`reals<real>`,
       :class:`scientific notation<sci_real>`)
     - common :class:`programming identifiers<identifier>`
     - network addresses (:class:`MAC<mac_address>`,
       :class:`IPv4<ipv4_address>`, :class:`IPv6<ipv6_address>`)
     - ISO8601 :class:`dates<iso8601_date>` and
       :class:`datetime<iso8601_datetime>`
     - :class:`UUID<uuid>`
     - :class:`comma-separated list<comma_separated_list>`

    Parse actions:

     - :class:`convertToInteger`
     - :class:`convertToFloat`
     - :class:`convertToDate`
     - :class:`convertToDatetime`
     - :class:`stripHTMLTags`
     - :class:`upcaseTokens`
     - :class:`downcaseTokens`

    Example::

        pyparsing_common.number.runTests('''
            # any int or real number, returned as the appropriate type
            100
            -100
            +100
            3.14159
            6.02e23
            1e-12
            ''')

        pyparsing_common.fnumber.runTests('''
            # any int or real number, returned as float
            100
            -100
            +100
            3.14159
            6.02e23
            1e-12
            ''')

        pyparsing_common.hex_integer.runTests('''
            # hex numbers
            100
            FF
            ''')

        pyparsing_common.fraction.runTests('''
            # fractions
            1/2
            -3/4
            ''')

        pyparsing_common.mixed_integer.runTests('''
            # mixed fractions
            1
            1/2
            -3/4
            1-3/4
            ''')

        import uuid
        pyparsing_common.uuid.setParseAction(tokenMap(uuid.UUID))
        pyparsing_common.uuid.runTests('''
            # uuid
            12345678-1234-5678-1234-567812345678
            ''')

    prints::

        # any int or real number, returned as the appropriate type
        100
        [100]

        -100
        [-100]

        +100
        [100]

        3.14159
        [3.14159]

        6.02e23
        [6.02e+23]

        1e-12
        [1e-12]

        # any int or real number, returned as float
        100
        [100.0]

        -100
        [-100.0]

        +100
        [100.0]

        3.14159
        [3.14159]

        6.02e23
        [6.02e+23]

        1e-12
        [1e-12]

        # hex numbers
        100
        [256]

        FF
        [255]

        # fractions
        1/2
        [0.5]

        -3/4
        [-0.75]

        # mixed fractions
        1
        [1]

        1/2
        [0.5]

        -3/4
        [-0.75]

        1-3/4
        [1.75]

        # uuid
        12345678-1234-5678-1234-567812345678
        [UUID('12345678-1234-5678-1234-567812345678')]
    """

    convertToInteger = tokenMap(int)
    """
    Parse action for converting parsed integers to Python int
    """

    convertToFloat = tokenMap(float)
    """
    Parse action for converting parsed numbers to Python float
    """

    integer = Word(nums).setName("integer").setParseAction(convertToInteger)
    """expression that parses an unsigned integer, returns an int"""

    hex_integer = Word(hexnums).setName("hex integer").setParseAction(tokenMap(int, 16))
    """expression that parses a hexadecimal integer, returns an int"""

    signed_integer = (
        Regex(r"[+-]?\d+").setName("signed integer").setParseAction(convertToInteger)
    )
    """expression that parses an integer with optional leading sign, returns an int"""

    fraction = (
        signed_integer().setParseAction(convertToFloat)
        + "/"
        + signed_integer().setParseAction(convertToFloat)
    ).setName("fraction")
    """fractional expression of an integer divided by an integer, returns a float"""
    fraction.addParseAction(lambda t: t[0] / t[-1])

    mixed_integer = (
        fraction | signed_integer + Optional(Optional("-").suppress() + fraction)
    ).setName("fraction or mixed integer-fraction")
    """mixed integer of the form 'integer - fraction', with optional leading integer, returns float"""
    mixed_integer.addParseAction(sum)

    real = (
        Regex(r"[+-]?(?:\d+\.\d*|\.\d+)")
        .setName("real number")
        .setParseAction(convertToFloat)
    )
    """expression that parses a floating point number and returns a float"""

    sci_real = (
        Regex(r"[+-]?(?:\d+(?:[eE][+-]?\d+)|(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?)")
        .setName("real number with scientific notation")
        .setParseAction(convertToFloat)
    )
    """expression that parses a floating point number with optional
    scientific notation and returns a float"""

    # streamlining this expression makes the docs nicer-looking
    number = (sci_real | real | signed_integer).streamline()
    """any numeric expression, returns the corresponding Python type"""

    fnumber = (
        Regex(r"[+-]?\d+\.?\d*([eE][+-]?\d+)?")
        .setName("fnumber")
        .setParseAction(convertToFloat)
    )
    """any int or real number, returned as float"""

    identifier = Word(alphas + "_", alphanums + "_").setName("identifier")
    """typical code identifier (leading alpha or '_', followed by 0 or more alphas, nums, or '_')"""

    ipv4_address = Regex(
        r"(25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})(\.(25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})){3}"
    ).setName("IPv4 address")
    "IPv4 address (``0.0.0.0 - 255.255.255.255``)"

    _ipv6_part = Regex(r"[0-9a-fA-F]{1,4}").setName("hex_integer")
    _full_ipv6_address = (_ipv6_part + (":" + _ipv6_part) * 7).setName(
        "full IPv6 address"
    )
    _short_ipv6_address = (
        Optional(_ipv6_part + (":" + _ipv6_part) * (0, 6))
        + "::"
        + Optional(_ipv6_part + (":" + _ipv6_part) * (0, 6))
    ).setName("short IPv6 address")
    _short_ipv6_address.addCondition(
        lambda t: sum(1 for tt in t if pyparsing_common._ipv6_part.matches(tt)) < 8
    )
    _mixed_ipv6_address = ("::ffff:" + ipv4_address).setName("mixed IPv6 address")
    ipv6_address = Combine(
        (_full_ipv6_address | _mixed_ipv6_address | _short_ipv6_address).setName(
            "IPv6 address"
        )
    ).setName("IPv6 address")
    "IPv6 address (long, short, or mixed form)"

    mac_address = Regex(
        r"[0-9a-fA-F]{2}([:.-])[0-9a-fA-F]{2}(?:\1[0-9a-fA-F]{2}){4}"
    ).setName("MAC address")
    "MAC address xx:xx:xx:xx:xx (may also have '-' or '.' delimiters)"

    @staticmethod
    def convertToDate(fmt="%Y-%m-%d"):
        """
        Helper to create a parse action for converting parsed date string to Python datetime.date

        Params -
         - fmt - format to be passed to datetime.strptime (default= ``"%Y-%m-%d"``)

        Example::

            date_expr = pyparsing_common.iso8601_date.copy()
            date_expr.setParseAction(pyparsing_common.convertToDate())
            print(date_expr.parseString("1999-12-31"))

        prints::

            [datetime.date(1999, 12, 31)]
        """

        def cvt_fn(s, l, t):
            try:
                return datetime.strptime(t[0], fmt).date()
            except ValueError as ve:
                raise ParseException(s, l, str(ve))

        return cvt_fn

    @staticmethod
    def convertToDatetime(fmt="%Y-%m-%dT%H:%M:%S.%f"):
        """Helper to create a parse action for converting parsed
        datetime string to Python datetime.datetime

        Params -
         - fmt - format to be passed to datetime.strptime (default= ``"%Y-%m-%dT%H:%M:%S.%f"``)

        Example::

            dt_expr = pyparsing_common.iso8601_datetime.copy()
            dt_expr.setParseAction(pyparsing_common.convertToDatetime())
            print(dt_expr.parseString("1999-12-31T23:59:59.999"))

        prints::

            [datetime.datetime(1999, 12, 31, 23, 59, 59, 999000)]
        """

        def cvt_fn(s, l, t):
            try:
                return datetime.strptime(t[0], fmt)
            except ValueError as ve:
                raise ParseException(s, l, str(ve))

        return cvt_fn

    iso8601_date = Regex(
        r"(?P<year>\d{4})(?:-(?P<month>\d\d)(?:-(?P<day>\d\d))?)?"
    ).setName("ISO8601 date")
    "ISO8601 date (``yyyy-mm-dd``)"

    iso8601_datetime = Regex(
        r"(?P<year>\d{4})-(?P<month>\d\d)-(?P<day>\d\d)[T ](?P<hour>\d\d):(?P<minute>\d\d)(:(?P<second>\d\d(\.\d*)?)?)?(?P<tz>Z|[+-]\d\d:?\d\d)?"
    ).setName("ISO8601 datetime")
    "ISO8601 datetime (``yyyy-mm-ddThh:mm:ss.s(Z|+-00:00)``) - trailing seconds, milliseconds, and timezone optional; accepts separating ``'T'`` or ``' '``"

    uuid = Regex(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}").setName("UUID")
    "UUID (``xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx``)"

    _html_stripper = anyOpenTag.suppress() | anyCloseTag.suppress()

    @staticmethod
    def stripHTMLTags(s, l, tokens):
        """Parse action to remove HTML tags from web page HTML source

        Example::

            # strip HTML links from normal text
            text = '<td>More info at the <a href="https://github.com/pyparsing/pyparsing/wiki">pyparsing</a> wiki page</td>'
            td, td_end = makeHTMLTags("TD")
            table_text = td + SkipTo(td_end).setParseAction(pyparsing_common.stripHTMLTags)("body") + td_end
            print(table_text.parseString(text).body)

        Prints::

            More info at the pyparsing wiki page
        """
        return pyparsing_common._html_stripper.transformString(tokens[0])

    _commasepitem = (
        Combine(
            OneOrMore(
                ~Literal(",")
                + ~LineEnd()
                + Word(printables, excludeChars=",")
                + Optional(White(" \t") + ~FollowedBy(LineEnd() | ","))
            )
        )
        .streamline()
        .setName("commaItem")
    )
    comma_separated_list = delimitedList(
        Optional(quotedString.copy() | _commasepitem, default="")
    ).setName("comma separated list")
    """Predefined expression of 1 or more printable words or quoted strin gs, separated by commas."""

    upcaseTokens = staticmethod(tokenMap(lambda t: t.upper()))
    """Parse action to convert tokens to upper case."""

    downcaseTokens = staticmethod(tokenMap(lambda t: t.lower()))
    """Parse action to convert tokens to lower case."""


_builtin_exprs = [
    v for v in vars(pyparsing_common).values() if isinstance(v, ParserElement)
]
