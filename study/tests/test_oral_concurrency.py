from threading import Event, Thread, current_thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections
from django.db.models import QuerySet
from django.test import Client, TransactionTestCase, skipUnlessDBFeature, tag
from django.urls import reverse

from study.models import OralStateSnapshot, PersonalResponse, Response
from study.oral_history import save_personal

from . import factories


@skipUnlessDBFeature("has_select_for_update")
@tag("database-locking")
class OralResponseConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.response = factories.make_response()

    def while_creating_first_response(self, contender):
        first_read, attempted, second_read, release = Event(), Event(), Event(), Event()
        contender_done = Event()
        failures = []
        original_first = QuerySet.first
        original_lock = QuerySet.select_for_update

        def observed_lock(queryset, *args, **kwargs):
            if current_thread().name == "oral-contender" and queryset.model in {
                get_user_model(), Response, PersonalResponse,
            }:
                attempted.set()
            return original_lock(queryset, *args, **kwargs)

        def observed_first(queryset):
            result = original_first(queryset)
            if queryset.model == PersonalResponse:
                if current_thread().name == "oral-first" and result is None:
                    first_read.set()
                    if not release.wait(15):
                        raise TimeoutError("First oral response save was not released")
                elif current_thread().name == "oral-contender":
                    attempted.set()
                    second_read.set()
            return result

        def run(operation):
            try:
                operation()
                if current_thread().name == "oral-contender":
                    contender_done.set()
            except BaseException as exc:  # Propagate worker failures to the test.
                failures.append(exc)
            finally:
                connections.close_all()

        first = Thread(
            target=run,
            args=(lambda: save_personal(
                self.response, self.user, {"position": "First answer"},
            ),),
            name="oral-first",
        )
        second = Thread(target=run, args=(contender,), name="oral-contender")
        with (
            patch.object(QuerySet, "first", observed_first),
            patch.object(QuerySet, "select_for_update", observed_lock),
        ):
            first.start()
            try:
                self.assertTrue(first_read.wait(15), failures)
                second.start()
                self.assertTrue(attempted.wait(15), failures)
                self.assertFalse(second_read.wait(0.2))
                self.assertFalse(contender_done.is_set())
            finally:
                release.set()
                first.join(20)
                if second.ident is not None:
                    second.join(20)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])

    def test_simultaneous_first_saves_preserve_the_previous_answer(self):
        self.while_creating_first_response(
            lambda: save_personal(self.response, self.user, {"position": "Second answer"}),
        )
        personal = PersonalResponse.objects.get(user=self.user, response=self.response)
        self.assertEqual(personal.position, "Second answer")
        snapshot = OralStateSnapshot.objects.get(kind="personal", source_id=personal.pk)
        self.assertEqual(snapshot.payload["fields"]["position"], "First answer")

    def test_account_deletion_waits_for_first_save_without_lock_inversion(self):
        client = Client()
        client.force_login(self.user)
        results = []
        self.while_creating_first_response(
            lambda: results.append(client.post(reverse("study:delete_account"), {
                "current_pin": "123456",
                "username_confirmation": self.user.username,
            }).status_code),
        )
        self.assertEqual(results, [302])
        self.assertFalse(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertFalse(PersonalResponse.objects.exists())

    def test_reset_waits_for_first_save_and_preserves_its_answer(self):
        client = Client()
        client.force_login(self.user)
        url = reverse(
            "study:edit_response",
            args=["eo", "tache-3", self.response.canonical_prompt.pk],
        )
        results = []
        self.while_creating_first_response(
            lambda: results.append(client.post(url, {"action": "reset"}).status_code),
        )
        self.assertEqual(results, [302])
        personal = PersonalResponse.objects.get(user=self.user, response=self.response)
        self.assertFalse(personal.is_active)
        self.assertEqual(personal.position, "First answer")
        snapshot = OralStateSnapshot.objects.get(kind="personal", source_id=personal.pk)
        self.assertEqual(snapshot.payload["fields"]["position"], "First answer")
