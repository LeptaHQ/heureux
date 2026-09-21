from __future__ import annotations

from threading import Event, Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature, tag
from django.urls import reverse
from django.utils import timezone

from study.account_services import _recovery_code_digest, generate_recovery_codes
from study.models import AccountRecoveryCode, Annotation, AnnotationKind, WritingResponseOverride

from . import factories


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AccountReliabilityTests(TestCase):
    def test_export_preserves_owned_writing_overrides_and_annotation_state(self):
        owner = factories.make_user("export-owner")
        other = factories.make_user("export-other")
        sujet = factories.make_writing_sujet(is_active=False)
        overrides = [
            WritingResponseOverride.objects.create(
                user=owner, sujet=sujet, version_key="model-1", body="My revised model",
            ),
            WritingResponseOverride.objects.create(
                user=owner, sujet=sujet, version_key="model-2", is_deleted=True,
            ),
        ]
        WritingResponseOverride.objects.create(
            user=other, sujet=sujet, version_key="model-1", body="Another learner's edit",
        )
        prompt = factories.make_response().prompts.get()
        note = Annotation.objects.create(
            user=owner, kind=AnnotationKind.NOTE, body="My note",
            source_prompt=prompt, completed_at=timezone.now(), study_later=True,
        )
        Annotation.objects.create(
            user=other, kind=AnnotationKind.NOTE, body="Another learner's note",
        )
        before_overrides = list(WritingResponseOverride.objects.order_by("pk").values())
        before_annotations = list(Annotation.objects.order_by("pk").values())
        self.client.force_login(owner)

        response = self.client.get(reverse("study:export_account"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"], 11)
        self.assertEqual(payload["writing_response_overrides"], [
            {
                "part": sujet.task.part.slug,
                "task": sujet.task.slug,
                "sujet": sujet.slug,
                "version_key": override.version_key,
                "body": override.body,
                "is_deleted": override.is_deleted,
                "updated_at": override.updated_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            }
            for override in overrides
        ])
        self.assertEqual(len(payload["annotations"]), 1)
        exported_note = payload["annotations"][0]
        self.assertEqual(exported_note["source_prompt_id"], prompt.pk)
        self.assertIsNotNone(exported_note["completed_at"])
        self.assertTrue(exported_note["study_later"])
        self.assertEqual(exported_note["id"], note.pk)
        self.assertEqual(
            list(WritingResponseOverride.objects.order_by("pk").values()), before_overrides,
        )
        self.assertEqual(
            list(Annotation.objects.order_by("pk").values()), before_annotations,
        )

    def test_inactive_account_recovery_does_not_rotate_pin_or_codes(self):
        user = factories.make_user("inactive-account")
        codes = generate_recovery_codes(user)
        user.is_active = False
        user.save(update_fields=["is_active"])
        original_password = user.password
        original_codes = list(AccountRecoveryCode.objects.filter(user=user).values())

        response = self.client.post(reverse("study:recover_account"), {
            "username": user.username,
            "recovery_code": codes[0],
            "new_pin": "654321",
            "new_pin_confirm": "654321",
        })

        self.assertContains(response, "Récupération impossible")
        self.assertNotIn("_auth_user_id", self.client.session)
        user.refresh_from_db()
        self.assertEqual(user.password, original_password)
        self.assertEqual(
            list(AccountRecoveryCode.objects.filter(user=user).values()), original_codes,
        )

    def test_registration_propagates_provisioning_integrity_errors_and_rolls_back(self):
        with patch(
            "study.views.account.provision_user_study_data",
            side_effect=IntegrityError("Study data constraint failed"),
        ):
            with self.assertRaisesMessage(IntegrityError, "Study data constraint failed"):
                self.client.post(reverse("study:register"), {
                    "username": "new-account", "pin": "123456", "pin_confirm": "123456",
                })
        self.assertFalse(get_user_model().objects.filter(username="new-account").exists())
        self.assertFalse(AccountRecoveryCode.objects.exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_registration_handles_a_username_claimed_after_form_validation(self):
        user = factories.make_user("claimed-account")
        with patch("study.forms.RegistrationForm.clean_username", return_value=user.username):
            response = self.client.post(reverse("study:register"), {
                "username": user.username, "pin": "654321", "pin_confirm": "654321",
            })
        self.assertContains(response, "déjà utilisé")
        self.assertEqual(get_user_model().objects.count(), 1)
        user.refresh_from_db()
        self.assertTrue(user.check_password("123456"))

    def test_failed_code_rotation_preserves_previous_codes(self):
        user = factories.make_user()
        generate_recovery_codes(user)
        previous = list(AccountRecoveryCode.objects.filter(user=user).values())
        with patch(
            "study.account_services.AccountRecoveryCode.objects.bulk_create",
            side_effect=IntegrityError("Recovery code collision"),
        ):
            with self.assertRaisesMessage(IntegrityError, "Recovery code collision"):
                generate_recovery_codes(user)
        self.assertEqual(
            list(AccountRecoveryCode.objects.filter(user=user).values()), previous,
        )


@skipUnlessDBFeature("has_select_for_update")
@tag("database-locking")
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RecoveryRotationLockTests(TransactionTestCase):
    def test_concurrent_rotations_leave_only_the_latest_code_set(self):
        user = factories.make_user()
        generate_recovery_codes(user)
        attempted, finished = Event(), Event()
        results, errors = [], []

        def observe_write(execute, sql, params, many, context):
            if "FOR UPDATE" in sql or sql.startswith("DELETE"):
                attempted.set()
            return execute(sql, params, many, context)

        def rotate():
            try:
                with connection.execute_wrapper(observe_write):
                    results.extend(generate_recovery_codes(user))
            except BaseException as exc:  # Propagate worker failures to the test runner.
                errors.append(exc)
            finally:
                connections.close_all()
                finished.set()

        worker = Thread(target=rotate)
        try:
            with transaction.atomic():
                first_codes = generate_recovery_codes(user)
                worker.start()
                self.assertTrue(attempted.wait(10), errors)
                self.assertFalse(finished.wait(0.2), errors)
        finally:
            if worker.ident is not None:
                worker.join(15)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        self.assertFalse(set(results) & set(first_codes))
        self.assertEqual(
            set(AccountRecoveryCode.objects.filter(user=user).values_list("token_digest", flat=True)),
            {_recovery_code_digest(code) for code in results},
        )
