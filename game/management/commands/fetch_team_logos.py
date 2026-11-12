"""Baixa os logos de Team.photo_url para game/team_logos/<hash da URL>.png (reduzidos)."""
from io import BytesIO
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from game.logo import logo_path
from game.models import Team

USER_AGENT = "csguess-dev-script/0.1 (personal project)"
MAX_SIDE = 600
MAX_BYTES = 15 * 1024 * 1024
CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "team_logos.json"


class Command(BaseCommand):
    help = "Preenche URLs conhecidas por nome da equipe e baixa seus logos (use --force para refazer)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--delay", type=float, default=1.0, help="Pausa entre downloads, em segundos.")

    def handle(self, *args, **options):
        from PIL import Image

        catalog = {
            name.casefold(): entry["photo_url"]
            for name, entry in json.loads(CATALOG_PATH.read_text(encoding="utf-8")).items()
        }
        settings.TEAM_LOGO_DIR.mkdir(parents=True, exist_ok=True)
        done = skipped = saved = missing = 0
        failures = []
        for team in Team.objects.order_by("pk"):
            needs_url = not team.photo_url
            if needs_url:
                team.photo_url = catalog.get(team.name.strip().casefold(), "")
            if not team.photo_url:
                self.stderr.write(f"{team.name}: sem URL cadastrada e sem entrada no catálogo.")
                missing += 1
                continue
            path = logo_path(team)
            if path.exists() and not options["force"]:
                skipped += 1
                if needs_url:
                    saved += Team.objects.filter(pk=team.pk, photo_url="").update(photo_url=team.photo_url)
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
                # Só associa a URL ao time depois de validar e salvar sua imagem.
                if needs_url:
                    saved += Team.objects.filter(pk=team.pk, photo_url="").update(photo_url=team.photo_url)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                failures.append(f"{team.name}: {exc}")
            time.sleep(options["delay"])

        for failure in failures:
            self.stderr.write(self.style.ERROR(failure))
        self.stdout.write(self.style.SUCCESS(
            f"Logos: {done} baixados, {skipped} já existentes, {saved} URLs salvas, "
            f"{missing} sem URL, {len(failures)} falhas."))
        if failures:
            raise CommandError("Não foi possível baixar todos os logos; consulte as falhas acima.")
