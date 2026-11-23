from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

DEFAULT_STAGES = [
    ("Registered", False),
    ("Assigned", False),
    ("In progress", False),
    ("Waiting approval", False),
    ("Done", True),
    ("Cancelled", True),
]


class Workspace(models.Model):
    """A separate area of life, e.g. a company or a volunteer organization."""

    COLORS = [
        ("blue", "Blue"),
        ("green", "Green"),
        ("purple", "Purple"),
        ("orange", "Orange"),
        ("teal", "Teal"),
        ("red", "Red"),
        ("gray", "Gray"),
    ]

    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=10, choices=COLORS, default="blue")
    ai_enabled = models.BooleanField(
        "Allow AI summaries",
        default=True,
        help_text="Turn off to never send this workspace's text to the AI provider.",
    )
    order = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("workspace_detail", args=[self.pk])

    def create_default_stages(self):
        for i, (name, is_closed) in enumerate(DEFAULT_STAGES):
            Stage.objects.get_or_create(
                workspace=self, name=name, defaults={"order": i, "is_closed": is_closed}
            )

    def first_open_stage(self):
        return self.stages.filter(is_closed=False).order_by("order", "pk").first()


class Stage(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=60)
    order = models.PositiveIntegerField(default=0)
    is_closed = models.BooleanField(
        "Closes the task", default=False, help_text="Tasks in this stage count as finished."
    )

    class Meta:
        ordering = ["workspace", "order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="unique_stage_per_workspace")
        ]

    def __str__(self):
        return self.name


class Holder(models.Model):
    """A department, committee, person or outside party who can hold a task."""

    KIND_CHOICES = [
        ("department", "Department"),
        ("committee", "Committee"),
        ("person", "Person"),
        ("external", "External party"),
        ("me", "Me"),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="holders")
    name = models.CharField(max_length=120)
    # Kinds that are a group or organization rather than one person.
    GROUP_KINDS = ["department", "committee", "external"]

    kind = models.CharField("Type", max_length=12, choices=KIND_CHOICES, default="person")
    contact_person = models.CharField(
        "Point of contact",
        max_length=120,
        blank=True,
        help_text="The person you deal with there, e.g. the department head or committee lead.",
    )
    phone = models.CharField(
        max_length=40,
        blank=True,
        validators=[
            RegexValidator(r"^[0-9+()\-\s.]*(?:\s*(?:ext\.?|x)\s*[0-9]+)?$",
                           "Use digits, spaces, + ( ) - and optionally 'ext 123'.")
        ],
        help_text="Mobile, landline or extension, e.g. +966 50 123 4567 or ext 214.",
    )
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["workspace", "name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="unique_holder_per_workspace")
        ]

    def __str__(self):
        return self.name

    @property
    def is_group(self):
        return self.kind in self.GROUP_KINDS

    @property
    def phone_link(self):
        """Phone number in a form usable for a tel: link (digits and leading +)."""
        main = self.phone.lower().split("ext")[0].split("x")[0]
        digits = "".join(ch for ch in main if ch.isdigit() or ch == "+")
        return digits

    @property
    def display_name(self):
        """"Finance (Sara)" for a group with a point of contact, else just the name."""
        if self.is_group and self.contact_person:
            return f"{self.name} ({self.contact_person})"
        return self.name


class TaskQuerySet(models.QuerySet):
    def open(self):
        return self.filter(stage__is_closed=False)

    def closed(self):
        return self.filter(stage__is_closed=True)

    def active_workspaces(self):
        return self.filter(workspace__archived=False)


class Task(models.Model):
    PRIORITY_CHOICES = [(1, "Low"), (2, "Normal"), (3, "High"), (4, "Urgent")]
    ROLE_CHOICES = [
        ("assigned", "I assigned it"),
        ("following", "I'm following up"),
        ("executing", "I'm doing it"),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(choices=PRIORITY_CHOICES, default=2)
    my_role = models.CharField("My role", max_length=10, choices=ROLE_CHOICES, default="following")
    stage = models.ForeignKey(Stage, on_delete=models.PROTECT, related_name="tasks")
    current_holder = models.ForeignKey(
        Holder, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    due_date = models.DateField(null=True, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_note = models.CharField(max_length=200, blank=True)
    reference = models.CharField(
        max_length=120, blank=True, help_text="Your own reference number, e.g. a letter or ticket no."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    holder_since = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    objects = TaskQuerySet.as_manager()

    class Meta:
        ordering = ["-priority", "due_date", "-updated_at"]
        indexes = [
            models.Index(fields=["follow_up_date"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("task_detail", args=[self.pk])

    @property
    def is_closed(self):
        return self.stage.is_closed

    @property
    def is_overdue(self):
        return bool(self.due_date and not self.is_closed and self.due_date < timezone.localdate())

    @property
    def follow_up_due(self):
        return bool(
            self.follow_up_date and not self.is_closed and self.follow_up_date <= timezone.localdate()
        )

    @property
    def days_with_holder(self):
        return (timezone.now() - self.holder_since).days


class Update(models.Model):
    """One entry on a task's timeline."""

    KIND_CHOICES = [
        ("created", "Created"),
        ("note", "Note"),
        ("email", "Email"),
        ("whatsapp", "WhatsApp"),
        ("meeting", "Meeting minutes"),
        ("call", "Phone call"),
        ("handoff", "Hand-off"),
        ("stage", "Stage change"),
        ("followup", "Follow-up set"),
    ]
    # Kinds the owner can add by hand (the rest are recorded automatically).
    MANUAL_KINDS = ["note", "email", "whatsapp", "meeting", "call"]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="updates")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="note")
    body = models.TextField(blank=True, help_text="Original text, as received.")
    summary = models.TextField(blank=True, help_text="Short summary (optional; AI can fill this later).")
    source = models.CharField(
        max_length=200, blank=True, help_text="Who it came from, subject line, meeting name, etc."
    )
    from_holder = models.ForeignKey(
        Holder, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_holder = models.ForeignKey(
        Holder, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    from_stage = models.ForeignKey(
        Stage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_stage = models.ForeignKey(
        Stage, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    occurred_at = models.DateTimeField(default=timezone.now, help_text="When it happened.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]

    def __str__(self):
        return f"{self.get_kind_display()} on {self.task}"
