import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest import TestCase, skipUnless

from lib.report.html_report import HTMLReport


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "lib"
    / "report"
    / "templates"
    / "html_report_template.html"
)


def extract_function(source, name):
    start = source.index(f"function {name}(")
    opening_brace = source.index("{", start)
    depth = 0

    for position in range(opening_brace, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]

    raise AssertionError(f"Unterminated JavaScript function: {name}")


class TestHTMLReportOffline(TestCase):
    def test_generated_report_has_no_remote_runtime_dependencies(self):
        source = HTMLReport().generate([])

        self.assertIsNone(re.search(r"<script[^>]+\bsrc=", source))
        self.assertIsNone(re.search(r"<link[^>]+\bhref=", source))

    def test_generated_report_contains_results_without_javascript(self):
        result_url = "https://example.test/admin?name=one&mode=two"
        source = HTMLReport().generate(
            [
                {
                    "url": result_url,
                    "status": 200,
                    "contentLength": 42,
                    "contentType": "text/plain",
                    "redirect": "/login",
                }
            ]
        )

        table_body = source.split('<tbody id="results-body">', 1)[1].split(
            "</tbody>", 1
        )[0]
        self.assertIn("data-report-result", table_body)
        self.assertIn("https://example.test/admin?name=one&amp;mode=two", table_body)
        self.assertIn("text/plain", table_body)
        self.assertIn("/login", table_body)


@skipUnless(shutil.which("node"), "Node.js is required for JavaScript tests")
class TestHTMLReportFilters(TestCase):
    @classmethod
    def setUpClass(cls):
        source = TEMPLATE_PATH.read_text(encoding="utf-8")
        cls.functions = "\n".join(
            extract_function(source, name)
            for name in (
                "queryTokens",
                "search",
                "lengthExcludeSearch",
                "safeHttpUrl",
            )
        )

    def evaluate(self, expression):
        script = f"""
{self.functions}
const value = (() => {{
{expression}
}})();
process.stdout.write(JSON.stringify(value));
"""
        completed = subprocess.run(
            ["node", "-"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_generated_inline_javascript_is_valid(self):
        source = HTMLReport().generate(
            [
                {
                    "url": "https://example.test/admin",
                    "status": 200,
                    "contentLength": 42,
                    "contentType": "text/plain",
                    "redirect": "/login",
                }
            ]
        )
        script = source.split("<script>", 1)[1].split("</script>", 1)[0]

        completed = subprocess.run(
            ["node", "--check", "-"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_search_matches_numeric_content_lengths_and_other_fields(self):
        result = self.evaluate(
            """
const result = {
  url: "https://example.test/admin",
  status: 200,
  contentLength: 42,
  contentType: "text/plain",
  redirect: "/login"
};
return [
  search({searchQuery: "42"}, result),
  search({searchQuery: "4"}, result),
  search({searchQuery: "admin 42"}, result),
  search({searchQuery: "200"}, result),
  search({searchQuery: "text/plain"}, result),
  search({searchQuery: "login"}, result),
  search({searchQuery: "0"}, {...result, contentLength: 0}),
  search({searchQuery: "42"}, {...result, contentLength: "42"}),
  search({searchQuery: "43"}, result),
  search({searchQuery: "42 missing"}, result)
];
"""
        )

        self.assertEqual(
            result,
            [True, True, True, True, True, True, True, True, False, False],
        )

    def test_length_exclusion_uses_exact_numeric_matches(self):
        result = self.evaluate(
            """
const result = {
  url: "https://example.test/admin",
  status: 200,
  contentLength: 42,
  contentType: "text/plain",
  redirect: ""
};
return [
  lengthExcludeSearch({lengthExcludeSearchQuery: "42"}, result),
  lengthExcludeSearch({lengthExcludeSearchQuery: "42 100"}, result),
  lengthExcludeSearch({lengthExcludeSearchQuery: "4"}, result),
  lengthExcludeSearch({lengthExcludeSearchQuery: "100 101"}, result),
  lengthExcludeSearch(
    {lengthExcludeSearchQuery: "0"},
    {...result, contentLength: 0}
  ),
  lengthExcludeSearch(
    {lengthExcludeSearchQuery: "42"},
    {...result, contentLength: "42"}
  )
];
"""
        )

        self.assertEqual(result, [False, False, True, True, False, False])

    def test_links_accept_http_urls_and_reject_active_schemes(self):
        result = self.evaluate(
            """
return [
  safeHttpUrl("https://example.test/admin"),
  safeHttpUrl("/login", "https://example.test/admin"),
  safeHttpUrl("javascript:alert(1)", "https://example.test/admin"),
  safeHttpUrl("data:text/html,unsafe", "https://example.test/admin")
];
"""
        )

        self.assertEqual(
            result,
            [
                "https://example.test/admin",
                "https://example.test/login",
                None,
                None,
            ],
        )
