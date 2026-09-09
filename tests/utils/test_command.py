from unittest import TestCase

from lib.utils.command import REDACTED_VALUE, redact_command


class TestCommandRedaction(TestCase):
    def test_redacts_sensitive_option_forms_and_preserves_safe_arguments(self):
        secrets = (
            "AUTH_EQUALS_SECRET",
            "PROXY_SPLIT_SECRET",
            "DATA_SHORT_SECRET",
            "DATA_SPLIT_SECRET",
            "HEADER_SPLIT_SECRET",
            "HEADER_EQUALS_SECRET",
            "COOKIE_SECRET",
            "PROXY_URL_SECRET",
            "REPLAY_SECRET",
            "MYSQL_SECRET",
            "POSTGRES_SECRET",
            "TARGET_SPLIT_SECRET",
            "TARGET_EQUALS_SECRET",
            "PROXY_ABBREVIATION_SECRET",
            "COOKIE_ABBREVIATION_SECRET",
            "MYSQL_ABBREVIATION_SECRET",
            "REPLAY_ABBREVIATION_SECRET",
            "CLUSTER_DATA_SECRET",
            "CLUSTER_HEADER_SECRET",
            "CLUSTER_PROXY_SECRET",
            "CLUSTER_TARGET_SECRET",
        )
        arguments = [
            "dirsearch.py",
            "--auth=AUTH_EQUALS_SECRET",
            "--proxy-auth",
            "PROXY_SPLIT_SECRET",
            "-dDATA_SHORT_SECRET",
            "--data",
            "DATA_SPLIT_SECRET",
            "-H",
            "Authorization: HEADER_SPLIT_SECRET",
            "--header=Cookie: HEADER_EQUALS_SECRET",
            "--cookie",
            "COOKIE_SECRET",
            "-phttp://proxy-user:PROXY_URL_SECRET@proxy.test",
            "--replay-proxy=http://replay-user:REPLAY_SECRET@proxy.test",
            "--mysql-url",
            "mysql://db-user:MYSQL_SECRET@db.test/name",
            "--postgres-url=postgresql://db-user:POSTGRES_SECRET@db.test/name",
            "-u",
            "https://target-user:TARGET_SPLIT_SECRET@example.test",
            "--url=https://target-user:TARGET_EQUALS_SECRET@example.test",
            "--proxy-a",
            "PROXY_ABBREVIATION_SECRET",
            "--cook=COOKIE_ABBREVIATION_SECRET",
            "--mys",
            "mysql://db-user:MYSQL_ABBREVIATION_SECRET@db.test/name",
            "--replay-p=http://replay-user:REPLAY_ABBREVIATION_SECRET@proxy.test",
            "-qd",
            "CLUSTER_DATA_SECRET",
            "-qH",
            "Authorization: CLUSTER_HEADER_SECRET",
            "-qphttp://proxy-user:CLUSTER_PROXY_SECRET@proxy.test",
            "-quhttps://target-user:CLUSTER_TARGET_SECRET@example.test",
            "--threads",
            "7",
            "--crawl",
        ]

        command = redact_command(arguments)

        for secret in secrets:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, command)
        self.assertIn(f"--auth={REDACTED_VALUE}", command)
        self.assertIn(f"-d{REDACTED_VALUE}", command)
        self.assertIn("--threads 7 --crawl", command)

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
