import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase


class InterviewEngineTests(SimpleTestCase):
    @skipUnless(shutil.which("node"), "Node is required for JavaScript unit checks")
    def test_followups_and_feedback(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("eo1_interview_engine_check.js"))],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
