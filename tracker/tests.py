import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import Contact, Event, Holder, Task, Workspace


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

    def test_create_task(self):
        resp = self.client.post(
            reverse("task_create", args=[self.ws.pk]),
            {
                "title": "Renew trade license",
                "my_role": "following",
                "stage": self.ws.first_open_stage().pk,
                "current_holder": self.gm.pk,
                "priority": 3,
                "first_note": "Expires end of month",
            },
        )
        task = Task.objects.get(title="Renew trade license")
        self.assertRedirects(resp, task.get_absolute_url())
        self.assertEqual(task.current_holder, self.gm)
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
        self.assertContains(page, "★ Main")
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


class AddHolderFromTaskTests(BaseCase):
    def test_task_form_has_button_not_inline_fields(self):
        resp = self.client.get(reverse("task_create", args=[self.ws.pk]))
        self.assertNotContains(resp, 'name="new_holder"')
        self.assertContains(resp, "+ New department / person")
        self.assertContains(resp, "/holders/new/?next=%2Fworkspaces%2F")

    def test_person_returns_straight_to_task_form_preselected(self):
        back = reverse("task_create", args=[self.ws.pk])
        url = reverse("holder_create", args=[self.ws.pk]) + "?next=" + back
        resp = self.client.post(url, {"name": "Omar", "kind": "person", "active": "on"})
        omar = Holder.objects.get(name="Omar")
        self.assertRedirects(resp, f"{back}?holder={omar.pk}", fetch_redirect_response=False)
        page = self.client.get(f"{back}?holder={omar.pk}")
        self.assertContains(page, f'<option value="h{omar.pk}" selected>')

    def test_department_goes_via_people_page_then_back(self):
        back = reverse("task_create", args=[self.ws.pk])
        resp = self.client.post(reverse("holder_create", args=[self.ws.pk]) + "?next=" + back,
                                {"name": "Legal", "kind": "department", "active": "on"})
        legal = Holder.objects.get(name="Legal")
        people_page = f"{legal.get_absolute_url()}?next={back.replace('/', '%2F')}"
        self.assertRedirects(resp, people_page, fetch_redirect_response=False)
        # add a person, staying in the return flow
        resp = self.client.post(reverse("contact_create", args=[legal.pk]) + "?next=" + back,
                                {"name": "Khalid", "role": "Legal Manager", "active": "on"})
        self.assertRedirects(resp, people_page, fetch_redirect_response=False)
        page = self.client.get(people_page)
        self.assertContains(page, "Use whole Legal")
        khalid = Contact.objects.get(name="Khalid")
        self.assertContains(page, f"{back}?contact={khalid.pk}")
        self.assertContains(page, f"{back}?holder={legal.pk}")

    def test_handoff_returns_with_panel_open_and_holder_selected(self):
        task = self.make_task()
        page = self.client.get(f"{task.get_absolute_url()}?holder={self.gm.pk}")
        self.assertContains(page, '<details class="panel" open>')
        self.assertContains(page, f'<option value="h{self.gm.pk}" selected>')

    def test_external_next_is_ignored(self):
        resp = self.client.post(reverse("holder_create", args=[self.ws.pk]) + "?next=https://evil.example/",
                                {"name": "Omar", "kind": "person", "active": "on"})
        self.assertRedirects(resp, self.ws.get_absolute_url(), fetch_redirect_response=False)

    def test_holder_from_other_workspace_not_preselected(self):
        other = Workspace.objects.create(name="Org")
        stranger = Holder.objects.create(workspace=other, name="Stranger")
        page = self.client.get(reverse("task_create", args=[self.ws.pk]) + f"?holder={stranger.pk}")
        self.assertNotContains(page, "Stranger")


class CopyButtonTests(BaseCase):
    def test_copy_buttons_next_to_phone_and_email(self):
        self.finance.phone = "+966 11 222 3333"
        self.finance.email = "finance@example.com"
        self.finance.save()
        Contact.objects.create(holder=self.finance, name="Sara", role="Manager", email="sara@example.com")
        # Department page shows the department's own phone/email; the workspace list stays uncluttered.
        for url in [self.finance.get_absolute_url()]:
            page = self.client.get(url)
            self.assertContains(page, 'data-copy="+966 11 222 3333"')
            self.assertContains(page, 'data-copy="finance@example.com"')
        # The task page shows the person it's with (Sara), each with a copy button.
        self.assertContains(self.client.get(self.make_task().get_absolute_url()), 'data-copy="sara@example.com"')
        self.assertContains(self.client.get(self.finance.get_absolute_url()), 'data-copy="sara@example.com"')


class CurrentlyWithContactTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.finance.email = "finance-dept@example.com"
        self.finance.save()

    def test_shows_main_contacts_own_email_not_departments(self):
        Contact.objects.create(holder=self.finance, name="Sara", role="Finance Manager", is_primary=True,
                               email="sara@example.com")
        page = self.client.get(self.make_task().get_absolute_url())
        facts = page.content.decode().split('<dl class="facts">')[1].split("People at")[0]
        self.assertIn("sara@example.com", facts)
        self.assertIn("Sara · Finance Manager", facts)
        self.assertNotIn("finance-dept@example.com", facts)

    def test_falls_back_to_department_when_person_has_no_details(self):
        Contact.objects.create(holder=self.finance, name="Sara", is_primary=True)
        page = self.client.get(self.make_task().get_absolute_url())
        self.assertContains(page, "No phone/email saved for Sara")
        self.assertContains(page, 'data-copy="finance-dept@example.com"')

    def test_department_without_people_shows_department_details(self):
        page = self.client.get(self.make_task().get_absolute_url())
        self.assertContains(page, 'data-copy="finance-dept@example.com"')


class DoingItMyselfTests(BaseCase):
    def post_task(self, **extra):
        data = {"title": "Write the report", "my_role": "executing",
                "stage": self.ws.first_open_stage().pk, "priority": 2}
        data.update(extra)
        self.client.post(reverse("task_create", args=[self.ws.pk]), data)
        return Task.objects.get(title="Write the report")

    def test_doing_it_myself_clears_holder(self):
        task = self.post_task(current_holder=self.finance.pk)  # even if a holder was left selected
        self.assertIsNone(task.current_holder)
        self.assertTrue(task.with_me)
        page = self.client.get(task.get_absolute_url())
        self.assertContains(page, "I'm doing it")
        self.assertContains(page, "with <strong>me</strong>")

    def test_dashboard_shows_on_my_desk_first(self):
        self.make_task(title="With finance")
        self.post_task()
        page = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("On my desk", page)
        self.assertLess(page.index('<span class="group-title">On my desk'),
                        page.index('<span class="group-title">Finance'))

    def test_following_up_keeps_holder(self):
        task = self.post_task(my_role="following", current_holder=self.finance.pk)
        self.assertEqual(task.current_holder, self.finance)
        self.assertFalse(task.with_me)

    def test_handoff_from_me_shows_me_on_timeline(self):
        task = self.post_task()
        self.client.post(reverse("task_handoff", args=[task.pk]), {"to_holder": self.gm.pk})
        page = self.client.get(task.get_absolute_url())
        self.assertContains(page, 'Me <span class="arrow">→</span> <strong>GM Office</strong>')


class PersonIntoDepartmentTests(BaseCase):
    url = None

    def setUp(self):
        super().setUp()
        self.url = reverse("holder_create", args=[self.ws.pk])

    def test_person_with_department_is_added_to_its_people(self):
        resp = self.client.post(self.url, {"name": "Sara", "kind": "person", "department": self.finance.pk,
                                           "role": "Finance Manager", "is_primary": "on",
                                           "email": "sara@example.com", "active": "on"})
        self.assertRedirects(resp, self.finance.get_absolute_url(), fetch_redirect_response=False)
        self.assertFalse(Holder.objects.filter(name="Sara").exists())  # not a separate desk
        sara = self.finance.contacts.get(name="Sara")
        self.assertEqual((sara.role, sara.is_primary, sara.email), ("Finance Manager", True, "sara@example.com"))

    def test_person_without_department_stays_on_their_own(self):
        self.client.post(self.url, {"name": "Omar", "kind": "person", "active": "on"})
        self.assertTrue(Holder.objects.filter(name="Omar", kind="person").exists())

    def test_department_ignored_for_non_person_types(self):
        self.client.post(self.url, {"name": "Legal", "kind": "department", "department": self.finance.pk,
                                    "active": "on"})
        self.assertTrue(Holder.objects.filter(name="Legal", kind="department").exists())
        self.assertFalse(self.finance.contacts.exists())

    def test_only_departments_offered(self):
        Holder.objects.create(workspace=self.ws, name="Lone Person", kind="person")
        page = self.client.get(self.url).content.decode()
        dept_select = page.split('name="department"')[1].split("</select>")[0]
        self.assertIn("Finance", dept_select)
        self.assertNotIn("Lone Person", dept_select)

    def test_same_name_allowed_inside_department(self):
        Holder.objects.create(workspace=self.ws, name="Ali", kind="person")
        self.client.post(self.url, {"name": "Ali", "kind": "person", "department": self.gm.pk, "active": "on"})
        self.assertTrue(self.gm.contacts.filter(name="Ali").exists())

    def test_from_task_returns_straight_back_with_person_selected(self):
        back = reverse("task_create", args=[self.ws.pk])
        resp = self.client.post(self.url + "?next=" + back,
                                {"name": "Sara", "kind": "person", "department": self.finance.pk, "active": "on"})
        sara = self.finance.contacts.get(name="Sara")
        self.assertRedirects(resp, f"{back}?contact={sara.pk}", fetch_redirect_response=False)
        page = self.client.get(f"{back}?contact={sara.pk}")
        self.assertContains(page, f'<option value="c{sara.pk}" selected>')

    def test_edit_form_has_no_department_field(self):
        page = self.client.get(reverse("holder_edit", args=[self.finance.pk]))
        self.assertNotContains(page, 'name="department"')


class AssignToPersonTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.sara = Contact.objects.create(holder=self.finance, name="Sara", role="Finance Manager",
                                           is_primary=True, email="sara@example.com")
        self.ahmed = Contact.objects.create(holder=self.finance, name="Ahmed", role="Accountant",
                                            phone="+966 50 000 0000")

    def create(self, desk):
        self.client.post(reverse("task_create", args=[self.ws.pk]),
                         {"title": "Pay invoice", "my_role": "following", "priority": 2,
                          "stage": self.ws.first_open_stage().pk, "current_holder": desk})
        return Task.objects.get(title="Pay invoice")

    def test_picker_groups_people_under_departments(self):
        page = self.client.get(reverse("task_create", args=[self.ws.pk])).content.decode()
        block = page.split('<optgroup label="Finance">')[1].split("</optgroup>")[0]
        self.assertIn("Finance — whole department", block)
        self.assertIn(f'value="c{self.ahmed.pk}"', block)
        self.assertIn("Ahmed · Accountant", block)
        self.assertIn("Sara · Finance Manager ★", block)

    def test_assign_to_specific_person(self):
        task = self.create(f"c{self.ahmed.pk}")
        self.assertEqual((task.current_holder, task.current_contact), (self.finance, self.ahmed))
        self.assertEqual(task.desk_name, "Ahmed · Finance")
        page = self.client.get(task.get_absolute_url())
        self.assertContains(page, "Ahmed · Finance")
        self.assertContains(page, 'data-copy="+966 50 000 0000"')  # Ahmed's phone, not Sara's
        self.assertNotIn("sara@example.com", page.content.decode().split("People at")[0])

    def test_whole_department_shows_main_contact(self):
        task = self.create(f"h{self.finance.pk}")
        self.assertIsNone(task.current_contact)
        self.assertEqual(task.desk_name, "Finance (Sara)")

    def test_handoff_between_people_in_same_department(self):
        task = self.create(f"c{self.sara.pk}")
        self.client.post(reverse("task_handoff", args=[task.pk]), {"to_holder": f"c{self.ahmed.pk}"})
        task.refresh_from_db()
        self.assertEqual(task.current_contact, self.ahmed)
        entry = task.updates.get(kind="handoff")
        self.assertEqual((entry.from_desk, entry.to_desk), ("Sara · Finance", "Ahmed · Finance"))
        page = self.client.get(task.get_absolute_url())
        self.assertContains(page, 'Sara · Finance <span class="arrow">→</span> <strong>Ahmed · Finance</strong>')

    def test_current_person_not_offered_as_handoff_target(self):
        task = self.create(f"c{self.sara.pk}")
        page = self.client.get(task.get_absolute_url()).content.decode()
        handoff = page.split('name="to_holder"')[1].split("</select>")[0]
        self.assertNotIn(f'value="c{self.sara.pk}"', handoff)
        self.assertIn(f'value="c{self.ahmed.pk}"', handoff)
        self.assertIn(f'value="h{self.finance.pk}"', handoff)

    def test_dashboard_groups_by_person(self):
        self.create(f"c{self.ahmed.pk}")
        self.assertContains(self.client.get(reverse("dashboard")), "Ahmed · Finance")

    def test_person_from_other_workspace_rejected(self):
        other = Workspace.objects.create(name="Org")
        stranger = Contact.objects.create(holder=Holder.objects.create(workspace=other, name="X",
                                                                        kind="department"), name="Stranger")
        resp = self.client.post(reverse("task_create", args=[self.ws.pk]),
                                {"title": "Bad", "my_role": "following", "priority": 2,
                                 "stage": self.ws.first_open_stage().pk, "current_holder": f"c{stranger.pk}"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Task.objects.filter(title="Bad").exists())

    def test_inactive_person_not_offered(self):
        self.ahmed.active = False
        self.ahmed.save()
        page = self.client.get(reverse("task_create", args=[self.ws.pk]))
        self.assertNotContains(page, f'value="c{self.ahmed.pk}"')

    def test_deleting_person_falls_back_to_department(self):
        task = self.create(f"c{self.ahmed.pk}")
        self.ahmed.delete()
        task.refresh_from_db()
        self.assertEqual((task.current_holder, task.current_contact), (self.finance, None))


class EventTests(BaseCase):
    def post_event(self, **extra):
        start = timezone.localtime() + timedelta(days=3)
        data = {"title": "Annual community lecture", "kind": "lecture", "my_role": "speaker",
                "status": "invited", "start": start.strftime("%Y-%m-%dT%H:%M"),
                "end": (start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
                "location": "Main hall", "my_topic": "Leadership and service", "duration_minutes": 30}
        data.update(extra)
        return self.client.post(reverse("event_create", args=[self.ws.pk]), data)

    def test_create_event_as_speaker(self):
        Contact.objects.create(holder=self.gm, name="Dr. Faris", role="Director", is_primary=True)
        faris = Contact.objects.get(name="Dr. Faris")
        resp = self.post_event(organizer_desk=f"c{faris.pk}")
        event = Event.objects.get()
        self.assertRedirects(resp, event.get_absolute_url())
        self.assertEqual((event.my_role, event.organizer, event.organizer_contact), ("speaker", self.gm, faris))
        page = self.client.get(event.get_absolute_url())
        self.assertContains(page, "Speaker / Lecturer")
        self.assertContains(page, "Leadership and service")
        self.assertContains(page, "Dr. Faris · GM Office")

    def test_outside_organizer_text(self):
        self.post_event(organizer_other="City Cultural Club")
        event = Event.objects.get()
        self.assertEqual(event.organizer_name, "City Cultural Club")
        self.assertContains(self.client.get(event.get_absolute_url()), "City Cultural Club")

    def test_event_without_organizer_page_opens(self):
        self.post_event()
        self.assertEqual(self.client.get(Event.objects.get().get_absolute_url()).status_code, 200)

    def test_end_before_start_rejected(self):
        start = timezone.localtime() + timedelta(days=1)
        resp = self.post_event(start=start.strftime("%Y-%m-%dT%H:%M"),
                               end=(start - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Event.objects.exists())

    def test_nav_list_and_dashboard(self):
        self.post_event()
        self.assertContains(self.client.get(reverse("dashboard")), 'href="/events/"')
        self.assertContains(self.client.get(reverse("event_list")), "Annual community lecture")
        dash = self.client.get(reverse("dashboard"))
        self.assertContains(dash, "Coming up")
        self.assertContains(dash, '<span class="stat-n warn">1</span><span class="stat-l">Invites')
        self.assertContains(self.client.get(reverse("event_list") + "?show=invites"), "Annual community lecture")

    def test_status_change(self):
        self.post_event()
        event = Event.objects.get()
        self.client.post(reverse("event_status", args=[event.pk]), {"status": "confirmed"})
        event.refresh_from_db()
        self.assertEqual(event.status, "confirmed")

    def test_past_events_listed_separately(self):
        past = timezone.localtime() - timedelta(days=10)
        self.post_event(title="Old ceremony", start=past.strftime("%Y-%m-%dT%H:%M"),
                        end=(past + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))
        self.assertNotContains(self.client.get(reverse("event_list")), "Old ceremony")
        self.assertContains(self.client.get(reverse("event_list") + "?show=past"), "Old ceremony")

    def test_calendar_file(self):
        self.post_event(title="Talk, with commas; and semicolons")
        resp = self.client.get(reverse("event_ics", args=[Event.objects.get().pk]))
        self.assertEqual(resp["Content-Type"], "text/calendar; charset=utf-8")
        body = resp.content.decode()
        self.assertIn("BEGIN:VEVENT", body)
        self.assertIn("SUMMARY:Talk\\, with commas\; and semicolons", body)
        self.assertIn("My role: Speaker / Lecturer", body)
        self.assertIn("STATUS:TENTATIVE", body)


# --- AI & phone app -----------------------------------------------------------------

from types import SimpleNamespace
from unittest import mock

from . import ai
from .models import AIUsage, AppSettings, Update


class FakeAnthropic:
    """Stands in for anthropic.Anthropic: returns a canned parsed result."""

    result = None
    stop_reason = "end_turn"
    calls = []

    def __init__(self, **kwargs):
        self.messages = self

    def parse(self, **kwargs):
        FakeAnthropic.calls.append(kwargs)
        parsed = kwargs["output_format"](**FakeAnthropic.result)
        return SimpleNamespace(parsed_output=parsed, stop_reason=FakeAnthropic.stop_reason,
                               usage=SimpleNamespace(input_tokens=900, output_tokens=120))


def suggestion(**over):
    data = {"summary": "Finance approved the budget; needs GM signature.", "message_kind": "email",
            "sender": "Sara", "action": "new_task", "task_id": None, "new_task_title": "", "desk": None,
            "next_action": "", "due_date": None, "follow_up_date": None, "event_title": "",
            "event_start": None, "event_end": None, "event_location": "", "event_my_role": None,
            "event_kind": None}
    data.update(over)
    return data


class AIBase(BaseCase):
    def setUp(self):
        super().setUp()
        ai.save_api_key("sk-ant-test-0000000000000000000000000000abcd")
        FakeAnthropic.calls = []
        FakeAnthropic.stop_reason = "end_turn"
        patcher = mock.patch("anthropic.Anthropic", FakeAnthropic)
        patcher.start()
        self.addCleanup(patcher.stop)


class AIKeyTests(BaseCase):
    def test_key_encrypted_and_only_hint_shown(self):
        raw = "sk-ant-test-1111111111111111111111111111wxyz"
        resp = self.client.post(reverse("settings"), {"api_key": raw, "ai_model": "claude-haiku-5-5"})
        self.assertRedirects(resp, reverse("settings"))
        s = AppSettings.load()
        self.assertNotIn(raw, s.anthropic_key_encrypted)
        self.assertEqual(ai.decrypt_key(s.anthropic_key_encrypted), raw)
        page = self.client.get(reverse("settings")).content.decode()
        self.assertIn("…wxyz", page)
        self.assertNotIn(raw, page)

    def test_invalid_key_rejected(self):
        self.client.post(reverse("settings"), {"api_key": "hello", "ai_model": "claude-haiku-5-5"})
        self.assertFalse(AppSettings.load().has_api_key)

    def test_remove_key(self):
        ai.save_api_key("sk-ant-test-2222222222222222222222222222abcd")
        self.client.post(reverse("settings"), {"remove_key": "on", "ai_model": "claude-haiku-5-5"})
        self.assertFalse(AppSettings.load().has_api_key)


class CleanTextTests(TestCase):
    def test_strips_quoted_reply_and_disclaimer(self):
        text = ("Dear team,\nThe quotation is approved, please proceed by Thursday.\nRegards,\nSara\n"
                "Sent from my iPhone\n\nOn Mon, 23 Nov 2026 at 10:00, Ali <ali@x.com> wrote:\n> old stuff\n> more\n")
        cleaned, short = ai.clean_text(text)
        self.assertIn("approved", cleaned)
        self.assertNotIn("old stuff", cleaned)
        self.assertNotIn("Sent from my", cleaned)
        self.assertFalse(short)
        cleaned, _ = ai.clean_text("Hello there, the report is ready for review today.\n\n"
                                   "DISCLAIMER: This email is confidential ...")
        self.assertNotIn("DISCLAIMER", cleaned)

    def test_long_text_shortened(self):
        _, short = ai.clean_text("word " * 5000)
        self.assertTrue(short)


class CaptureTests(AIBase):
    def test_share_target_prefills_text(self):
        page = self.client.get(reverse("capture"), {"title": "Fwd: Budget", "text": "Please approve"})
        self.assertContains(page, "Fwd: Budget\nPlease approve")

    def test_ai_suggestion_prefills_review(self):
        task = self.make_task()
        sara = Contact.objects.create(holder=self.gm, name="Sara", role="Secretary")
        FakeAnthropic.result = suggestion(action="update_task", task_id=task.pk, desk=f"c{sara.pk}",
                                          follow_up_date="2026-12-01", next_action="Check signature")
        page = self.client.post(reverse("capture"), {"text": "Budget approved, sent to GM office",
                                                      "workspace": self.ws.pk, "use_ai": "1"})
        self.assertContains(page, "Suggested by AI")
        self.assertContains(page, "Finance approved the budget")
        self.assertContains(page, f'<option value="c{sara.pk}" selected>')
        call = FakeAnthropic.calls[0]
        self.assertEqual(call["model"], "claude-haiku-5-5")
        self.assertEqual(call["output_config"], {"effort": "low"})
        self.assertIn(f"c{sara.pk}: Sara - Secretary (GM Office)", call["messages"][0]["content"])
        self.assertEqual(AIUsage.objects.get().input_tokens, 900)

    def test_same_text_reuses_result(self):
        FakeAnthropic.result = suggestion()
        for _ in range(2):
            self.client.post(reverse("capture"), {"text": "Same message", "workspace": self.ws.pk, "use_ai": "1"})
        self.assertEqual(len(FakeAnthropic.calls), 1)

    def test_made_up_ids_are_dropped(self):
        FakeAnthropic.result = suggestion(action="update_task", task_id=9999, desk="c9999",
                                          due_date="not a date")
        result, _ = ai.suggest_for_capture(self.ws, "Something")
        self.assertEqual((result["task_id"], result["desk"], result["due_date"], result["action"]),
                         (None, None, None, "new_task"))

    def test_ai_off_for_workspace_sends_nothing(self):
        self.ws.ai_enabled = False
        self.ws.save()
        page = self.client.post(reverse("capture"), {"text": "Secret", "workspace": self.ws.pk, "use_ai": "1"},
                                follow=True)
        self.assertContains(page, "AI is turned off for Company")
        self.assertEqual(FakeAnthropic.calls, [])

    def test_refusal_reported(self):
        FakeAnthropic.result = suggestion()
        FakeAnthropic.stop_reason = "refusal"
        with self.assertRaises(ai.AIError):
            ai.suggest_for_capture(self.ws, "Text")

    def test_save_update_with_handoff_and_follow_up(self):
        task = self.make_task()
        sara = Contact.objects.create(holder=self.gm, name="Sara")
        resp = self.client.post(reverse("capture_save"), {
            "workspace": self.ws.pk, "body": "Full email text", "summary": "Approved; with GM",
            "kind": "email", "source": "Sara", "action": "update_task", "task": task.pk,
            "desk": f"c{sara.pk}", "handoff": "on", "next_action": "Ask about signature",
            "follow_up_date": "2026-12-01"})
        self.assertRedirects(resp, task.get_absolute_url())
        task.refresh_from_db()
        self.assertEqual((task.current_holder, task.current_contact), (self.gm, sara))
        self.assertEqual(str(task.follow_up_date), "2026-12-01")
        u = task.updates.get(kind="email")
        self.assertEqual((u.body, u.summary, u.source), ("Full email text", "Approved; with GM", "Sara"))

    def test_save_new_task_without_ai(self):
        page = self.client.post(reverse("capture"), {"text": "Please renew the license", "workspace": self.ws.pk,
                                                      "manual": "1"})
        self.assertContains(page, "Check and save")
        self.assertEqual(FakeAnthropic.calls, [])
        self.client.post(reverse("capture_save"), {
            "workspace": self.ws.pk, "body": "Please renew the license", "kind": "whatsapp",
            "action": "new_task", "new_task_title": "Renew license", "my_role": "executing"})
        task = Task.objects.get(title="Renew license")
        self.assertTrue(task.with_me)
        self.assertEqual(task.updates.get(kind="whatsapp").body, "Please renew the license")

    def test_save_as_event(self):
        resp = self.client.post(reverse("capture_save"), {
            "workspace": self.ws.pk, "body": "You are invited to speak at our forum", "summary": "Invite to speak",
            "kind": "email", "source": "City Club", "action": "new_event", "event_title": "Youth forum",
            "event_kind": "conference", "event_my_role": "speaker", "event_start": "2026-12-10T18:00",
            "event_location": "Hall A"})
        event = Event.objects.get()
        self.assertRedirects(resp, event.get_absolute_url())
        self.assertEqual((event.status, event.my_role, event.organizer_name), ("invited", "speaker", "City Club"))

    def test_review_requires_task_for_update(self):
        resp = self.client.post(reverse("capture_save"), {
            "workspace": self.ws.pk, "body": "x", "kind": "note", "action": "update_task"})
        self.assertEqual(resp.status_code, 400)

    def test_summarize_existing_update(self):
        task = self.make_task()
        u = Update.objects.create(task=task, kind="email", body="Long email about the budget")
        FakeAnthropic.result = {"summary": "Budget approved."}
        page = self.client.get(task.get_absolute_url())
        self.assertContains(page, "✨ Summarize")
        self.client.post(reverse("update_summarize", args=[u.pk]))
        u.refresh_from_db()
        self.assertEqual(u.summary, "Budget approved.")

    def test_usage_estimate(self):
        AIUsage.objects.create(purpose="capture", model="claude-haiku-5-5", input_tokens=1_000_000,
                               output_tokens=100_000)
        self.assertAlmostEqual(ai.usage_this_month()["cost"], 0.15)


class PWATests(TestCase):
    def test_manifest_and_share_target_public(self):
        resp = self.client.get("/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/manifest+json")
        data = resp.json()
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["share_target"]["action"], "/capture/")
        self.assertEqual({i["sizes"] for i in data["icons"]}, {"192x192", "512x512"})

    def test_service_worker_and_offline_public(self):
        sw = self.client.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertEqual(sw["Service-Worker-Allowed"], "/")
        self.assertEqual(self.client.get("/offline/").status_code, 200)

    def test_share_requires_login_then_returns(self):
        resp = self.client.get("/capture/?text=hello")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/?next=/capture/%3Ftext%3Dhello", resp["Location"])


class AssetVersionTests(BaseCase):
    def test_static_urls_are_versioned(self):
        from django.conf import settings
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, f"app.css?v={settings.ASSET_VERSION}")
        self.assertContains(page, f"app.js?v={settings.ASSET_VERSION}")
        self.client.logout()
        self.assertContains(self.client.get(reverse("login")), f"app.css?v={settings.ASSET_VERSION}")


class ChatCaptureTests(AIBase):
    HX = {"HTTP_HX_REQUEST": "true"}

    def test_page_is_chat(self):
        page = self.client.get(reverse("capture"))
        self.assertContains(page, 'class="composer"')
        self.assertContains(page, 'name="use_ai"')
        self.assertContains(page, "Paste or share a message")

    def test_shared_text_goes_into_composer(self):
        page = self.client.get(reverse("capture"), {"text": "Meeting moved to Monday"})
        self.assertContains(page, ">Meeting moved to Monday</textarea>")

    def test_send_returns_two_bubbles_only(self):
        FakeAnthropic.result = suggestion(new_task_title="Approve budget")
        resp = self.client.post(reverse("capture"), {"text": "Budget needs approval", "workspace": self.ws.pk,
                                                      "use_ai": "1"}, **self.HX)
        html = resp.content.decode()
        self.assertNotIn("<html", html)
        self.assertIn('class="msg me"', html)
        self.assertIn('class="msg ai"', html)
        self.assertIn("Finance approved the budget", html)

    def test_two_replies_have_distinct_ids(self):
        FakeAnthropic.result = suggestion()
        a = self.client.post(reverse("capture"), {"text": "One", "workspace": self.ws.pk}, **self.HX).content.decode()
        b = self.client.post(reverse("capture"), {"text": "Two", "workspace": self.ws.pk}, **self.HX).content.decode()
        ida = re.search(r'id="(r[0-9a-f]+)_summary"', a).group(1)
        idb = re.search(r'id="(r[0-9a-f]+)_summary"', b).group(1)
        self.assertNotEqual(ida, idb)

    def test_save_in_chat_returns_saved_bubble(self):
        task = self.make_task()
        resp = self.client.post(reverse("capture_save"), {
            "workspace": self.ws.pk, "uid": "abc123", "body": "Approved", "kind": "whatsapp",
            "action": "update_task", "task": task.pk, "follow_up_date": "2026-12-01"}, **self.HX)
        html = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Added to the timeline of", html)
        self.assertIn(task.get_absolute_url(), html)
        self.assertIn("follow up Tue 01 Dec", html)

    def test_invalid_save_in_chat_rerenders_bubble(self):
        resp = self.client.post(reverse("capture_save"), {
            "workspace": self.ws.pk, "uid": "abc123", "body": "x", "kind": "note", "action": "update_task"}, **self.HX)
        self.assertEqual(resp.status_code, 200)  # htmx only swaps 2xx
        self.assertContains(resp, "Choose the task this belongs to.")
        self.assertContains(resp, 'id="rabc123_task"')

    def test_ai_error_shown_in_bubble(self):
        AppSettings.objects.update(anthropic_key_encrypted="")
        resp = self.client.post(reverse("capture"), {"text": "Hi", "workspace": self.ws.pk, "use_ai": "1"}, **self.HX)
        self.assertContains(resp, "No AI key yet")
        self.assertContains(resp, "You can still file it yourself")
