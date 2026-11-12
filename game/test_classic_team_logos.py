import json

from django.test import TestCase
from django.urls import reverse

from .logo import logo_path
from .models import DailyChallenge
from .services import local_date, player_snapshot
from .tests import LogoSettingsMixin, make_player


class ClassicTeamLogoTests(LogoSettingsMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.team = self.make_team("FURIA")
        self.chosen = make_player(1, team=self.team)
        secret = make_player(2, team_name="Outro time")
        self.challenge = DailyChallenge.objects.create(
            date=local_date(), secret_player=secret, secret_snapshot=player_snapshot(secret),
        )
        self.url = reverse("game:classic-team-logo", args=[self.chosen.pk])

    def guess(self):
        self.client.get(reverse("game:classic"))
        return self.client.post(
            reverse("game:guesses"), content_type="application/json",
            data=json.dumps({"challenge_date": str(local_date()), "player_id": self.chosen.pk}),
        )

    def test_only_serves_logo_after_player_was_guessed(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        response = self.guess()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["player"]["team_logo_url"], self.url)
        image = self.client.get(self.url)
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image["Content-Type"], "image/png")
        self.assertEqual(b"".join(image.streaming_content), logo_path(self.team).read_bytes())
        self.assertEqual(image["Cache-Control"], "no-store")
        secret_url = reverse("game:classic-team-logo", args=[self.challenge.secret_player_id])
        self.assertEqual(self.client.get(secret_url).status_code, 404)

    def test_restored_guesses_include_logo(self):
        self.guess()
        body = self.client.get(reverse("game:classic")).json()
        self.assertEqual(body["guesses"][0]["player"]["team_logo_url"], self.url)
        self.assertEqual(body["guesses"][0]["player"]["current_team"], "FURIA")

    def test_without_team_or_photo_keeps_text_without_logo(self):
        self.chosen.team = None
        self.chosen.save()
        data = self.guess().json()["player"]
        self.assertEqual((data["current_team"], data["team_logo_url"]), ("No team", ""))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.team.photo_url = ""
        self.team.save()
        self.chosen.team = self.team
        self.assertEqual(player_snapshot(self.chosen)["team_logo_url"], "")

    def test_missing_file_does_not_break_guess(self):
        logo_path(self.team).unlink()
        self.assertEqual(self.guess().status_code, 201)
        self.assertEqual(self.client.get(self.url).status_code, 404)
