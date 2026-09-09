from unittest import TestCase

from lib.utils.command import REDACTED_VALUE, redact_command


class TestCommandRedaction(TestCase):
    def test_replaces_realistic_secret_values_with_exact_marker(self):
        cases = (
            (
                "split auth",
                ["--auth", "alice:auth-password"],
                ["--auth", REDACTED_VALUE],
            ),
            (
                "equals auth",
                ["--auth=alice:auth-password"],
                [f"--auth={REDACTED_VALUE}"],
            ),
            (
                "attached body",
                ["-dusername=alice&password=body-password"],
                [f"-d{REDACTED_VALUE}"],
            ),
            (
                "split body",
                ["--data", "username=alice&password=body-password"],
                ["--data", REDACTED_VALUE],
            ),
            (
                "authorization header",
                ["-H", "Authorization: Bearer fake.jwt.signature"],
                ["-H", REDACTED_VALUE],
            ),
            (
                "cookie header",
                ["--header=Cookie: session=header-cookie-value"],
                [f"--header={REDACTED_VALUE}"],
            ),
            (
                "cookie option",
                ["--cookie", "session=cookie-value; csrftoken=csrf-value"],
                ["--cookie", REDACTED_VALUE],
            ),
            (
                "attached proxy",
                ["-phttp://proxy-user:proxy-password@proxy.example"],
                [f"-p{REDACTED_VALUE}"],
            ),
            (
                "replay proxy",
                ["--replay-proxy=http://replay-user:replay-password@proxy.example"],
                [f"--replay-proxy={REDACTED_VALUE}"],
            ),
            (
                "mysql URL",
                ["--mysql-url", "mysql://reporter:mysql-password@db.example/scan"],
                ["--mysql-url", REDACTED_VALUE],
            ),
            (
                "postgres URL",
                [
                    "--postgres-url=postgresql://reporter:postgres-password"
                    "@db.example/scan"
                ],
                [f"--postgres-url={REDACTED_VALUE}"],
            ),
            (
                "split target userinfo",
                ["-u", "https://alice:target-password@target.example"],
                ["-u", REDACTED_VALUE],
            ),
            (
                "equals target userinfo",
                ["--url=https://alice:target-password@target.example"],
                [f"--url={REDACTED_VALUE}"],
            ),
            (
                "abbreviated proxy auth",
                ["--proxy-a", "proxy-user:proxy-auth-password"],
                ["--proxy-a", REDACTED_VALUE],
            ),
            (
                "abbreviated cookie",
                ["--cook=session=abbreviated-cookie-value"],
                [f"--cook={REDACTED_VALUE}"],
            ),
            (
                "abbreviated mysql URL",
                ["--mys", "mysql://reporter:mysql-password@db.example/scan"],
                ["--mys", REDACTED_VALUE],
            ),
            (
                "abbreviated replay proxy",
                ["--replay-p=http://user:replay-password@proxy.example"],
                [f"--replay-p={REDACTED_VALUE}"],
            ),
            (
                "clustered split body",
                ["-qd", "username=alice&password=cluster-password"],
                ["-qd", REDACTED_VALUE],
            ),
            (
                "clustered split header",
                ["-qH", "Authorization: Bearer clustered-token"],
                ["-qH", REDACTED_VALUE],
            ),
            (
                "clustered attached proxy",
                ["-qphttp://user:cluster-password@proxy.example"],
                [f"-qp{REDACTED_VALUE}"],
            ),
            (
                "clustered attached target",
                ["-quhttps://alice:cluster-password@target.example"],
                [f"-qu{REDACTED_VALUE}"],
            ),
        )

        for name, supplied, expected in cases:
            with self.subTest(name=name):
                arguments = ["dirsearch.py", *supplied, "--threads", "7"]
                expected_command = " ".join(
                    ["dirsearch.py", *expected, "--threads", "7"]
                )
                self.assertEqual(redact_command(arguments), expected_command)

    def test_preserves_other_short_options_with_attached_values(self):
        arguments = [
            "dirsearch.py",
            "-ephp",
            "-t25",
            "-Ojson,xml",
            "-qf",
        ]

        self.assertEqual(redact_command(arguments), " ".join(arguments))

    def test_preserves_target_without_embedded_credentials(self):
        command = redact_command(
            [
                "dirsearch.py",
                "-u",
                "https://example.test/path",
                "--threads",
                "7",
            ]
        )

        self.assertEqual(
            command,
            "dirsearch.py -u https://example.test/path --threads 7",
        )
