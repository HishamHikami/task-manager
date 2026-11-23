from datetime import timedelta

from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

PHONE_VALIDATOR = RegexValidator(
    r"^[0-9+()\-\s.]*(?:\s*(?:ext\.?|x)\s*[0-9]+)?$",
    "Use digits, spaces, + ( ) - and optionally 'ext 123'.",
)
PHONE_HELP = "Mobile, landline or extension, e.g. +966 50 123 4567 or ext 214."


def tel_link(phone):
    """Phone number in a form usable for a tel: link (digits and leading +)."""
    main = phone.lower().split("ext")[0].split("x")[0]
    return "".join(ch for ch in main if ch.isdigit() or ch == "+")


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
    phone = models.CharField(
        max_length=40, blank=True, validators=[PHONE_VALIDATOR],
        help_text="Main line for the department/committee, or the person's own number.",
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
        return tel_link(self.phone)

    def get_absolute_url(self):
        return reverse("holder_detail", args=[self.pk])

    @property
    def primary_contact(self):
        """The main person to deal with in a department/committee (uses prefetched contacts)."""
        if not self.is_group:
            return None
        people = [c for c in self.contacts.all() if c.active]
        return next((c for c in people if c.is_primary), people[0] if people else None)

    @property
    def display_name(self):
        """"Finance (Sara)" for a group with a main contact, else just the name."""
        contact = self.primary_contact
        return f"{self.name} ({contact.name})" if contact else self.name


class Contact(models.Model):
    """A person inside a department, committee or outside party."""

    holder = models.ForeignKey(Holder, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=120)
    role = models.CharField(
        max_length=120, blank=True, help_text="e.g. Manager, Secretary, Accountant, Committee lead."
    )
    is_primary = models.BooleanField(
        "Main contact", default=False, help_text="The person you usually deal with here."
    )
    phone = models.CharField(max_length=40, blank=True, validators=[PHONE_VALIDATOR], help_text=PHONE_HELP)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True, help_text="Untick when they leave or change roles.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "name"]

    def __str__(self):
        return f"{self.name} — {self.role}" if self.role else self.name

    @property
    def phone_link(self):
        return tel_link(self.phone)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_primary:
            Contact.objects.filter(holder=self.holder, is_primary=True).exclude(pk=self.pk).update(
                is_primary=False
            )


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
    # The specific person inside that department/committee, if known.
    current_contact = models.ForeignKey(
        "Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
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
    def with_me(self):
        """I'm doing it myself and haven't handed it to anyone."""
        return self.current_holder_id is None and self.my_role == "executing"

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

    @property
    def desk_name(self):
        """Whose desk it's on: "Maysara · IT & Support", "IT & Support (Sara)" or "Omar"."""
        return desk_label(self.current_holder, self.current_contact)

    @property
    def desk_person(self):
        """The person to call about it: the assigned person, else the department's main contact."""
        if self.current_contact_id:
            return self.current_contact
        return self.current_holder.primary_contact if self.current_holder_id else None


def desk_label(holder, contact):
    if contact:
        return f"{contact.name} · {contact.holder.name}"
    return holder.display_name if holder else ""


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
    from_contact = models.ForeignKey(
        "Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_contact = models.ForeignKey(
        "Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
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

    @property
    def from_desk(self):
        return desk_label(self.from_holder, self.from_contact)

    @property
    def to_desk(self):
        return desk_label(self.to_holder, self.to_contact)

    def __str__(self):
        return f"{self.get_kind_display()} on {self.task}"


class EventQuerySet(models.QuerySet):
    def upcoming(self):
        now = timezone.now()
        return self.filter(models.Q(end__gte=now) | models.Q(end__isnull=True, start__gte=now - timedelta(hours=12)))

    def past(self):
        now = timezone.now()
        return self.filter(models.Q(end__lt=now) | models.Q(end__isnull=True, start__lt=now - timedelta(hours=12)))


class Event(models.Model):
    """A meeting, lecture, ceremony, conference, etc. and the part I play in it."""

    ROLE_CHOICES = [
        ("host", "Host / Organizer"),
        ("speaker", "Speaker / Lecturer"),
        ("panelist", "Panelist"),
        ("moderator", "Moderator / Master of ceremonies"),
        ("trainer", "Trainer / Workshop leader"),
        ("guest_honor", "Guest of honor / Chief guest"),
        ("representative", "Representing my organization"),
        ("participant", "Participant / Attendee"),
        ("guest", "Invited guest"),
        ("volunteer", "Volunteer / Helper"),
    ]
    # Roles where I present something, so a topic and preparation matter.
    PRESENTING_ROLES = {"speaker", "panelist", "moderator", "trainer", "host"}

    STATUS_CHOICES = [
        ("invited", "Invited — not answered yet"),
        ("tentative", "Tentative / maybe"),
        ("confirmed", "Confirmed — I'm going"),
        ("declined", "Declined"),
        ("done", "Done — attended"),
        ("cancelled", "Cancelled by organizer"),
    ]
    KIND_CHOICES = [
        ("meeting", "Meeting"),
        ("lecture", "Lecture / Talk"),
        ("conference", "Conference / Forum"),
        ("workshop", "Workshop / Training"),
        ("ceremony", "Ceremony / Celebration"),
        ("religious", "Religious gathering / Program"),
        ("exhibition", "Exhibition / Fair"),
        ("visit", "Visit / Tour"),
        ("social", "Social / Dinner"),
        ("other", "Other"),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=200)
    kind = models.CharField("Type of event", max_length=12, choices=KIND_CHOICES, default="meeting")
    my_role = models.CharField("My role", max_length=16, choices=ROLE_CHOICES, default="participant")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="confirmed")
    start = models.DateTimeField("Starts")
    end = models.DateTimeField("Ends", null=True, blank=True)
    location = models.CharField(max_length=200, blank=True, help_text="Venue, address or room.")
    online_link = models.URLField("Online link", blank=True, help_text="Zoom/Teams/Meet link, if online.")
    organizer = models.ForeignKey(
        Holder, on_delete=models.SET_NULL, null=True, blank=True, related_name="events",
        verbose_name="Organized / invited by",
    )
    organizer_contact = models.ForeignKey(
        "Contact", on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    organizer_other = models.CharField(
        "…or organizer not in the list", max_length=200, blank=True,
        help_text="e.g. an outside organization or person you don't track.",
    )
    my_topic = models.CharField(
        "My topic / talk title", max_length=200, blank=True,
        help_text="What I'm presenting, if I'm speaking, leading or hosting.",
    )
    duration_minutes = models.PositiveIntegerField(
        "My speaking time (minutes)", null=True, blank=True,
    )
    audience = models.CharField(max_length=200, blank=True, help_text="Who will attend, expected numbers.")
    description = models.TextField("Details", blank=True)
    preparation = models.TextField(
        "Preparation / to-do", blank=True, help_text="Slides, dress code, gifts, travel, what to bring…"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["start"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("event_detail", args=[self.pk])

    @property
    def is_presenting(self):
        return self.my_role in self.PRESENTING_ROLES

    @property
    def organizer_name(self):
        if self.organizer_contact_id:
            return desk_label(self.organizer, self.organizer_contact)
        if self.organizer_id:
            return self.organizer.display_name
        return self.organizer_other

    @property
    def status_short(self):
        return {"invited": "To answer", "tentative": "Maybe", "confirmed": "Going", "declined": "Declined",
                "done": "Attended", "cancelled": "Cancelled"}.get(self.status, self.status)

    @property
    def organizer_person(self):
        """The person to contact about the event, if known."""
        if self.organizer_contact_id:
            return self.organizer_contact
        return self.organizer.primary_contact if self.organizer_id else None

    @property
    def needs_answer(self):
        return self.status == "invited"

    @property
    def is_off(self):
        return self.status in {"declined", "cancelled"}


class AppSettings(models.Model):
    """Single row of app-wide settings, edited on the Settings page."""

    MODEL_CHOICES = [
        ("claude-haiku-5-5", "Claude Haiku 5.5 — fast and cheapest (recommended)"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5 — smarter, ~20× the cost"),
    ]

    anthropic_key_encrypted = models.TextField(blank=True)
    anthropic_key_hint = models.CharField(max_length=12, blank=True)
    ai_model = models.CharField(max_length=40, choices=MODEL_CHOICES, default="claude-haiku-5-5")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "settings"
        verbose_name_plural = "settings"

    def __str__(self):
        return "Settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def has_api_key(self):
        return bool(self.anthropic_key_encrypted)


class AIUsage(models.Model):
    """One AI call: what for, how many tokens, and (for reuse) the result."""

    PURPOSE_CHOICES = [("capture", "Quick capture"), ("summary", "Summarize update"), ("test", "Connection test")]

    created_at = models.DateTimeField(auto_now_add=True)
    purpose = models.CharField(max_length=10, choices=PURPOSE_CHOICES)
    model = models.CharField(max_length=40)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=True)
    error = models.CharField(max_length=200, blank=True)
    text_hash = models.CharField(max_length=64, blank=True, db_index=True)
    result = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
