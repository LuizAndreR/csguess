from datetime import date

from django.core.management.base import BaseCommand, CommandError

from game.services import NoEligiblePlayers, ensure_daily_challenge, local_date


class Command(BaseCommand):
    help = "Garante o desafio diário sem substituir desafios existentes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=date.fromisoformat,
            help="Data explícita AAAA-MM-DD"
        )

    def handle(self, *args, **options):
        try:
            challenge = ensure_daily_challenge(options["date"] or local_date())
        except NoEligiblePlayers as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Desafio {challenge.date}: {challenge.public_id}"))
