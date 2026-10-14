from django.db import connection


def lock_lesson_planning():
    """Serialize generator and Lesson Admin writes within their transaction."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [73191501])
