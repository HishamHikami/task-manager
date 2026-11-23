import re

import django.core.validators
from django.db import migrations, models

EMAIL_RE = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+")


def split_contact(apps, schema_editor):
    """Move the old free-text contact into phone / email without losing anything."""
    Holder = apps.get_model("tracker", "Holder")
    for h in Holder.objects.exclude(contact=""):
        text = h.contact.strip()
        match = EMAIL_RE.search(text)
        if match:
            h.email = match.group(0)
            text = (text[: match.start()] + text[match.end():]).strip(" ,;/|-")
        if text:
            if len(text) <= 40:
                h.phone = text
            else:
                h.notes = (h.notes + "\n" if h.notes else "") + f"Contact: {text}"
        h.save(update_fields=["phone", "email", "notes"])


def join_contact(apps, schema_editor):
    Holder = apps.get_model("tracker", "Holder")
    for h in Holder.objects.all():
        h.contact = " / ".join(v for v in (h.phone, h.email) if v)[:200]
        h.save(update_fields=["contact"])


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0002_holder_contact_person"),
    ]

    operations = [
        migrations.AddField(
            model_name="holder",
            name="phone",
            field=models.CharField(
                blank=True,
                help_text="Mobile, landline or extension, e.g. +966 50 123 4567 or ext 214.",
                max_length=40,
                validators=[
                    django.core.validators.RegexValidator(
                        "^[0-9+()\\-\\s.]*(?:\\s*(?:ext\\.?|x)\\s*[0-9]+)?$",
                        "Use digits, spaces, + ( ) - and optionally 'ext 123'.",
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="holder",
            name="email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.RunPython(split_contact, join_contact),
        migrations.RemoveField(
            model_name="holder",
            name="contact",
        ),
    ]
