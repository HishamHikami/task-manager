"""Fill an empty database with example data to try the app."""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker import services
from tracker.models import Holder, Task, Update, Workspace


class Command(BaseCommand):
    help = "Create example workspaces, people and tasks (only on an empty database)."

    def handle(self, *args, **options):
        if Workspace.objects.exists():
            raise CommandError("Database already has workspaces; refusing to add demo data.")
        today = timezone.localdate()
        now = timezone.now()

        company = Workspace.objects.create(name="Company", color="blue", order=0)
        org = Workspace.objects.create(name="Community Org", color="green", order=1)
        for ws in (company, org):
            ws.create_default_stages()

        def h(ws, name, kind):
            return Holder.objects.create(workspace=ws, name=name, kind=kind)

        fin, it, gm, proc = (h(company, "Finance", "department"), h(company, "IT", "department"),
                             h(company, "GM Office", "department"), h(company, "Procurement", "department"))
        events, treas, ali = (h(org, "Events Committee", "committee"), h(org, "Treasurer", "person"),
                              h(org, "Br. Ali", "person"))

        def stage(ws, name):
            return ws.stages.get(name=name)

        def task(ws, title, holder, stage_name, days_ago, **kw):
            t = Task.objects.create(workspace=ws, title=title, current_holder=holder,
                                    stage=stage(ws, stage_name), **kw)
            Task.objects.filter(pk=t.pk).update(created_at=now - timedelta(days=days_ago),
                                                holder_since=now - timedelta(days=days_ago))
            t.refresh_from_db()
            services.record_created(t)
            return t

        t1 = task(company, "Approve Q1 marketing budget", proc, "In progress", 9, priority=3,
                  due_date=today - timedelta(days=2), reference="PR-2291", my_role="assigned")
        services.hand_off(t1, fin, "Procurement finished quotations, sent to Finance.",
                          now - timedelta(days=5))
        Update.objects.create(task=t1, kind="email", source="Finance — Sara",
                              summary="Finance needs the third quotation before approving.",
                              body="Dear team,\nWe reviewed the two quotations. Please share the third one...",
                              occurred_at=now - timedelta(days=3))
        services.set_follow_up(t1, today, "Ask Sara if 3rd quotation arrived")

        task(company, "Laptop replacement for sales team", it, "Assigned", 4, my_role="following",
             follow_up_date=today + timedelta(days=2), follow_up_note="Check delivery date")
        t3 = task(company, "Sign vendor contract renewal", gm, "Waiting approval", 12, priority=4,
                  due_date=today + timedelta(days=1), my_role="following")
        Update.objects.create(task=t3, kind="meeting", source="Weekly management meeting",
                              summary="GM asked Legal to review clause 7 before signing.",
                              occurred_at=now - timedelta(days=1))

        t4 = task(org, "Ramadan iftar event planning", events, "In progress", 6, priority=3,
                  due_date=today + timedelta(days=20), my_role="executing")
        Update.objects.create(task=t4, kind="whatsapp", source="Events group",
                              summary="Venue confirmed; catering quotes pending.",
                              body="Venue is confirmed for the 14th. Waiting on 2 catering quotes.",
                              occurred_at=now - timedelta(hours=20))
        task(org, "Reimburse volunteer expenses", treas, "Assigned", 3, my_role="following",
             follow_up_date=today - timedelta(days=1), follow_up_note="Remind treasurer")
        t6 = task(org, "Print new members' cards", ali, "In progress", 15)
        services.change_stage(t6, stage(org, "Done"), "Cards delivered.")
        self.stdout.write(self.style.SUCCESS("Demo data created."))
