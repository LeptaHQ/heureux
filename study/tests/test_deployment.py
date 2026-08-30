"""Deployment configuration and database connection defaults.

These guard the settings that keep a serverless Postgres (Neon) asleep: short
connection lifetimes, no deploy-time database work in the web start path, and
fingerprinted imports that remain safe when both platforms deploy.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import call, patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings import (
    default_conn_health_checks,
    default_conn_max_age,
    env_int,
    is_pooled_db_host,
)
from study.management.commands.deploy_database import (
    Command as DatabaseDeployCommand,
    deployment_commit_message,
    should_skip_database_deploy,
)

REPO_ROOT = Path(settings.BASE_DIR)
RENDER_YAML = REPO_ROOT / "render.yaml"
VERCEL_JSON = REPO_ROOT / "vercel.json"

DEPLOY_COMMAND = "python manage.py deploy_database"


def render_service_fields() -> dict[str, str]:
    """Scalar fields of the single web service in render.yaml.

    PyYAML is not a project dependency, and the fields under test are plain
    ``key: value`` scalars, so read them directly instead.
    """
    fields = {}
    in_service = False
    for line in RENDER_YAML.read_text().splitlines():
        if line.startswith("  - type:"):
            in_service = True
            fields["type"] = line.split(":", 1)[1].strip()
            continue
        if not in_service or not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"    ([A-Za-z]+): (.*)", line)
        if not match:
            continue
        key, value = match.groups()
        fields[key] = value.strip().strip('"')
    return fields


class ConnectionDefaultsTests(SimpleTestCase):
    def test_invalid_connection_lifetime_fails_loudly(self):
        with patch.dict(os.environ, {"TEST_DB_CONN_MAX_AGE": "invalid"}):
            with self.assertRaises(ImproperlyConfigured):
                env_int("TEST_DB_CONN_MAX_AGE", 60)

    def test_negative_connection_lifetime_fails_loudly(self):
        with patch.dict(os.environ, {"TEST_DB_CONN_MAX_AGE": "-1"}):
            with self.assertRaises(ImproperlyConfigured):
                env_int("TEST_DB_CONN_MAX_AGE", 60)

    def test_serverless_never_holds_a_connection_open(self):
        self.assertEqual(
            default_conn_max_age(on_vercel=True, on_render=False),
            0,
        )

    def test_render_keeps_connections_briefly(self):
        self.assertEqual(
            default_conn_max_age(on_vercel=False, on_render=True),
            60,
        )

    def test_local_development_keeps_connections(self):
        self.assertEqual(
            default_conn_max_age(on_vercel=False, on_render=False),
            600,
        )

    def test_vercel_wins_when_both_platforms_look_present(self):
        self.assertEqual(
            default_conn_max_age(on_vercel=True, on_render=True),
            0,
        )

    def test_health_checks_only_where_connections_are_reused(self):
        self.assertFalse(default_conn_health_checks(on_vercel=True))
        self.assertTrue(default_conn_health_checks(on_vercel=False))

    def test_pooled_neon_hosts_are_detected(self):
        self.assertTrue(
            is_pooled_db_host("ep-cool-name-123456-pooler.us-east-2.aws.neon.tech")
        )
        self.assertTrue(is_pooled_db_host("EP-NAME-POOLER.eu-central-1.aws.neon.tech"))

    def test_direct_hosts_are_not_treated_as_pooled(self):
        self.assertFalse(
            is_pooled_db_host("ep-cool-name-123456.us-east-2.aws.neon.tech")
        )
        self.assertFalse(is_pooled_db_host(""))
        self.assertFalse(is_pooled_db_host(None))

    def test_database_config_carries_the_connection_settings(self):
        config = settings.DATABASES["default"]

        self.assertIn("CONN_MAX_AGE", config)
        self.assertIn("CONN_HEALTH_CHECKS", config)
        self.assertIsInstance(config["DISABLE_SERVER_SIDE_CURSORS"], bool)
        self.assertEqual(
            config["DISABLE_SERVER_SIDE_CURSORS"],
            is_pooled_db_host(config.get("HOST", "")),
        )


class DeploymentCommandTests(SimpleTestCase):
    def setUp(self):
        self.service = render_service_fields()

    def test_render_start_command_only_launches_the_server(self):
        start = self.service["startCommand"]

        self.assertTrue(start.startswith("gunicorn config.wsgi:application"))
        # A cold start or restart re-runs startCommand; deploy-time database
        # work there wakes Neon on every restart.
        self.assertNotIn("manage.py", start)

    def test_free_render_runs_database_deployment_during_the_build(self):
        self.assertEqual(self.service["plan"], "free")
        self.assertNotIn("preDeployCommand", self.service)
        build = self.service["buildCommand"]
        self.assertIn(DEPLOY_COMMAND, build)

    def test_render_runs_deploy_database_work_exactly_once_per_deploy(self):
        # The free plan runs this in the build; it must never leak back into the
        # start path, which is executed again on every cold start.
        deploy_time = self.service["buildCommand"]
        self.assertEqual(deploy_time.count("manage.py deploy_database"), 1)

    def test_render_build_command_installs_the_app(self):
        build = self.service["buildCommand"]

        self.assertIn("pip install -r requirements.txt", build)
        self.assertIn("collectstatic", build)

    def test_render_health_check_path(self):
        self.assertEqual(self.service["healthCheckPath"], "/healthz")

    def test_render_pins_the_database_connection_lifetime(self):
        body = RENDER_YAML.read_text()

        self.assertIn("DB_CONN_MAX_AGE", body)
        self.assertIn(
            str(default_conn_max_age(on_vercel=False, on_render=True)),
            body,
        )

    def test_vercel_build_runs_the_database_deployment_command(self):
        config = json.loads(VERCEL_JSON.read_text())

        self.assertEqual(config["buildCommand"], DEPLOY_COMMAND)


class DatabaseDeployCommandTests(SimpleTestCase):
    def test_skip_marker_is_case_insensitive(self):
        self.assertTrue(
            should_skip_database_deploy(
                "Roll out compute safeguards [SKIP DB]"
            )
        )
        self.assertFalse(should_skip_database_deploy("Normal deployment"))

    def test_platform_commit_message_avoids_git_lookup(self):
        with (
            patch.dict(
                os.environ,
                {"VERCEL_GIT_COMMIT_MESSAGE": "Platform message"},
            ),
            patch("subprocess.run") as run,
        ):
            self.assertEqual(deployment_commit_message(), "Platform message")
        run.assert_not_called()

    def test_marked_commit_skips_database_commands(self):
        command = DatabaseDeployCommand()
        with (
            patch(
                "study.management.commands.deploy_database."
                "deployment_commit_message",
                return_value="Schema-free rollout [skip db]",
            ),
            patch(
                "study.management.commands.deploy_database.call_command"
            ) as call_command_mock,
        ):
            command.handle(force=False, verbosity=1)
        call_command_mock.assert_not_called()

    def test_normal_commit_migrates_then_imports(self):
        command = DatabaseDeployCommand()
        with (
            patch(
                "study.management.commands.deploy_database."
                "deployment_commit_message",
                return_value="Normal deployment",
            ),
            patch(
                "study.management.commands.deploy_database.call_command"
            ) as call_command_mock,
        ):
            command.handle(force=False, verbosity=1)
        self.assertEqual(
            call_command_mock.call_args_list,
            [
                call(
                    "migrate",
                    interactive=False,
                    verbosity=1,
                ),
                call(
                    "import_content",
                    if_changed=True,
                    verbosity=1,
                ),
            ],
        )

    def test_force_runs_database_commands_for_a_marked_commit(self):
        command = DatabaseDeployCommand()
        with (
            patch(
                "study.management.commands.deploy_database."
                "deployment_commit_message",
                return_value="Retry [skip db]",
            ),
            patch(
                "study.management.commands.deploy_database.call_command"
            ) as call_command_mock,
        ):
            command.handle(force=True, verbosity=1)
        self.assertEqual(call_command_mock.call_count, 2)
