"""Baixa os logos de Team.photo_url para game/team_logos/<id>.png (reduzidos)."""
from io import BytesIO
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand

from game.logo import logo_path
from game.models import Team

USER_AGENT = "csguess-dev-script/0.1 (personal project)"
MAX_SIDE = 600
MAX_BYTES = 15 * 1024 * 1024


class Command(BaseCommand):
    help = "Baixa e reduz os logos das equipes; ignora os que já existem (use --force para refazer)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--delay", type=float, default=1.0, help="Pausa entre downloads, em segundos.")

    def handle(self, *args, **options):
        from PIL import Image

        settings.TEAM_LOGO_DIR.mkdir(parents=True, exist_ok=True)
        done = skipped = 0
        failures = []
        for team in Team.objects.exclude(photo_url="").order_by("pk"):
            path = logo_path(team.pk)
            if path.exists() and not options["force"]:
                skipped += 1
                continue
            try:
                request = urllib.request.Request(team.photo_url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("arquivo maior que o limite")
                with Image.open(BytesIO(data)) as image:
                    image = image.convert("RGBA")
                    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
                    image.save(path, "PNG", optimize=True)
                done += 1
            except (urllib.error.URLError, OSError, ValueError) as exc:
                failures.append(f"{team.name}: {exc}")
            time.sleep(options["delay"])

        for failure in failures:
            self.stderr.write(self.style.ERROR(failure))
        self.stdout.write(self.style.SUCCESS(
            f"Logos: {done} baixados, {skipped} já existentes, {len(failures)} falhas."))
