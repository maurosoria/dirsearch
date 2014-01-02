from difflib import SequenceMatcher

DYNAMICITY_MARK_LENGTH = 32
UPPER_RATIO_BOUND = 0.98

class DynamicContentParser:

	def __init__(self, firstPage, secondPage):
		self.firstPage = firstPage
		self.secondPage = secondPage

	@staticmethod
	def checkDynamicContent(firstPage, secondPage, dynamicMarks):
	    if any(page is None for page in (firstPage, secondPage)):
	        # No content
	        return

	    seqMatcher = getCurrentThreadData().seqMatcher
	    seqMatcher.set_seq1(firstPage)
	    seqMatcher.set_seq2(secondPage)

	    # In case of an intolerable difference turn on dynamicity removal engine
	    if seqMatcher.quick_ratio() <= UPPER_RATIO_BOUND:
	        findDynamicContent(firstPage, secondPage)

	        count = 0
	        while not Request.queryPage():
	            count += 1

	            if count > conf.retries:
	                # Too dynamic
	                return

	            secondPage, _ = Request.queryPage(content=True)
	            findDynamicContent(firstPage, secondPage)



	@staticmethod
	def findDynamicContent(firstPage, secondPage):
		dynamicMarks = []

		blocks = SequenceMatcher(None, firstPage, secondPage)

		# Removing too small matching blocks
		for block in blocks[:]:
			(_, _, length) = block

			if length <= DYNAMICITY_MARK_LENGTH:
				blocks.remove(block)

		# Making of dynamic markings based on prefix/suffix principle
		if len(blocks) > 0:
			blocks.insert(0, None)
			blocks.append(None)

			for i in xrange(len(blocks) - 1):
				prefix = firstPage[blocks[i][0]:blocks[i][0] + blocks[i][2]] if blocks[i] else None
            	suffix = firstPage[blocks[i + 1][0]:blocks[i + 1][0] + blocks[i + 1][2]] if blocks[i + 1] else None

            if prefix is None and blocks[i + 1][0] == 0:
                continue

            if suffix is None and (blocks[i][0] + blocks[i][2] >= len(firstPage)):
                continue


            dynamicMarks.append((re.escape(prefix[-DYNAMICITY_MARK_LENGTH / 2:]) if prefix else None, re.escape(suffix[:DYNAMICITY_MARK_LENGTH / 2]) if suffix else None))

            return dynamicMarks


    @staticmethod
    def trimAlphaNum(value):
    	#    Trims alpha numeric characters from start and ending of a given value
    	while value and value[-1].isalnum():
        	value = value[:-1]

    	while value and value[0].isalnum():
        	value = value[1:]

    	return value


    @staticmethod
    def removeDynamicContent(page, dynamicMarks):
    """
    Removing dynamic content from supplied page basing removal on
    precalculated dynamic markings
    """
    if page:
        for item in dynamicMarkings:
            prefix, suffix = item

            if prefix is None and suffix is None:
                continue
            elif prefix is None:
                page = re.sub(r'(?s)^.+%s' % suffix, suffix, page)
            elif suffix is None:
                page = re.sub(r'(?s)%s.+$' % prefix, prefix, page)
            else:
                page = re.sub(r'(?s)%s.+%s' % (prefix, suffix), '%s%s' % (prefix, suffix), page)

    return page