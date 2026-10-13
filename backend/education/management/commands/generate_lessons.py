from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from education.lesson_generation import generate_lessons


class Command(BaseCommand):
    help = "Preview lessons from recurring schedules; --apply saves new lessons only."

    def add_arguments(self, parser):
        parser.add_argument("--start", help="First local date, YYYY-MM-DD; defaults to today.")
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--schedule-id", type=int)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options["start"]) if options["start"] else timezone.localdate()
        except ValueError:
            raise CommandError("--start must be a valid YYYY-MM-DD date.") from None
        try:
            report = generate_lessons(start, options["days"], apply=options["apply"], schedule_id=options["schedule_id"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from None
        self.stdout.write("APPLIED: new lessons saved." if options["apply"] else "PREVIEW ONLY: no lessons changed. Use --apply to save.")
        self.stdout.write(f"Timezone: {settings.TIME_ZONE}; start={start}; days={options['days']}")
        for detail in report.pop("details"):
            self.stdout.write(detail)
        for conflict in report.pop("conflict_details"):
            self.stdout.write(f"CONFLICT: {conflict}")
        if report["conflicts"]:
            self.stdout.write("Apply is blocked by conflicts. Candidate counts include conflicting slots.")
        self.stdout.write(str(report))
        self.stdout.write("Details limited to 50 entries; conflict reasons to 20. Existing lessons, including cancelled ones, are preserved.")
