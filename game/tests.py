from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Player, Team


def player(**kwargs):
    data = {"nick": "teste", "name": "João 测试", "source": "liquipedia:counterstrike", "source_id": "Jogador", "is_major_winner": False}
    data.update(kwargs)
    return Player(**data)


class PlayerValidationTests(SimpleTestCase):
    def validate(self, instance):
        instance.full_clean(validate_unique=False, validate_constraints=False)

    def test_nationalities_normalized(self):
        instance = player(nationalities=["br", "PT"])
        self.validate(instance)
        self.assertEqual(instance.nationalities, ["BR", "PT"])

    def test_invalid_nationalities(self):
        for value in (None, {}, "BR", [1], ["BRA"], ["B1"], ["éé"], ["BR", "br"], [" BR"]):
            with self.subTest(value=value), self.assertRaises(ValidationError) as exc:
                self.validate(player(nationalities=value))
            self.assertIn("nationalities", exc.exception.message_dict)

    def test_invalid_roles(self):
        for value in (None, {}, "igl", [1], [""], ["  "], ["igl", "igl"], [["entry"]], ["entry"], ["rifler"], ["AWP"]):
            with self.subTest(value=value), self.assertRaises(ValidationError) as exc:
                self.validate(player(roles=value))
            self.assertIn("roles", exc.exception.message_dict)

    def test_supported_roles_are_preserved(self):
        roles = ["igl", "rifle", "awp"]
        instance = player(roles=roles)
        self.validate(instance)
        self.assertEqual(instance.roles, roles)

    def test_defaults_are_independent_and_missing_data_is_valid(self):
        first, second = player(), player()
        self.validate(first)
        first.nationalities.append("BR")
        first.roles.append("igl")
        self.assertEqual(second.nationalities, [])
        self.assertEqual(second.roles, [])
        self.assertEqual(second.career_status, Player.CareerStatus.UNKNOWN)
        for field in ("years_active", "photo_url", "source_url"):
            self.assertEqual(getattr(second, field), "")
        self.assertIsNone(second.source_collected_at)

    def test_status_does_not_infer_team_or_roles(self):
        for status in Player.CareerStatus.values:
            instance = player(career_status=status)
            self.validate(instance)
            self.assertEqual(instance.current_team, "No team")
            self.assertEqual(instance.roles, [])

    def test_required_fields_and_invalid_status(self):
        for field in ("nick", "name", "source", "source_id", "career_status"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.validate(player(**{field: ""}))
        with self.assertRaises(ValidationError):
            self.validate(player(career_status="benched"))

    def test_optional_text_uses_empty_string_not_null(self):
        for field in ("years_active", "photo_url", "source_url"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.validate(player(**{field: None}))

    def test_unicode_long_urls_and_source_identifier(self):
        instance = player(photo_url="https://example.com/" + "a" * 2000,
                          source_url="https://example.com/" + "b" * 2000,
                          source_id="página-非数字", years_active="2003 – Present")
        self.validate(instance)


class PlayerPersistenceTests(TestCase):
    def test_save_normalizes_and_persists_metadata(self):
        instance = player(nationalities=["br"], roles=["igl", "rifle"], source_collected_at=timezone.now())
        instance.save()
        instance.refresh_from_db()
        self.assertEqual(instance.nationalities, ["BR"])
        self.assertEqual(instance.name, "João 测试")
        self.assertEqual(instance.roles, ["igl", "rifle"])
        self.assertIsNotNone(instance.created_at)
        self.assertIsNotNone(instance.updated_at)
        self.assertIsNotNone(instance.source_collected_at)

    def test_save_rejects_invalid_lists(self):
        for field in ("roles", "nationalities"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                player(**{field: {}}).save()
        self.assertEqual(Player.objects.count(), 0)

    def test_source_identity_is_validated(self):
        player().save()
        with self.assertRaises(ValidationError):
            player(nick="outro").save()

    def test_database_enforces_source_identity_even_without_model_validation(self):
        player().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Player.objects.bulk_create([player(nick="outro")])

    def test_nick_can_repeat_and_source_identity_is_a_pair(self):
        player().save()
        player(source_id="outra página").save()
        player(source="outra:fonte").save()
        self.assertEqual(Player.objects.filter(nick="teste").count(), 3)


class HomeTests(SimpleTestCase):
    def test_home(self):
        response = self.client.get(reverse("game:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/classic.html")
        self.assertContains(response, "CSGuess")
        self.assertContains(response, "Quem está na sua mira?")
        self.assertContains(response, "/static/game/css/classic.css")
        self.assertContains(response, "/static/game/js/classic.js")
        self.assertContains(response, 'class="mode-button" href="/logo/"')


# ---------------------------------------------------------------------------
# Regras de comparação (puras, sem banco)
# ---------------------------------------------------------------------------
from datetime import timedelta
import json

from django.core.management import call_command

from .models import DailyChallenge
from .normalization import parse_activity, search_key
from .services import (
    NoEligiblePlayers, compare, compare_sets, compare_year,
    ensure_daily_challenge, local_date,
)


def snap(**kwargs):
    data = {
        "id": 1, "career_status": "active", "is_major_winner": False,
        "current_team": "FaZe", "nationalities": ["BR"], "roles": ["rifle"],
        "years_active": "2015 – Present",
    }
    data.update(kwargs)
    return data


class CompareTests(SimpleTestCase):
    def test_compare_sets(self):
        self.assertEqual(compare_sets(["BR"], ["BR"]), "correct")
        self.assertEqual(compare_sets(["BR", "PT"], ["PT", "BR"]), "correct")
        self.assertEqual(compare_sets(["BR", "PT"], ["BR"]), "partial")
        self.assertEqual(compare_sets(["DK"], ["BR"]), "incorrect")

    def test_compare_year(self):
        self.assertEqual(compare_year(2015, 2015), {"status": "correct", "direction": None})
        self.assertEqual(compare_year(2015, 2018)["direction"], "up")
        self.assertEqual(compare_year(2018, 2015)["direction"], "down")
        self.assertEqual(compare_year(2015, None)["direction"], "ongoing")
        self.assertEqual(compare_year(None, 2020)["direction"], "ended")
        self.assertEqual(compare_year(None, None)["status"], "correct")

    def test_parse_activity(self):
        self.assertEqual(parse_activity("2015 – Present"), (2015, None))
        self.assertEqual(parse_activity("2009 – 2014"), (2009, 2014))
        for bad in ("2015 - Present", "2015", "1899 – 2000", "2020 – 2010", "2015 – present", ""):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                parse_activity(bad)

    def test_search_key(self):
        self.assertEqual(search_key("GeT_RiGhT"), "getright")
        self.assertEqual(search_key("r0pz"), search_key("ropz"))
        self.assertEqual(search_key("Håvard"), "havard")

    def test_compare_identical_profile(self):
        result = compare(snap(), snap())
        self.assertEqual(result["player"], "correct")
        for field in ("career_status", "is_major_winner", "current_team", "nationalities", "roles"):
            self.assertEqual(result[field], "correct")
        self.assertEqual(result["activity"]["start"]["status"], "correct")
        self.assertEqual(result["activity"]["end"]["status"], "correct")

    def test_compare_different_profile(self):
        result = compare(
            snap(id=2, career_status="retired", is_major_winner=True, current_team="No team",
                 nationalities=["BR", "PT"], roles=["awp"], years_active="2010 – 2014"),
            snap(),
        )
        self.assertEqual(result["player"], "incorrect")
        self.assertEqual(result["career_status"], "incorrect")
        self.assertEqual(result["is_major_winner"], "incorrect")
        self.assertEqual(result["current_team"], "incorrect")
        self.assertEqual(result["nationalities"], "partial")
        self.assertEqual(result["roles"], "incorrect")
        self.assertEqual(result["activity"]["start"]["direction"], "up")
        self.assertEqual(result["activity"]["end"]["direction"], "ongoing")

    def test_compare_normalizes_empty_team(self):
        self.assertEqual(compare(snap(current_team=""), snap(current_team="No team"))["current_team"], "correct")


# ---------------------------------------------------------------------------
# Sorteio diário e API (exigem PostgreSQL)
# ---------------------------------------------------------------------------
def make_player(n, **kwargs):
    data = {
        "nick": f"player{n}", "name": f"Nome Sobrenome{n} Extra", "source_id": str(n),
        "nationalities": ["BR"], "roles": ["rifle"], "career_status": "active",
        "years_active": "2015 – Present",
    }
    team_name = kwargs.pop("team_name", "FaZe")
    data.update(kwargs)
    if team_name and "team" not in data:
        data["team"] = Team.objects.get_or_create(name=team_name)[0]
    p = player(**data)
    p.save()
    return p


class DailyChallengeTests(TestCase):
    def test_creates_one_challenge_and_is_idempotent(self):
        make_player(1)
        first = ensure_daily_challenge()
        second = ensure_daily_challenge()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.date, local_date())
        self.assertEqual(DailyChallenge.objects.count(), 1)
        self.assertEqual(first.secret_snapshot["id"], first.secret_player_id)

    def test_seven_day_block_excludes_recent_players_both_directions(self):
        a, b = make_player(1), make_player(2)
        day = local_date()
        DailyChallenge.objects.create(date=day - timedelta(days=6), secret_player=a, secret_snapshot={})
        DailyChallenge.objects.create(date=day + timedelta(days=6), secret_player=b, secret_snapshot={})
        with self.assertRaises(NoEligiblePlayers):
            ensure_daily_challenge(day)

    def test_player_returns_after_block_window(self):
        a = make_player(1)
        day = local_date()
        DailyChallenge.objects.create(date=day - timedelta(days=7), secret_player=a, secret_snapshot={})
        self.assertEqual(ensure_daily_challenge(day).secret_player_id, a.pk)

    def test_ineligible_players_are_never_drawn(self):
        make_player(1, roles=[])          # sem funções
        good = make_player(2)
        for _ in range(5):
            DailyChallenge.objects.all().delete()
            self.assertEqual(ensure_daily_challenge().secret_player_id, good.pk)

    def test_no_eligible_players_raises(self):
        make_player(1, roles=[])
        with self.assertRaises(NoEligiblePlayers):
            ensure_daily_challenge()

    def test_management_command_fails_without_candidates(self):
        with self.assertRaises(Exception):
            call_command("ensure_daily_challenge")


class ClassicAPITests(TestCase):
    def setUp(self):
        self.secret = make_player(1, nick="GeT_RiGhT", nationalities=["SE"], roles=["igl"],
                                  years_active="2003 – Present", is_major_winner=True)
        self.other = make_player(2, nick="r0pz", nationalities=["EE"], roles=["rifle"],
                                 years_active="2016 – Present")
        self.challenge = DailyChallenge.objects.create(
            date=local_date(), secret_player=self.secret,
            secret_snapshot=__import__("game.services", fromlist=["player_snapshot"]).player_snapshot(self.secret),
        )

    def guess(self, player_id, date=None):
        return self.client.post(
            reverse("game:guesses"),
            data=json.dumps({"challenge_date": date or local_date().isoformat(), "player_id": player_id}),
            content_type="application/json",
        )

    def test_get_initializes_cookie_and_hides_secret(self):
        response = self.client.get(reverse("game:classic"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "in_progress")
        self.assertEqual(body["guesses"], [])
        self.assertNotIn("victory", body)
        self.assertNotIn("GeT_RiGhT", response.content.decode())
        self.assertIn("csguess_classic_progress", response.cookies)
        self.assertTrue(response.cookies["csguess_classic_progress"]["httponly"])

    def test_get_without_challenge_returns_503(self):
        DailyChallenge.objects.all().delete()
        response = self.client.get(reverse("game:classic"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "challenge_unavailable")

    def test_method_not_allowed(self):
        self.assertEqual(self.client.post(reverse("game:classic")).status_code, 405)
        self.assertEqual(self.client.get(reverse("game:guesses")).status_code, 405)

    def test_search_normalizes_and_validates(self):
        self.client.get(reverse("game:classic"))
        url = reverse("game:player-search")
        nicks = lambda q: [p["nick"] for p in self.client.get(url, {"q": q}).json()["players"]]
        self.assertEqual(nicks("getright"), ["GeT_RiGhT"])
        self.assertEqual(nicks("ropz"), ["r0pz"])
        self.assertEqual(nicks("r0"), ["r0pz"])
        self.assertEqual(self.client.get(url, {"q": "a"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"q": "a" * 101}).status_code, 400)

    def test_search_limits_to_ten_and_returns_short_name(self):
        for n in range(10, 25):
            make_player(n, nick=f"zed{n}")
        players = self.client.get(reverse("game:player-search"), {"q": "zed"}).json()["players"]
        self.assertEqual(len(players), 10)
        self.assertTrue(all(len(p["name"].split()) == 2 for p in players))

    def test_guess_requires_session(self):
        response = self.guess(self.other.pk)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "session_required")

    def test_wrong_guess_returns_comparison_without_leaking_secret(self):
        self.client.get(reverse("game:classic"))
        response = self.guess(self.other.pk)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertFalse(body["correct"])
        self.assertEqual(body["number"], 1)
        self.assertEqual(body["comparison"]["player"], "incorrect")
        self.assertEqual(body["comparison"]["nationalities"], "incorrect")
        self.assertEqual(body["comparison"]["is_major_winner"], "incorrect")
        self.assertNotIn("victory", body)
        self.assertNotIn("GeT_RiGhT", response.content.decode())

    def test_duplicate_guess_rejected_and_hidden_from_search(self):
        self.client.get(reverse("game:classic"))
        self.guess(self.other.pk)
        self.assertEqual(self.guess(self.other.pk).json()["error"]["code"], "duplicate_guess")
        found = self.client.get(reverse("game:player-search"), {"q": "ropz"}).json()["players"]
        self.assertEqual(found, [])

    def test_victory_flow_and_restore(self):
        self.client.get(reverse("game:classic"))
        self.guess(self.other.pk)
        win = self.guess(self.secret.pk)
        self.assertEqual(win.status_code, 201)
        body = win.json()
        self.assertTrue(body["correct"])
        self.assertEqual(body["victory"]["attempts"], 2)
        self.assertEqual(body["victory"]["player"]["nick"], "GeT_RiGhT")
        self.assertEqual(self.guess(self.other.pk).status_code, 409)

        restored = self.client.get(reverse("game:classic")).json()
        self.assertEqual(restored["state"], "completed")
        self.assertEqual(len(restored["guesses"]), 2)
        self.assertEqual(restored["victory"]["attempts"], 2)

    def test_progress_does_not_carry_over_to_another_challenge(self):
        self.client.get(reverse("game:classic"))
        self.guess(self.other.pk)
        self.challenge.public_id = __import__("uuid").uuid4()
        self.challenge.save()
        self.assertEqual(self.client.get(reverse("game:classic")).json()["guesses"], [])

    def test_tampered_cookie_is_discarded(self):
        self.client.get(reverse("game:classic"))
        self.guess(self.other.pk)
        self.client.cookies["csguess_classic_progress"] = "adulterado"
        self.assertEqual(self.client.get(reverse("game:classic")).json()["guesses"], [])

    def test_invalid_requests(self):
        self.client.get(reverse("game:classic"))
        post = lambda body, ct="application/json": self.client.post(
            reverse("game:guesses"), data=body, content_type=ct)
        today = local_date().isoformat()
        cases = [
            (post("x", "text/plain"), 415, "invalid_content_type"),
            (post("não é json"), 400, "invalid_json"),
            (post("[]"), 400, "invalid_body"),
            (post(json.dumps({"challenge_date": today})), 400, "invalid_body"),
            (post(json.dumps({"challenge_date": today, "player_id": True})), 400, "invalid_player"),
            (post(json.dumps({"challenge_date": today, "player_id": "1"})), 400, "invalid_player"),
            (post(json.dumps({"challenge_date": today, "player_id": 0})), 400, "invalid_player"),
            (post(json.dumps({"challenge_date": "06/11/2026", "player_id": 1})), 400, "invalid_date"),
            (post(json.dumps({"challenge_date": "2026-13-45", "player_id": 1})), 400, "invalid_date"),
            (post(json.dumps({"challenge_date": today, "player_id": 999999})), 400, "invalid_player"),
        ]
        for response, status, code in cases:
            with self.subTest(code=code):
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code)

    def test_stale_date_returns_409(self):
        self.client.get(reverse("game:classic"))
        yesterday = (local_date() - timedelta(days=1)).isoformat()
        response = self.guess(self.other.pk, yesterday)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "challenge_changed")

    def test_ineligible_player_cannot_be_guessed(self):
        bad = make_player(3, roles=[])
        self.client.get(reverse("game:classic"))
        self.assertEqual(self.guess(bad.pk).json()["error"]["code"], "invalid_player")

    def test_csrf_is_enforced(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("game:classic"))
        response = client.post(reverse("game:guesses"), data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "csrf_failed")

    def test_health(self):
        self.assertEqual(self.client.get(reverse("game:health")).json(), {"status": "ok"})


class TeamTests(TestCase):
    def test_player_without_team_reads_no_team(self):
        p = make_player(1, team_name=None)
        self.assertIsNone(p.team)
        self.assertEqual(p.current_team, "No team")

    def test_current_team_comes_from_relation(self):
        p = make_player(1, team_name="FURIA")
        p.refresh_from_db()
        self.assertEqual(p.current_team, "FURIA")
        self.assertEqual(list(p.team.players.all()), [p])

    def test_many_players_share_one_team(self):
        make_player(1, team_name="FURIA")
        make_player(2, team_name="FURIA")
        self.assertEqual(Team.objects.count(), 1)
        self.assertEqual(Team.objects.get().players.count(), 2)

    def test_team_name_is_unique_and_trimmed(self):
        Team.objects.create(name="FURIA")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Team.objects.create(name="FURIA")
        t = Team.objects.create(name="  NAVI  ")
        self.assertEqual(t.name, "NAVI")

    def test_reserved_name_rejected(self):
        for name in ("No team", "no TEAM", " No team "):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                Team.objects.create(name=name)

    def test_team_with_players_cannot_be_deleted(self):
        p = make_player(1, team_name="FURIA")
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            p.team.delete()

    def test_retired_player_cannot_have_team(self):
        team = Team.objects.create(name="FURIA")
        with self.assertRaises(ValidationError) as exc:
            player(career_status="retired", team=team).save()
        self.assertIn("team", exc.exception.message_dict)
        player(career_status="retired", source_id="r").save()

    def test_snapshot_exposes_team_name(self):
        from .services import player_snapshot
        self.assertEqual(player_snapshot(make_player(1, team_name="FURIA"))["current_team"], "FURIA")
        self.assertEqual(player_snapshot(make_player(2, team_name=None))["current_team"], "No team")

    def test_renaming_team_updates_all_players(self):
        from .services import eligible_players
        a, b = make_player(1, team_name="Old"), make_player(2, team_name="Old")
        Team.objects.filter(name="Old").update(name="New")
        names = {data["current_team"] for _, data in eligible_players(Player.objects.filter(pk__in=[a.pk, b.pk]))}
        self.assertEqual(names, {"New"})

    def test_eligible_players_does_not_query_team_per_player(self):
        from .services import eligible_players
        for n in range(5):
            make_player(n, team_name=f"T{n}")
        with self.assertNumQueries(1):
            list(eligible_players())


class ImportPlayersTeamTests(TestCase):
    def document(self, *rows):
        base = {"nick": "x", "name": "Nome X", "nationalities": ["BR"], "career_status": "active",
                "current_team": "FURIA", "roles": ["rifle"], "years_active": "2015 – Present",
                "photo_url": "", "is_major_winner": False, "source": "liquipedia:counterstrike",
                "source_id": "1", "source_url": "", "source_collected_at": None}
        players = [{**base, **row} for row in rows]
        return {"schema_version": 2, "exported_at": "2026-11-06T00:00:00-03:00", "players": players}

    def run_import(self, document, *args):
        import tempfile, os
        from io import StringIO
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(document, f)
        try:
            call_command("import_players", f.name, *args, stdout=StringIO())
        finally:
            os.unlink(f.name)

    def test_import_creates_teams_and_reuses_them(self):
        self.run_import(self.document(
            {"nick": "a", "source_id": "1"},
            {"nick": "b", "source_id": "2"},
            {"nick": "c", "source_id": "3", "current_team": "No team"},
            {"nick": "d", "source_id": "4", "current_team": ""},
        ))
        self.assertEqual(Team.objects.count(), 1)
        self.assertEqual(Team.objects.get().players.count(), 2)
        self.assertEqual(Player.objects.filter(team__isnull=True).count(), 2)

    def test_import_is_idempotent_and_moves_player_between_teams(self):
        self.run_import(self.document({}))
        self.run_import(self.document({}))
        self.assertEqual((Player.objects.count(), Team.objects.count()), (1, 1))
        self.run_import(self.document({"current_team": "NAVI"}))
        self.assertEqual(Player.objects.get().current_team, "NAVI")
        self.run_import(self.document({"current_team": "No team"}))
        self.assertIsNone(Player.objects.get().team)

    def test_dry_run_writes_nothing(self):
        self.run_import(self.document({}), "--dry-run")
        self.assertEqual((Player.objects.count(), Team.objects.count()), (0, 0))

    def test_retired_with_team_is_rejected(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_import(self.document({"career_status": "retired"}))
        self.assertEqual((Player.objects.count(), Team.objects.count()), (0, 0))


# ---------------------------------------------------------------------------
# Modo Logo
# ---------------------------------------------------------------------------
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from django.test import override_settings

from .logo import (
    BLUR_RADII, BLUR_STEP, NoEligibleTeams, attempts_to_next_level, blur_index,
    ensure_logo_challenge, eligible_teams, logo_path, render_logo,
)
from .models import TeamChallenge


class LogoSettingsMixin:
    """Cada teste usa uma pasta temporária de logos (PNGs com detalhe, para o blur ser mensurável)."""

    def setUp(self):
        super().setUp()
        from PIL import Image, ImageDraw
        self.logo_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.logo_dir, True)
        override = override_settings(TEAM_LOGO_DIR=self.logo_dir)
        override.enable()
        self.addCleanup(override.disable)
        self._Image, self._Draw = Image, ImageDraw

    def make_team(self, name, logo=True, photo=None):
        if photo is None:
            photo = f"https://liquipedia.net/commons/images/x/xx/{quote(name)}_darkmode.png"
        team = Team.objects.create(name=name, photo_url=photo)
        if logo:
            image = self._Image.new("RGBA", (300, 200), (0, 0, 0, 0))
            draw = self._Draw.Draw(image)
            for i in range(0, 300, 20):
                draw.rectangle([i, 0, i + 9, 199], fill=(255, 120 + i % 100, 0, 255))
            image.save(logo_path(team))
        return team


class LogoRulesTests(SimpleTestCase):
    def test_blur_index_changes_every_ten_attempts(self):
        self.assertEqual([blur_index(n) for n in (0, 9, 10, 19, 20, 29, 30, 99)], [0, 0, 1, 1, 2, 2, 3, 3])
        self.assertEqual(BLUR_STEP, 10)
        self.assertEqual(BLUR_RADII[-1], 0)

    def test_solved_is_always_sharp(self):
        self.assertEqual(blur_index(0, solved=True), len(BLUR_RADII) - 1)

    def test_attempts_to_next_level(self):
        self.assertEqual(attempts_to_next_level(0, 0), 10)
        self.assertEqual(attempts_to_next_level(9, 0), 1)
        self.assertEqual(attempts_to_next_level(10, 1), 10)
        self.assertIsNone(attempts_to_next_level(30, len(BLUR_RADII) - 1))


class LogoRenderTests(LogoSettingsMixin, TestCase):
    def test_each_level_is_sharper_than_the_previous(self):
        from PIL import Image, ImageChops, ImageStat
        team = self.make_team("FURIA")
        images = [Image.open(BytesIO(render_logo(team, i))).convert("L") for i in range(len(BLUR_RADII))]
        self.assertTrue(all(img.size == (480, 300) for img in images))
        # Contraste local (desvio padrão) só aumenta conforme o desfoque diminui.
        deviations = [ImageStat.Stat(img).stddev[0] for img in images]
        self.assertEqual(deviations, sorted(deviations))
        self.assertLess(deviations[0], deviations[-1])

    def test_render_is_png_and_cached(self):
        team = self.make_team("FURIA")
        first = render_logo(team, 0)
        self.assertTrue(first.startswith(b"\x89PNG"))
        self.assertIs(render_logo(team, 0), first)

    def test_missing_file_raises_oserror(self):
        team = self.make_team("FURIA", logo=False)
        with self.assertRaises(OSError):
            render_logo(team, 0)


class LogoChallengeTests(LogoSettingsMixin, TestCase):
    def test_only_teams_with_photo_and_file_are_eligible(self):
        ok = self.make_team("Ok")
        self.make_team("SemArquivo", logo=False)
        self.make_team("SemFoto", logo=False, photo="")
        no_url = Team.objects.create(name="SemUrl")
        self.assertEqual(eligible_teams(), [ok])
        self.assertNotIn(no_url, eligible_teams())

    def test_creates_one_challenge_and_is_idempotent(self):
        team = self.make_team("FURIA")
        first, second = ensure_logo_challenge(), ensure_logo_challenge()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual((first.date, first.secret_team), (local_date(), team))
        self.assertEqual(TeamChallenge.objects.count(), 1)

    def test_no_eligible_team_raises(self):
        self.make_team("SemArquivo", logo=False)
        with self.assertRaises(NoEligibleTeams):
            ensure_logo_challenge()

    def test_seven_day_block_both_directions(self):
        a, b = self.make_team("A"), self.make_team("B")
        day = local_date()
        TeamChallenge.objects.create(date=day - timedelta(days=6), secret_team=a)
        TeamChallenge.objects.create(date=day + timedelta(days=6), secret_team=b)
        with self.assertRaises(NoEligibleTeams):
            ensure_logo_challenge(day)

    def test_team_returns_after_window(self):
        a = self.make_team("A")
        day = local_date()
        TeamChallenge.objects.create(date=day - timedelta(days=7), secret_team=a)
        self.assertEqual(ensure_logo_challenge(day).secret_team, a)

    def test_secret_team_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        team = self.make_team("A")
        ensure_logo_challenge()
        with self.assertRaises(ProtectedError):
            team.delete()

    def test_command_creates_both_challenges(self):
        make_player(1)
        self.make_team("FURIA")
        call_command("ensure_daily_challenge")
        self.assertEqual((DailyChallenge.objects.count(), TeamChallenge.objects.count()), (1, 1))

    def test_command_creates_classic_even_if_logo_fails_but_exits_with_error(self):
        make_player(1)
        with self.assertRaises(Exception):
            call_command("ensure_daily_challenge")
        self.assertEqual(DailyChallenge.objects.count(), 1)


class LogoAPITests(LogoSettingsMixin, TestCase):
    SECRET = "Equipe Segredo"

    def setUp(self):
        super().setUp()
        self.secret = self.make_team(self.SECRET)
        self.others = [self.make_team(f"Time {n:02d}") for n in range(12)]
        self.challenge = TeamChallenge.objects.create(date=local_date(), secret_team=self.secret)

    def guess(self, team_id, date=None):
        return self.client.post(
            reverse("game:logo-guesses"),
            data=json.dumps({"challenge_date": date or local_date().isoformat(), "team_id": team_id}),
            content_type="application/json",
        )

    def image(self):
        return self.client.get(reverse("game:logo-image"))

    def test_page(self):
        response = self.client.get(reverse("game:logo-page"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "game/logo.html")
        self.assertContains(response, "De quem é este logo?")

    def test_navigation_marks_current_mode(self):
        logo = self.client.get(reverse("game:logo-page")).content.decode()
        classic = self.client.get(reverse("game:home")).content.decode()
        self.assertRegex(logo, r'href="/logo/" aria-current="page"')
        self.assertNotRegex(logo, r'href="/" aria-current="page"')
        self.assertRegex(classic, r'href="/" aria-current="page"')

    def test_state_initializes_cookie_and_does_not_leak_the_secret(self):
        response = self.client.get(reverse("game:logo"))
        body = response.json()
        self.assertEqual((response.status_code, body["state"], body["guesses"]), (200, "in_progress", []))
        self.assertEqual((body["blur_level"], body["attempts_to_next_level"]), (0, 10))
        self.assertIn("csguess_logo_progress", response.cookies)
        text = response.content.decode()
        for forbidden in (self.SECRET, "Secret_Team", "photo_url", "victory"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn(str(self.secret.pk), body["image_url"])

    def test_state_without_challenge_returns_503(self):
        TeamChallenge.objects.all().delete()
        response = self.client.get(reverse("game:logo"))
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (503, "challenge_unavailable"))

    def test_image_is_blurred_png_without_identifying_headers(self):
        self.client.get(reverse("game:logo"))
        response = self.image()
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/png"))
        self.assertEqual(response.content, render_logo(self.secret, 0))
        self.assertNotEqual(response.content, render_logo(self.secret, len(BLUR_RADII) - 1))
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertNotIn(self.SECRET, "".join(f"{k}:{v}" for k, v in response.items()))

    def test_image_without_cookie_is_still_blurred(self):
        self.assertEqual(self.image().content, render_logo(self.secret, 0))

    def test_tampered_cookie_does_not_unblur(self):
        self.client.get(reverse("game:logo"))
        self.client.cookies["csguess_logo_progress"] = "adulterado"
        self.assertEqual(self.image().content, render_logo(self.secret, 0))

    def test_wrong_guess_never_reveals_secret(self):
        self.client.get(reverse("game:logo"))
        response = self.guess(self.others[0].pk)
        body = response.json()
        self.assertEqual(response.status_code, 201)
        self.assertEqual((body["correct"], body["number"], body["state"]), (False, 1, "in_progress"))
        self.assertEqual(body["team"], {"id": self.others[0].pk, "name": "Time 00"})
        self.assertNotIn(self.SECRET, response.content.decode())

    def test_blur_gets_lighter_every_ten_attempts(self):
        self.client.get(reverse("game:logo"))
        first = self.image().content
        for n in range(9):
            self.assertEqual(self.guess(self.others[n].pk).json()["blur_level"], 0)
        self.assertEqual(self.image().content, first)  # 9 tentativas: ainda no nível 0
        tenth = self.guess(self.others[9].pk).json()
        self.assertEqual((tenth["blur_level"], tenth["attempts_to_next_level"]), (1, 10))
        self.assertEqual(self.image().content, render_logo(self.secret, 1))
        self.assertNotEqual(self.image().content, first)

    def test_victory_reveals_sharp_logo_and_restores(self):
        self.client.get(reverse("game:logo"))
        self.guess(self.others[0].pk)
        win = self.guess(self.secret.pk)
        body = win.json()
        self.assertEqual((win.status_code, body["correct"], body["state"]), (201, True, "completed"))
        self.assertEqual(body["victory"], {"team": {"id": self.secret.pk, "name": self.SECRET}, "attempts": 2})
        self.assertEqual(self.image().content, render_logo(self.secret, len(BLUR_RADII) - 1))
        self.assertEqual(self.guess(self.others[1].pk).json()["error"]["code"], "match_completed")

        restored = self.client.get(reverse("game:logo")).json()
        self.assertEqual((restored["state"], len(restored["guesses"])), ("completed", 2))
        self.assertEqual([g["correct"] for g in restored["guesses"]], [False, True])
        self.assertEqual(restored["victory"]["team"]["name"], self.SECRET)

    def test_duplicate_guess_rejected_and_hidden_from_search(self):
        self.client.get(reverse("game:logo"))
        self.guess(self.others[0].pk)
        self.assertEqual(self.guess(self.others[0].pk).json()["error"]["code"], "duplicate_guess")
        names = [t["name"] for t in self.client.get(reverse("game:team-search"), {"q": "time 00"}).json()["teams"]]
        self.assertEqual(names, [])

    def test_guess_requires_session(self):
        response = self.guess(self.others[0].pk)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "session_required"))

    def test_progress_does_not_carry_over_to_new_challenge(self):
        self.client.get(reverse("game:logo"))
        self.guess(self.others[0].pk)
        self.challenge.public_id = __import__("uuid").uuid4()
        self.challenge.save()
        self.assertEqual(self.client.get(reverse("game:logo")).json()["guesses"], [])

    def test_search(self):
        self.client.get(reverse("game:logo"))
        url = reverse("game:team-search")
        names = lambda q: [t["name"] for t in self.client.get(url, {"q": q}).json()["teams"]]
        self.assertEqual(names("segredo"), [self.SECRET])
        self.assertEqual(len(names("time")), 10)  # 12 equipes casam, mas só 10 voltam
        self.assertTrue(all(n.startswith("Time") for n in names("time")))
        self.assertEqual(self.client.get(url, {"q": "a"}).status_code, 400)
        self.assertEqual(self.client.get(url, {"q": "a" * 101}).status_code, 400)
        self.assertEqual(set(self.client.get(url, {"q": "time"}).json()["teams"][0]), {"id", "name"})

    def test_search_ignores_teams_without_local_logo(self):
        self.make_team("Fantasma", logo=False)
        self.client.get(reverse("game:logo"))
        self.assertEqual(self.client.get(reverse("game:team-search"), {"q": "fantasma"}).json()["teams"], [])

    def test_invalid_requests(self):
        self.client.get(reverse("game:logo"))
        post = lambda body, ct="application/json": self.client.post(reverse("game:logo-guesses"), data=body, content_type=ct)
        today = local_date().isoformat()
        cases = [
            (post("x", "text/plain"), 415, "invalid_content_type"),
            (post("não é json"), 400, "invalid_json"),
            (post(json.dumps({"challenge_date": today})), 400, "invalid_body"),
            (post(json.dumps({"challenge_date": today, "player_id": 1})), 400, "invalid_body"),
            (post(json.dumps({"challenge_date": today, "team_id": True})), 400, "invalid_team"),
            (post(json.dumps({"challenge_date": today, "team_id": "1"})), 400, "invalid_team"),
            (post(json.dumps({"challenge_date": "06/11/2026", "team_id": 1})), 400, "invalid_date"),
            (post(json.dumps({"challenge_date": today, "team_id": 999999})), 400, "invalid_team"),
        ]
        for response, status, code in cases:
            with self.subTest(code=code):
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (status, code))

    def test_stale_date_returns_409(self):
        self.client.get(reverse("game:logo"))
        response = self.guess(self.others[0].pk, (local_date() - timedelta(days=1)).isoformat())
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "challenge_changed"))

    def test_team_without_logo_cannot_be_guessed(self):
        ghost = self.make_team("Fantasma", logo=False)
        self.client.get(reverse("game:logo"))
        self.assertEqual(self.guess(ghost.pk).json()["error"]["code"], "invalid_team")

    def test_csrf_is_enforced(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("game:logo"))
        response = client.post(reverse("game:logo-guesses"), data="{}", content_type="application/json")
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (403, "csrf_failed"))

    def test_logo_and_classic_progress_are_independent(self):
        make_player(1)
        self.client.get(reverse("game:logo"))
        self.guess(self.others[0].pk)
        self.assertNotIn("csguess_classic_progress", self.client.cookies)
        self.assertEqual(len(self.client.get(reverse("game:logo")).json()["guesses"]), 1)

    def test_methods(self):
        self.assertEqual(self.client.post(reverse("game:logo")).status_code, 405)
        self.assertEqual(self.client.get(reverse("game:logo-guesses")).status_code, 405)
        self.assertEqual(self.client.post(reverse("game:logo-image")).status_code, 405)
