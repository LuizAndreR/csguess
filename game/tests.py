from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Player


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
