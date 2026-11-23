from django import forms
from django.utils import timezone

from .models import AppSettings, Contact, Event, Holder, Stage, Task, Update, Workspace


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M", **kwargs)


class WorkspaceForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ["name", "description", "color", "ai_enabled", "order", "archived"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class StageForm(forms.ModelForm):
    class Meta:
        model = Stage
        fields = ["name", "order", "is_closed"]

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace or self.instance.workspace

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Stage.objects.filter(workspace=self.workspace, name__iexact=name).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This workspace already has a stage with that name.")
        return name


class HolderChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.display_name


class DeskChoiceField(forms.ChoiceField):
    """Pick whose desk a task is on: a whole department, a specific person inside it,
    or an individual. Values are "h<holder id>" or "c<contact id>"; cleans to
    a (holder, contact) pair, where contact may be None."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("choices", [])
        super().__init__(*args, **kwargs)
        self.workspace = None

    def set_workspace(self, workspace, exclude=None):
        self.workspace = workspace
        holders = list(workspace.holders.filter(active=True).prefetch_related("contacts"))
        choices = [("", "---------")]
        individuals = []
        for h in holders:
            if h.is_group:
                options = [(f"h{h.pk}", f"{h.name} — whole {h.get_kind_display().lower()}")]
                for c in h.contacts.all():
                    if c.active:
                        label = c.name + (f" · {c.role}" if c.role else "") + (" ★" if c.is_primary else "")
                        options.append((f"c{c.pk}", label))
                options = [o for o in options if o[0] != exclude]
                if options:
                    choices.append((h.name, options))
            elif f"h{h.pk}" != exclude:
                individuals.append((f"h{h.pk}", h.name))
        if individuals:
            choices.append(("Individuals", individuals))
        self.choices = choices

    def to_python(self, value):
        value = super().to_python(value)
        return f"h{value}" if value.isdigit() else value  # plain holder id still accepted

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return (None, None)
        pk = int(value[1:])
        if value[0] == "c":
            contact = Contact.objects.select_related("holder").get(pk=pk, holder__workspace=self.workspace)
            return (contact.holder, contact)
        return (self.workspace.holders.get(pk=pk), None)


def desk_value(holder=None, contact=None):
    if contact:
        return f"c{contact.pk}"
    return f"h{holder.pk}" if holder else ""


class HolderForm(forms.ModelForm):
    class Meta:
        model = Holder
        fields = ["name", "kind", "phone", "email", "notes", "active"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "inputmode": "tel"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    # Only when adding a new Person: optionally put them inside a department.
    department = HolderChoiceField(
        queryset=Holder.objects.none(),
        required=False,
        label="Department (optional)",
        help_text="Pick one to add this person to that department's people list. "
                  "Leave empty for someone who works on their own.",
    )
    role = forms.CharField(max_length=120, required=False, help_text="e.g. Manager, Secretary, Accountant.")
    is_primary = forms.BooleanField(
        label="Main contact", required=False, help_text="The person you usually deal with in that department."
    )
    field_order = ["name", "kind", "department", "role", "is_primary", "phone", "email", "notes", "active"]

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace or self.instance.workspace
        if self.instance.pk:
            for name in ["department", "role", "is_primary"]:
                self.fields.pop(name)
        else:
            self.fields["department"].queryset = (
                self.workspace.holders.filter(active=True, kind__in=Holder.GROUP_KINDS)
                .prefetch_related("contacts")
            )
            self.fields["department"].label_from_instance = lambda h: h.name

    def clean_phone(self):
        return " ".join(self.cleaned_data["phone"].split())

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean(self):
        data = super().clean()
        if data.get("kind") != "person":
            data["department"] = None
        if data.get("department"):
            return data  # becomes a person in that department, not a separate desk
        name = data.get("name")
        if name and Holder.objects.filter(workspace=self.workspace, name__iexact=name).exclude(
            pk=self.instance.pk
        ).exists():
            self.add_error("name", "This workspace already has someone with that name.")
        return data

    def save_into_department(self):
        """Save as a person inside the chosen department. Returns the Contact."""
        d = self.cleaned_data
        return Contact.objects.create(
            holder=d["department"], name=d["name"], role=d.get("role", "").strip(),
            is_primary=d.get("is_primary", False), phone=d.get("phone", ""), email=d.get("email", ""),
            notes=d.get("notes", ""), active=d.get("active", True),
        )


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ["name", "role", "is_primary", "phone", "email", "notes", "active"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "inputmode": "tel"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def clean_phone(self):
        return " ".join(self.cleaned_data["phone"].split())


class TaskForm(forms.ModelForm):
    current_holder = DeskChoiceField(
        label="Currently with", required=False,
        help_text="A department, or the specific person in it who has the task.",
    )
    first_note = forms.CharField(
        label="Background / first note",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional. Saved as the first entry on the timeline.",
    )

    class Meta:
        model = Task
        fields = [
            "title",
            "description",
            "my_role",
            "stage",
            "priority",
            "due_date",
            "follow_up_date",
            "follow_up_note",
            "reference",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "due_date": DateInput(),
            "follow_up_date": DateInput(),
        }

    field_order = [
        "title", "description", "my_role", "stage", "current_holder", "priority", "due_date",
        "follow_up_date", "follow_up_note", "reference", "first_note",
    ]

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["stage"].queryset = workspace.stages.all()
        self.fields["current_holder"].set_workspace(workspace)
        if not self.instance.pk:
            self.fields["stage"].initial = workspace.first_open_stage()
        else:
            # Holder and stage changes on an existing task go through hand-off /
            # stage forms so they are recorded on the timeline.
            for name in ["stage", "current_holder", "first_note"]:
                self.fields.pop(name)

    def clean(self):
        data = super().clean()
        if data.get("my_role") == "executing" and "current_holder" in self.fields:
            data["current_holder"] = (None, None)  # it's on my own desk
        return data

    def save(self, commit=True):
        task = super().save(commit=False)
        if "current_holder" in self.fields:
            task.current_holder, task.current_contact = self.cleaned_data.get("current_holder") or (None, None)
        if commit:
            task.save()
        return task


class UpdateForm(forms.ModelForm):
    class Meta:
        model = Update
        fields = ["kind", "source", "body", "summary", "occurred_at"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 5, "placeholder": "Paste the email, WhatsApp message or minutes here"}),
            "summary": forms.Textarea(attrs={"rows": 2}),
            "occurred_at": DateTimeInput(),
        }
        labels = {"kind": "Type", "body": "Text", "occurred_at": "When"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [c for c in Update.KIND_CHOICES if c[0] in Update.MANUAL_KINDS]
        self.fields["occurred_at"].initial = timezone.localtime().replace(second=0, microsecond=0)

    def clean(self):
        data = super().clean()
        if not (data.get("body") or "").strip() and not (data.get("summary") or "").strip():
            raise forms.ValidationError("Add some text or a summary.")
        return data


class HandoffForm(forms.Form):
    to_holder = DeskChoiceField(
        label="Hand to", error_messages={"required": "Choose who the task goes to."},
        help_text="A department, or the specific person in it.",
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    occurred_at = forms.DateTimeField(label="When", widget=DateTimeInput(), required=False)
    follow_up_date = forms.DateField(label="Follow up on", widget=DateInput(), required=False)

    def __init__(self, *args, task, **kwargs):
        super().__init__(*args, **kwargs)
        self.task = task
        self.fields["to_holder"].set_workspace(
            task.workspace, exclude=desk_value(task.current_holder, task.current_contact)
        )
        self.fields["occurred_at"].initial = timezone.localtime().replace(second=0, microsecond=0)


class StageChangeForm(forms.Form):
    stage = forms.ModelChoiceField(queryset=Stage.objects.none(), label="Move to stage")
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, task, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].queryset = task.workspace.stages.exclude(pk=task.stage_id)


class FollowUpForm(forms.Form):
    follow_up_date = forms.DateField(label="Follow up on", widget=DateInput(), required=False)
    follow_up_note = forms.CharField(label="What to check", max_length=200, required=False)


class EventForm(forms.ModelForm):
    organizer_desk = DeskChoiceField(
        label="Organized / invited by", required=False,
        help_text="A department or person you already track.",
    )

    class Meta:
        model = Event
        fields = [
            "title", "kind", "my_role", "status", "start", "end", "location", "online_link",
            "organizer_other", "my_topic", "duration_minutes", "audience", "description", "preparation",
        ]
        widgets = {
            "start": DateTimeInput(),
            "end": DateTimeInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "preparation": forms.Textarea(attrs={"rows": 3}),
        }

    field_order = [
        "title", "kind", "my_role", "status", "start", "end", "location", "online_link",
        "organizer_desk", "organizer_other", "my_topic", "duration_minutes", "audience",
        "description", "preparation",
    ]

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["organizer_desk"].set_workspace(workspace)
        if self.instance.pk:
            self.fields["organizer_desk"].initial = desk_value(
                self.instance.organizer, self.instance.organizer_contact
            )

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end and end < start:
            self.add_error("end", "The end can't be before the start.")
        return data

    def save(self, commit=True):
        event = super().save(commit=False)
        event.organizer, event.organizer_contact = self.cleaned_data.get("organizer_desk") or (None, None)
        if commit:
            event.save()
        return event


class EventStatusForm(forms.Form):
    status = forms.ChoiceField(choices=Event.STATUS_CHOICES)


# --- AI: quick capture & settings ---------------------------------------------------

class CaptureForm(forms.Form):
    text = forms.CharField(
        label="Message", widget=forms.Textarea(attrs={"rows": 9, "placeholder":
            "Paste an email, WhatsApp message or meeting minutes — or share it here from your phone."}),
    )
    workspace = forms.ModelChoiceField(queryset=Workspace.objects.filter(archived=False), empty_label=None)


class CaptureReviewForm(forms.Form):
    ACTIONS = [("update_task", "Add to an existing task"), ("new_task", "Register a new task"),
               ("new_event", "Add as an event")]

    workspace = forms.ModelChoiceField(queryset=Workspace.objects.all(), widget=forms.HiddenInput)
    body = forms.CharField(widget=forms.HiddenInput, required=False)
    summary = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)
    kind = forms.ChoiceField(label="It's a", choices=[c for c in Update.KIND_CHOICES if c[0] in Update.MANUAL_KINDS])
    source = forms.CharField(label="From", max_length=200, required=False)
    action = forms.ChoiceField(label="What to do with it", choices=ACTIONS, widget=forms.RadioSelect)
    # existing task
    task = forms.ModelChoiceField(queryset=Task.objects.none(), required=False, label="Task")
    handoff = forms.BooleanField(required=False, label="Also record a hand-off to this person")
    # new task
    new_task_title = forms.CharField(label="New task title", max_length=200, required=False)
    my_role = forms.ChoiceField(label="My role", choices=Task.ROLE_CHOICES, initial="following", required=False)
    # shared
    desk = DeskChoiceField(label="Who has it now", required=False)
    next_action = forms.CharField(label="Next action / what to check", max_length=200, required=False)
    due_date = forms.DateField(label="Due date", widget=DateInput(), required=False)
    follow_up_date = forms.DateField(label="Follow up on", widget=DateInput(), required=False)
    # event
    event_title = forms.CharField(label="Event title", max_length=200, required=False)
    event_kind = forms.ChoiceField(label="Type of event", choices=Event.KIND_CHOICES, required=False, initial="meeting")
    event_my_role = forms.ChoiceField(label="My role at the event", choices=Event.ROLE_CHOICES, required=False,
                                      initial="guest")
    event_start = forms.DateTimeField(label="Starts", widget=DateTimeInput(), required=False)
    event_end = forms.DateTimeField(label="Ends", widget=DateTimeInput(), required=False)
    event_location = forms.CharField(label="Where", max_length=200, required=False)

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["task"].queryset = workspace.tasks.open().select_related(
            "current_holder", "current_contact__holder").prefetch_related("current_holder__contacts")
        self.fields["task"].label_from_instance = lambda t: f"{t.title} — {t.desk_name or 'me'}"
        self.fields["desk"].set_workspace(workspace)

    def clean(self):
        data = super().clean()
        action = data.get("action")
        if action == "update_task" and not data.get("task"):
            self.add_error("task", "Choose the task this belongs to.")
        if action == "new_task" and not (data.get("new_task_title") or "").strip():
            self.add_error("new_task_title", "Give the new task a title.")
        if action == "new_event":
            if not (data.get("event_title") or "").strip():
                self.add_error("event_title", "Give the event a title.")
            if not data.get("event_start"):
                self.add_error("event_start", "When does it start?")
            elif data.get("event_end") and data["event_end"] < data["event_start"]:
                self.add_error("event_end", "The end can't be before the start.")
        if not (data.get("body") or "").strip() and not (data.get("summary") or "").strip():
            raise forms.ValidationError("There's nothing to save.")
        return data


class SettingsForm(forms.Form):
    api_key = forms.CharField(
        label="Anthropic API key", required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "off", "placeholder": "sk-ant-…"}),
        help_text="Leave empty to keep the saved key.",
    )
    remove_key = forms.BooleanField(label="Remove the saved key", required=False)
    ai_model = forms.ChoiceField(label="AI model", choices=AppSettings.MODEL_CHOICES)

    def clean_api_key(self):
        key = self.cleaned_data["api_key"].strip()
        if key and (not key.startswith("sk-ant-") or len(key) < 30 or " " in key):
            raise forms.ValidationError("That doesn't look like an Anthropic API key (it starts with sk-ant-).")
        return key
