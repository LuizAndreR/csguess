from datetime import date

from django.core.management.base import BaseCommand, CommandError

from game.logo import NoEligibleTeams, ensure_logo_challenge
from game.services import NoEligiblePlayers, ensure_daily_challenge, local_date


class Command(BaseCommand):
    help = "Garante os desafios diários (Clássico e Logo) sem substituir os existentes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=date.fromisoformat,
            help="Data explícita AAAA-MM-DD"
        )

    def handle(self, *args, **options):
        day = options["date"] or local_date()
        errors = []

        # Um modo indisponível não impede o outro; o comando falha se qualquer um falhar.
        try:
            challenge = ensure_daily_challenge(day)
            self.stdout.write(self.style.SUCCESS(f"Clássico {challenge.date}: {challenge.public_id}"))
        except NoEligiblePlayers as exc:
            errors.append(f"Clássico: {exc}")

        try:
            challenge = ensure_logo_challenge(day)
            self.stdout.write(self.style.SUCCESS(f"Logo {challenge.date}: {challenge.public_id}"))
        except NoEligibleTeams as exc:
            errors.append(f"Logo: {exc}")

        if errors:
            raise CommandError(" | ".join(errors))
