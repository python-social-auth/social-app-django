import io

from django.core.management import call_command
from django.core.management.commands import makemigrations
from django.test import TestCase


class MigrationTestCase(TestCase):
    def test_missing_migrations(self):
        output = io.StringIO()
        try:
            call_command(
                makemigrations.Command(),
                dry_run=True,
                check_changes=True,
                verbosity=1,
                stdout=output,
                no_color=True,
            )
        except SystemExit as err:
            if err.code != 0:
                raise AssertionError(output.getvalue())
