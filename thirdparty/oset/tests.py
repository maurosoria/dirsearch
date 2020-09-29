#!/usr/bin/env python
# -*- mode:python; tab-width: 2; coding: utf-8 -*-

"""Partially backported python ABC classes"""


import doctest
import unittest

optionflags = (
    doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS | doctest.REPORT_ONLY_FIRST_FAILURE
)

TESTFILES = ["pyoset.txt"]


def test_suite():
    """Simple tes suite"""

    globs = {}
    try:
        from pprint import pprint

        globs["pprint"] = pprint
    except Exception:
        pass
    try:
        from interlude import interact

        globs["interact"] = interact
    except Exception:
        pass

    return unittest.TestSuite(
        [
            doctest.DocFileSuite(file, optionflags=optionflags, globs=globs)
            for file in TESTFILES
        ]
    )


if __name__ == "__main__":
    unittest.main(defaultTest="test_suite")
