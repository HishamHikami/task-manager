from django import forms
from django.utils import timezone

from .models import Contact, Holder, Stage, Task, Update, Workspace


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


class HolderForm(forms.ModelForm):
    class Meta:
        model = Holder
        fields = ["name", "kind", "phone", "email", "notes", "active"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2}),
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel", "inputmode": "tel"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def __init__(self, *args, workspace=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace or self.instance.workspace

    def clean_phone(self):
        return " ".join(self.cleaned_data["phone"].split())

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Holder.objects.filter(workspace=self.workspace, name__iexact=name).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This workspace already has someone with that name.")
        return name


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


class HolderChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.display_name


class TaskForm(forms.ModelForm):
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
            "current_holder",
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
        labels = {"current_holder": "Currently with"}
        field_classes = {"current_holder": HolderChoiceField}

    field_order = [
        "title", "description", "my_role", "stage", "current_holder", "priority", "due_date",
        "follow_up_date", "follow_up_note", "reference", "first_note",
    ]

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace
        self.fields["stage"].queryset = workspace.stages.all()
        self.fields["current_holder"].queryset = workspace.holders.filter(active=True).prefetch_related("contacts")
        self.fields["current_holder"].required = False
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
            data["current_holder"] = None  # it's on my own desk
        return data


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
    to_holder = HolderChoiceField(
        queryset=Holder.objects.none(), label="Hand to",
        error_messages={"required": "Choose who the task goes to."},
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    occurred_at = forms.DateTimeField(label="When", widget=DateTimeInput(), required=False)
    follow_up_date = forms.DateField(label="Follow up on", widget=DateInput(), required=False)

    def __init__(self, *args, task, **kwargs):
        super().__init__(*args, **kwargs)
        self.task = task
        self.fields["to_holder"].queryset = (
            task.workspace.holders.filter(active=True).exclude(pk=task.current_holder_id or 0)
            .prefetch_related("contacts")
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
