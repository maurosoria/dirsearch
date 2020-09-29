from difflib import SequenceMatcher
import re

from thirdparty import chardet


class DynamicContentParser:
    def __init__(self, requester, path, firstPage, secondPage, comparisons=2):
        self.DYNAMICITY_MARK_LENGTH = 32
        self.UPPER_RATIO_BOUND = 0.98
        self.requester = requester
        self.keyCallback = path
        self.comparisons = comparisons
        self.dynamicMarks = []
        self.seqMatcher = SequenceMatcher()
        self.generateDynamicMarks(firstPage, secondPage)

    def generateDynamicMarks(self, firstPage, secondPage):
        if any(page is None for page in (firstPage, secondPage)):
            # No content
            return

        self.seqMatcher.set_seq1(firstPage)
        self.seqMatcher.set_seq2(secondPage)
        ratio = self.seqMatcher.quick_ratio()
        # In case of an intolerable difference turn on dynamicity removal engine
        if ratio <= self.UPPER_RATIO_BOUND:
            self.dynamicMarks += self.findDynamicContent(firstPage, secondPage)
            for i in range(self.comparisons):
                response = self.requester.request(self.keyCallback)
                secondPage = response.body
                self.dynamicMarks += self.findDynamicContent(firstPage, secondPage)
            self.cleanPage = self.removeDynamicContent(firstPage, self.dynamicMarks)
            self.seqMatcher.set_seq1(self.cleanPage)
            self.seqMatcher.set_seq2(
                self.removeDynamicContent(secondPage, self.dynamicMarks)
            )
            ratio = self.seqMatcher.quick_ratio()
        else:
            self.cleanPage = firstPage
        self.comparisonRatio = ratio

    def compareTo(self, page):
        seqMatcher = SequenceMatcher()
        seqMatcher.set_seq1(self.cleanPage)
        seqMatcher.set_seq2(self.removeDynamicContent(page, self.dynamicMarks))
        ratio = seqMatcher.quick_ratio()
        return ratio

    def findDynamicContent(self, firstPage, secondPage):
        dynamicMarks = []

        blocks = list(
            SequenceMatcher(None, firstPage, secondPage).get_matching_blocks()
        )

        # Removing too small matching blocks
        for block in blocks[:]:
            (_, _, length) = block

            if length <= self.DYNAMICITY_MARK_LENGTH:
                blocks.remove(block)

        # Making of dynamic markings based on prefix/suffix principle
        if len(blocks) > 0:
            blocks.insert(0, None)
            blocks.append(None)

            for i in range(len(blocks) - 1):
                prefix = (
                    firstPage[blocks[i][0] : blocks[i][0] + blocks[i][2]]
                    if blocks[i]
                    else None
                )
                suffix = (
                    firstPage[blocks[i + 1][0] : blocks[i + 1][0] + blocks[i + 1][2]]
                    if blocks[i + 1]
                    else None
                )

                if prefix is None and blocks[i + 1][0] == 0:
                    continue

                if suffix is None and (blocks[i][0] + blocks[i][2] >= len(firstPage)):
                    continue

                dynamicMarks.append(
                    (
                        re.escape(prefix[int(-self.DYNAMICITY_MARK_LENGTH / 2) :])
                        if prefix
                        else None,
                        re.escape(suffix[: int(self.DYNAMICITY_MARK_LENGTH / 2)])
                        if suffix
                        else None,
                    )
                )

        return dynamicMarks

    def removeDynamicContent(self, page, dynamicMarks):
        """
        Removing dynamic content from supplied page basing removal on
        precalculated dynamic markings
        """
        if page and len(dynamicMarks) > 0:
            encoding = chardet.detect(page)["encoding"]
            page = page.decode(encoding, errors="replace")
            for item in dynamicMarks:
                prefix, suffix = item
                if prefix is not None:
                    prefix = prefix.decode(encoding, errors="replace")
                if suffix is not None:
                    suffix = suffix.decode(encoding, errors="replace")

                if prefix is None and suffix is None:
                    continue
                elif prefix is None:
                    page = re.sub(
                        r"(?s)^.+{0}".format(re.escape(suffix)),
                        suffix.replace("\\", r"\\"),
                        page,
                    )
                elif suffix is None:
                    page = re.sub(
                        r"(?s){0}.+$".format(re.escape(prefix)),
                        prefix.replace("\\", r"\\"),
                        page,
                    )
                else:
                    page = re.sub(
                        r"(?s){0}.+{1}".format(re.escape(prefix), re.escape(suffix)),
                        "{0}{1}".format(
                            prefix.replace("\\", r"\\"), suffix.replace("\\", r"\\")
                        ),
                        page,
                    )

            page = page.encode()

        return page
