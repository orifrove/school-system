from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from education.models import Lesson


class Command(BaseCommand):
    help = "Read-only audit of existing lesson overlaps by teacher and room."

    def add_arguments(self, parser):
        parser.add_argument("--start", help="First local date YYYY-MM-DD; defaults to today.")
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--limit", type=int, default=20, help="Maximum printed conflict pairs (1-200).")
        parser.add_argument("--fail-on-conflict", action="store_true", help="Return a nonzero exit status when conflicts exist.")

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options["start"]) if options["start"] else timezone.localdate()
            if not 1 <= options["days"] <= 90 or not 1 <= options["limit"] <= 200:
                raise ValueError
            end = start + timedelta(days=options["days"])
        except (ValueError, OverflowError):
            raise CommandError("Use a valid --start date, --days 1-90 and --limit 1-200.") from None
        zone = timezone.get_default_timezone()
        begins = timezone.make_aware(datetime.combine(start, time.min), zone)
        ends = timezone.make_aware(datetime.combine(end, time.min), zone)
        lessons = Lesson.objects.exclude(status=Lesson.STATUS_CANCELLED).filter(
            starts_at__lt=ends, ends_at__gt=begins
        ).order_by("starts_at", "pk").values("pk", "teacher_id", "room", "starts_at", "ends_at")
        self.stdout.write("READ ONLY: no lessons changed and no messages sent.")
        self.stdout.write(f"Timezone: {zone}; dates: {start} to {end} (end exclusive)")
        active = []
        checked = conflicts = printed = 0
        # One ordered query; retain only lessons whose intervals still overlap.
        for lesson in lessons.iterator(chunk_size=500):
            checked += 1
            active = [other for other in active if other["ends_at"] > lesson["starts_at"]]
            for other in active:
                reasons = []
                if other["teacher_id"] == lesson["teacher_id"]:
                    reasons.append("teacher")
                room = lesson["room"]
                if room and room.strip() and room == other["room"]:
                    reasons.append("room")
                if not reasons:
                    continue
                conflicts += 1
                if printed < options["limit"]:
                    overlap_start = max(begins, other["starts_at"], lesson["starts_at"])
                    overlap_end = min(ends, other["ends_at"], lesson["ends_at"])
                    self.stdout.write(f"CONFLICT lesson#{other['pk']} / lesson#{lesson['pk']}: "
                        f"{', '.join(reasons)}; {overlap_start.astimezone(zone).isoformat()} - "
                        f"{overlap_end.astimezone(zone).isoformat()}")
                    printed += 1
            active.append(lesson)
        self.stdout.write(f"Checked lessons: {checked}; conflict pairs: {conflicts}; shown: {printed}.")
        if conflicts > printed:
            self.stdout.write("Output limited; narrow the date range or increase --limit.")
        if conflicts and options["fail_on_conflict"]:
            raise CommandError("Existing lesson conflicts found. Review the listed lessons in Admin.")
