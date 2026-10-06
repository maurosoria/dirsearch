from pathlib import Path
from unittest import TestCase


class TestDockerWorkflow(TestCase):
    def test_compose_plan_grants_only_host_network_to_bake(self):
        workflow = Path(".github/workflows/docker-image.yml").read_text(
            encoding="utf-8"
        )
        build_step = workflow.split("- name: Build Docker image\n", 1)[1].split(
            "- name: Test Docker image\n", 1
        )[0]

        # Explicit bash enables pipefail: a failed Compose plan must fail CI too.
        self.assertIn("shell: bash", build_step)
        self.assertIn("docker compose -f - build --print dirsearch", build_step)
        self.assertIn(
            "| docker buildx bake --file - --allow=network.host --load dirsearch",
            build_step,
        )
        self.assertIn("network: host", build_step)
        self.assertIn("entitlements:\n                  - network.host", build_step)
        self.assertNotIn("security.insecure", build_step)
        self.assertNotIn("privileged: true", build_step)

    def test_release_matrix_keeps_all_stack_smokes(self):
        workflow = Path(".github/workflows/docker-image.yml").read_text(
            encoding="utf-8"
        )
        for stack in ("threaded", "async", "native-rust"):
            with self.subTest(stack=stack):
                self.assertIn(f"          - {stack}\n", workflow)
        self.assertIn('"${{ steps.image.outputs.tag }}" --version', workflow)
        self.assertIn('"${{ steps.image.outputs.tag }}" --help', workflow)
        self.assertIn("--allow=network.host --load dirsearch", workflow)
