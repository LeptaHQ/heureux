"""Run deployment database tasks unless this commit explicitly skips them."""

from __future__ import annotations

import os
import subprocess

from django.core.management import call_command
from django.core.management.base import BaseCommand


SKIP_DATABASE_MARKER = "[skip db]"


def deployment_commit_message() -> str:
    """Return the platform-provided message, falling back to the Git checkout."""
    message = os.environ.get("VERCEL_GIT_COMMIT_MESSAGE", "").strip()
    if message:
        return message
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def should_skip_database_deploy(message: str) -> bool:
    return SKIP_DATABASE_MARKER in message.casefold()


class Command(BaseCommand):
    help = (
        "Apply migrations and synchronize bundled content for a deployment. "
        "A commit marked [skip db] bypasses these tasks for a schema-free "
        "rollout when the database is temporarily unavailable."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run database tasks even when the commit is marked [skip db].",
        )

    def handle(self, *args, **options):
        message = deployment_commit_message()
        if not options["force"] and should_skip_database_deploy(message):
            self.stdout.write(
                "Database deployment skipped by the current commit marker."
            )
            return

        verbosity = options["verbosity"]
        call_command(
            "migrate",
            interactive=False,
            verbosity=verbosity,
        )
        call_command(
            "import_content",
            if_changed=True,
            verbosity=verbosity,
        )
