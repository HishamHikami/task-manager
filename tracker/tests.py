from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Contact, Holder, Task, Workspace


class BaseCase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("owner", password="a-long-test-password")
        self.client.force_login(self.user)
        self.ws = Workspace.objects.create(name="Company")
        self.ws.create_default_stages()
        self.finance = Holder.objects.create(workspace=self.ws, name="Finance", kind="department")
        self.gm = Holder.objects.create(workspace=self.ws, name="GM Office", kind="department")

    def make_task(self, **kw):
        defaults = dict(workspace=self.ws, title="Approve budget", stage=self.ws.first_open_stage(),
                        current_holder=self.finance)
        defaults.update(kw)
        task = Task.objects.create(**defaults)
        services.record_created(task)
        return task


class ServiceTests(BaseCase):
    def test_handoff_records_history(self):
        task = self.make_task()
        services.hand_off(task, self.gm, "Sent for signature")
        task.refresh_from_db()
        self.assertEqual(task.current_holder, self.gm)
        entry = task.updates.get(kind="handoff")
        self.assertEqual(entry.from_holder, self.finance)
        self.assertEqual(entry.to_holder, self.gm)

    def test_closing_stage_sets_closed_at_and_reopening_clears_it(self):
        task = self.make_task()
        done = self.ws.stages.get(name="Done")
        services.change_stage(task, done)
        self.assertIsNotNone(task.closed_at)
        self.assertIn(task, Task.objects.closed())
        services.change_stage(task, self.ws.first_open_stage())
        self.assertIsNone(task.closed_at)
        self.assertIn(task, Task.objects.open())

    def test_overdue_and_follow_up_flags(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        task = self.make_task(due_date=yesterday, follow_up_date=yesterday)
        self.assertTrue(task.is_overdue)
        self.assertTrue(task.follow_up_due)


class ViewTests(BaseCase):
    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_dashboard_groups_by_holder(self):
        self.make_task(title="Task A")
        self.make_task(title="Task B", current_holder=self.gm)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "Task A")
        self.assertContains(resp, "GM Office")

    def test_create_task_with_new_holder(self):
        resp = self.client.post(
            reverse("task_create", args=[self.ws.pk]),
            {
                "title": "Renew trade license",
                "my_role": "following",
                "stage": self.ws.first_open_stage().pk,
                "new_holder": "PRO Services",
                "new_holder_kind": "department",
                "priority": 3,
                "first_note": "Expires end of month",
            },
        )
        task = Task.objects.get(title="Renew trade license")
        self.assertRedirects(resp, task.get_absolute_url())
        self.assertEqual(task.current_holder.name, "PRO Services")
        self.assertEqual(task.updates.get(kind="created").body, "Expires end of month")

    def test_handoff_view_with_follow_up(self):
        task = self.make_task()
        date = timezone.localdate() + timedelta(days=3)
        self.client.post(reverse("task_handoff", args=[task.pk]),
                         {"to_holder": self.gm.pk, "note": "For approval", "follow_up_date": date.isoformat()})
        task.refresh_from_db()
        self.assertEqual(task.current_holder, self.gm)
        self.assertEqual(task.follow_up_date, date)

    def test_handoff_requires_target(self):
        task = self.make_task()
        resp = self.client.post(reverse("task_handoff", args=[task.pk]), {"note": "x"})
        self.assertEqual(resp.status_code, 400)

    def test_add_update_and_search(self):
        task = self.make_task()
        self.client.post(reverse("task_add_update", args=[task.pk]),
                         {"kind": "email", "source": "Ahmed", "body": "Invoice 4471 is approved",
                          "occurred_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M")})
        self.assertEqual(task.updates.filter(kind="email").count(), 1)
        resp = self.client.get(reverse("task_list"), {"q": "4471"})
        self.assertContains(resp, "Approve budget")

    def test_holder_from_other_workspace_rejected(self):
        other = Workspace.objects.create(name="Org")
        stranger = Holder.objects.create(workspace=other, name="Stranger")
        task = self.make_task()
        resp = self.client.post(reverse("task_handoff", args=[task.pk]), {"to_holder": stranger.pk})
        self.assertEqual(resp.status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.current_holder, self.finance)


@override_settings(LOGIN_MAX_ATTEMPTS=2)
class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        get_user_model().objects.create_user("owner", password="a-long-test-password")

    def test_lockout_after_failures(self):
        url = reverse("login")
        for _ in range(2):
            self.client.post(url, {"username": "owner", "password": "wrong"})
        resp = self.client.post(url, {"username": "owner", "password": "a-long-test-password"})
        self.assertEqual(resp.status_code, 429)


class AdminLoginTests(TestCase):
    def test_admin_login_goes_through_throttled_login(self):
        resp = self.client.get("/admin/login/?next=/admin/")
        self.assertRedirects(resp, "/login/?next=%2Fadmin%2F", fetch_redirect_response=False)

    def test_admin_index_redirects_anonymous_to_login(self):
        resp = self.client.get("/admin/", follow=True)
        self.assertEqual(resp.request["PATH_INFO"], "/login/")


class PeopleTests(BaseCase):
    def test_display_name_uses_main_contact_for_groups_only(self):
        Contact.objects.create(holder=self.finance, name="Ahmed", role="Accountant")
        Contact.objects.create(holder=self.finance, name="Sara", role="Manager", is_primary=True)
        self.assertEqual(Holder.objects.get(pk=self.finance.pk).display_name, "Finance (Sara)")
        person = Holder.objects.create(workspace=self.ws, name="Omar", kind="person")
        self.assertEqual(person.display_name, "Omar")

    def test_only_one_main_contact(self):
        a = Contact.objects.create(holder=self.finance, name="Sara", is_primary=True)
        Contact.objects.create(holder=self.finance, name="Ahmed", is_primary=True)
        a.refresh_from_db()
        self.assertFalse(a.is_primary)
        self.assertEqual(self.finance.contacts.filter(is_primary=True).count(), 1)

    def test_inactive_people_are_not_main_contact(self):
        Contact.objects.create(holder=self.finance, name="Old Manager", is_primary=True, active=False)
        Contact.objects.create(holder=self.finance, name="New Manager")
        self.assertEqual(Holder.objects.get(pk=self.finance.pk).display_name, "Finance (New Manager)")

    def test_new_holder_with_main_contact_from_handoff(self):
        task = self.make_task()
        self.client.post(reverse("task_handoff", args=[task.pk]),
                         {"new_holder": "Legal", "new_holder_kind": "department",
                          "new_holder_contact_person": "Mr. Khalid", "new_holder_contact_role": "Legal Manager"})
        task.refresh_from_db()
        self.assertEqual(task.current_holder.name, "Legal")
        c = task.current_holder.contacts.get()
        self.assertEqual((c.name, c.role, c.is_primary), ("Mr. Khalid", "Legal Manager", True))
        resp = self.client.get(task.get_absolute_url())
        self.assertContains(resp, "Legal (Mr. Khalid)")
        self.assertContains(resp, "Legal Manager")

    def test_add_edit_remove_people(self):
        resp = self.client.post(reverse("contact_create", args=[self.finance.pk]),
                                {"name": "Sara", "role": "Finance Manager", "is_primary": "on",
                                 "phone": "+966 11 222 3333", "active": "on"})
        self.assertRedirects(resp, self.finance.get_absolute_url())
        self.client.post(reverse("contact_create", args=[self.finance.pk]),
                         {"name": "Ahmed", "role": "Accountant", "email": "ahmed@example.com", "active": "on"})
        page = self.client.get(self.finance.get_absolute_url())
        self.assertContains(page, "Finance Manager")
        self.assertContains(page, "Accountant")
        self.assertContains(page, "★ Main contact")
        ahmed = Contact.objects.get(name="Ahmed")
        self.client.post(reverse("contact_edit", args=[ahmed.pk]),
                         {"name": "Ahmed", "role": "Senior Accountant", "active": "on"})
        ahmed.refresh_from_db()
        self.assertEqual(ahmed.role, "Senior Accountant")
        self.client.post(reverse("contact_delete", args=[ahmed.pk]))
        self.assertFalse(Contact.objects.filter(pk=ahmed.pk).exists())

    def test_new_group_holder_goes_to_people_page(self):
        resp = self.client.post(reverse("holder_create", args=[self.ws.pk]),
                                {"name": "HR", "kind": "department", "active": "on"})
        self.assertRedirects(resp, Holder.objects.get(name="HR").get_absolute_url())


class PhoneEmailTests(BaseCase):
    def post_holder(self, **data):
        base = {"name": "Legal", "kind": "department", "active": "on"}
        base.update(data)
        return self.client.post(reverse("holder_create", args=[self.ws.pk]), base)

    def test_saves_phone_and_email_separately(self):
        self.post_holder(phone="+966  50 123 4567", email="khalid@example.com")
        h = Holder.objects.get(name="Legal")
        self.assertEqual(h.phone, "+966 50 123 4567")
        self.assertEqual(h.email, "khalid@example.com")
        self.assertEqual(h.phone_link, "+966501234567")

    def test_extension_allowed(self):
        self.post_holder(phone="ext 214")
        self.assertEqual(Holder.objects.get(name="Legal").phone, "ext 214")

    def test_invalid_values_rejected(self):
        resp = self.post_holder(phone="call Sara", email="not-an-email")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Holder.objects.filter(name="Legal").exists())
        self.assertContains(resp, "Enter a valid email address.")

    def test_task_page_shows_tap_to_call_and_email(self):
        self.finance.phone = "+966 11 222 3333"
        self.finance.email = "finance@example.com"
        self.finance.save()
        resp = self.client.get(self.make_task().get_absolute_url())
        self.assertContains(resp, 'href="tel:+966112223333"')
        self.assertContains(resp, 'href="mailto:finance@example.com"')


class WorkspaceCountTests(BaseCase):
    def test_open_count_not_inflated_by_holders(self):
        self.make_task(title="One")
        self.make_task(title="Two")
        resp = self.client.get(reverse("workspace_list"))
        self.assertContains(resp, "2 open · 2 departments/people")
