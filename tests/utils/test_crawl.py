# -*- coding: utf-8 -*-
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#  Author: Mauro Soria

import gc
import weakref
from unittest import TestCase

from lib.core.settings import DUMMY_URL
from lib.utils.crawl import Crawler


class WeakText(str):
    pass


class TestCrawl(TestCase):
    def assert_body_is_released(self, parser, body):
        clear_cache = getattr(parser, "cache_clear", None)
        if clear_cache:
            clear_cache()

        content = WeakText(body)
        reference = weakref.ref(content)
        try:
            parser(DUMMY_URL, DUMMY_URL, content)
            del content
            gc.collect()
            self.assertIsNone(reference())
        finally:
            if clear_cache:
                clear_cache()

    def test_text_crawl(self):
        html_doc = f'Link: {DUMMY_URL}foobar'
        self.assertEqual(Crawler.text_crawl(DUMMY_URL, DUMMY_URL, html_doc), {"foobar"})

    def test_text_crawl_preserves_url_components(self):
        paths = (
            "api/v1/users?next=/dashboard",
            "public/scripts/",
            "catalog;view=full/items:latest@v2?filter[status]=active",
            "reports/Ben's_(final)/view?format=csv",
            "search/%E2%9C%93?q=one%20two&next=/account?tab=keys",
            "?page=2&next=/dashboard",
        )

        for path in paths:
            with self.subTest(path=path):
                text_doc = f'const endpoint = "{DUMMY_URL}{path}";'

                self.assertEqual(
                    Crawler.text_crawl(DUMMY_URL, DUMMY_URL, text_doc),
                    {path},
                )

    def test_text_crawl_handles_serialized_url_forms(self):
        cases = (
            (
                'JSON escaped solidus',
                r'const endpoint = "https:\/\/example.com\/api\/v1\/users";',
                "api/v1/users",
            ),
            (
                'JavaScript Unicode escape',
                r'const endpoint = "https:\u002F\u002Fexample.com\u002Fgraphql\u002Fv2";',
                "graphql/v2",
            ),
            (
                'JavaScript hexadecimal escape',
                r'const endpoint = "https:\x2f\x2fexample.com\x2fassets\x2fapp.js";',
                "assets/app.js",
            ),
            (
                "case-insensitive origin",
                'const endpoint = "HTTPS://EXAMPLE.COM/Admin/Users";',
                "Admin/Users",
            ),
        )

        for name, text_doc, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    Crawler.text_crawl(DUMMY_URL, DUMMY_URL, text_doc),
                    {expected},
                )

    def test_text_crawl_respects_context_delimiters(self):
        text_doc = (
            f'quoted = "{DUMMY_URL}api/search?q=one,two"; '
            f"fetch('{DUMMY_URL}api/health'); "
            f"angle = <{DUMMY_URL}docs/start>; "
            f"See ({DUMMY_URL}docs/(draft)). "
            f"Then visit {DUMMY_URL}account/profile, and continue."
        )

        self.assertEqual(
            Crawler.text_crawl(DUMMY_URL, DUMMY_URL, text_doc),
            {
                "account/profile",
                "api/health",
                "api/search?q=one,two",
                "docs/(draft)",
                "docs/start",
            },
        )

    def test_text_crawl_keeps_scope_and_fragment_boundaries(self):
        text_doc = (
            f"{DUMMY_URL}api/health#readiness "
            f"{DUMMY_URL}api/health#liveness "
            f"{DUMMY_URL}#overview "
            "http://example.com/wrong-scheme "
            "https://example.com.evil.test/lookalike "
            "https://other.example/api/external"
        )

        self.assertEqual(
            Crawler.text_crawl(DUMMY_URL, DUMMY_URL, text_doc),
            {"api/health"},
        )

    def test_text_crawl_filters_media_paths_not_route_suffixes(self):
        text_doc = (
            f'route = "{DUMMY_URL}api/generatepdf"; '
            f'image = "{DUMMY_URL}assets/LOGO.PNG?v=2#hero";'
        )

        self.assertEqual(
            Crawler.text_crawl(DUMMY_URL, DUMMY_URL, text_doc),
            {"api/generatepdf"},
        )

    def test_html_crawl(self):
        html_doc = f'<a href="{DUMMY_URL}foo">link</a><script src="/bar.js"><img src="/bar.png">'
        self.assertEqual(Crawler.html_crawl(DUMMY_URL, DUMMY_URL, html_doc), {"foo", "bar.js"})

    def test_html_crawl_resolves_only_canonical_same_origin_urls(self):
        url = "https://example.com/section/page"
        html_doc = r"""
            <a href="//EXAMPLE.COM:443/protocol-relative">same origin</a>
            <a href="https://EXAMPLE.COM:443/absolute">same origin</a>
            <a href="\\EXAMPLE.COM:443\backslash-relative">same origin</a>
            <a href="/query?pattern=\d+">query backslash is data</a>
            <a href="//cdn.example/external">external host</a>
            <a href="\\cdn.example\external-backslash">external host</a>
            <a href="http://example.com/wrong-scheme">wrong scheme</a>
            <a href="https://example.com:444/wrong-port">wrong port</a>
            <a href="https://example.com:invalid/bad-port">invalid port</a>
            <a href="https://[invalid/bad-host">invalid host</a>
            <a href="https://example.com.evil.test/lookalike">lookalike</a>
        """

        self.assertEqual(
            Crawler.html_crawl(url, DUMMY_URL, html_doc),
            {
                "absolute",
                "backslash-relative",
                "protocol-relative",
                r"query?pattern=\d+",
            },
        )

    def test_html_crawl_uses_first_base_without_queueing_it(self):
        url = "https://example.com/section/page"
        html_doc = """
            <base href="/assets/">
            <base href="/ignored/">
            <a href="api/users?next=/dashboard#details">API</a>
            <script src="scripts/app.js"></script>
        """

        self.assertEqual(
            Crawler.html_crawl(url, DUMMY_URL, html_doc),
            {
                "assets/api/users?next=/dashboard",
                "assets/scripts/app.js",
            },
        )

    def test_html_crawl_does_not_localize_paths_under_external_base(self):
        url = "https://example.com/section/page"
        html_doc = """
            <base href="https://cdn.example/assets/">
            <a href="relative-api">external through base</a>
            <a href="https://example.com/local-api">explicitly local</a>
        """

        self.assertEqual(
            Crawler.html_crawl(url, DUMMY_URL, html_doc),
            {"local-api"},
        )

    def test_html_crawl_ignores_invalid_or_unsafe_first_base(self):
        url = "https://example.com/section/page"

        for base in (
            "data:text/html,ignored",
            "javascript:alert(1)",
            "http://[invalid",
        ):
            with self.subTest(base=base):
                html_doc = (
                    f'<base href="{base}">'
                    '<base href="/second-base-is-ignored/">'
                    '<a href="relative-api">API</a>'
                )

                self.assertEqual(
                    Crawler.html_crawl(url, DUMMY_URL, html_doc),
                    {"section/relative-api"},
                )

    def test_html_crawl_parses_source_and_img_srcset_candidates(self):
        url = "https://example.com/page"
        html_doc = """
            <source srcset="/render/small?format=jpg 1x,
                            /render/large?format=jpg 2x,
                            /render/no-descriptor,
                            /render/final-no-descriptor">
            <img src="/image-endpoint"
                 srcset="/image?crop=1,2 640w,
                         //cdn.example/external 2x,
                         data:image/svg+xml,&lt;svg&gt;&lt;/svg&gt; 3x">
        """

        self.assertEqual(
            Crawler.html_crawl(url, DUMMY_URL, html_doc),
            {
                "image-endpoint",
                "image?crop=1,2",
                "render/large?format=jpg",
                "render/final-no-descriptor",
                "render/no-descriptor",
                "render/small?format=jpg",
            },
        )

    def test_html_crawl_handles_rtl_override(self):
        html_doc = '<a href="/admin/\u202eexe.txt/">link</a>'

        self.assertEqual(
            Crawler.html_crawl(DUMMY_URL, DUMMY_URL, html_doc),
            {"admin/\u202eexe.txt/"},
        )

    def test_html_crawl_handles_large_zwj_emoji_sequence(self):
        family = "👨‍👩‍👧‍👦" * 500
        html_doc = f'<a href="/admin/{family}/ok">link</a>'

        self.assertEqual(
            Crawler.html_crawl(DUMMY_URL, DUMMY_URL, html_doc),
            {f"admin/{family}/ok"},
        )

    def test_robots_crawl(self):
        robots_txt = """
User-agent: Googlebot
Disallow: /path1

User-agent: *
        Allow: /path2"""
        self.assertEqual(Crawler.robots_crawl(DUMMY_URL, DUMMY_URL, robots_txt), {"path1", "path2"})

    def test_text_crawl_releases_response_body(self):
        self.assert_body_is_released(
            Crawler.text_crawl,
            f"Link: {DUMMY_URL}text-retention-check",
        )

    def test_html_crawl_releases_response_body(self):
        self.assert_body_is_released(
            Crawler.html_crawl,
            '<a href="/html-retention-check">link</a>',
        )

    def test_robots_crawl_releases_response_body(self):
        self.assert_body_is_released(
            Crawler.robots_crawl,
            "Allow: /robots-retention-check",
        )
