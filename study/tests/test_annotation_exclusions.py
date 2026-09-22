import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase


class AnnotationExclusionTests(SimpleTestCase):
    @skipUnless(shutil.which("node"), "Node is required for JavaScript unit checks")
    def test_french_offsets_and_selection_suppression(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("annotation_exclusions_check.js"))],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checks passed", result.stdout)
