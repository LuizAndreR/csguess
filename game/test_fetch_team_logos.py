from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.error import URLError

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from PIL import Image

from .logo import logo_path
from .models import Team


class FetchTeamLogosTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        settings = override_settings(TEAM_LOGO_DIR=root / "logos")
        settings.enable()
        self.addCleanup(settings.disable)
        self.url = "https://example.com/furia.png"
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps({"FURIA": {"photo_url": self.url}}))
        patcher = patch("game.management.commands.fetch_team_logos.CATALOG_PATH", catalog)
        patcher.start()
        self.addCleanup(patcher.stop)
        data = BytesIO()
        Image.new("RGBA", (800, 400), (255, 100, 0, 255)).save(data, "PNG")
        self.image = data.getvalue()

    def run_command(self):
        call_command("fetch_team_logos", delay=0, stdout=StringIO(), stderr=StringIO())

    @patch("game.management.commands.fetch_team_logos.urllib.request.urlopen")
    def test_fills_url_by_name_downloads_and_is_idempotent(self, urlopen):
        team = Team.objects.create(name="furia")
        unrelated = Team.objects.create(name="Desconhecido")
        urlopen.return_value.__enter__.return_value.read.return_value = self.image
        self.run_command()
        team.refresh_from_db()
        unrelated.refresh_from_db()
        self.assertEqual(team.photo_url, self.url)
        self.assertEqual(unrelated.photo_url, "")
        with Image.open(logo_path(team)) as image:
            self.assertEqual((image.format, image.size), ("PNG", (600, 300)))
        self.run_command()
        urlopen.assert_called_once()

    @patch("game.management.commands.fetch_team_logos.urllib.request.urlopen")
    def test_preserves_existing_url(self, urlopen):
        custom = "https://example.com/custom.png"
        team = Team.objects.create(name="FURIA", photo_url=custom)
        urlopen.return_value.__enter__.return_value.read.return_value = self.image
        self.run_command()
        team.refresh_from_db()
        self.assertEqual(team.photo_url, custom)
        self.assertEqual(urlopen.call_args.args[0].full_url, custom)

    @patch("game.management.commands.fetch_team_logos.urllib.request.urlopen")
    def test_failed_download_does_not_save_url(self, urlopen):
        team = Team.objects.create(name="FURIA")
        for failure in (URLError("offline"), None):
            with self.subTest(failure=failure):
                urlopen.side_effect = failure
                urlopen.return_value.__enter__.return_value.read.return_value = b"not an image"
                with self.assertRaises(CommandError):
                    self.run_command()
                team.refresh_from_db()
                self.assertEqual(team.photo_url, "")
