"""Importação atômica e idempotente do contrato Player v2."""
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from game.models import Player
from game.normalization import normalize_team


FIELDS = {"nick", "name", "nationalities", "career_status", "current_team", "roles", "years_active",
          "photo_url", "is_major_winner", "source", "source_id", "source_url", "source_collected_at"}
STAFF_ROLES = ("coach", "analyst", "manager", "streamer", "staff", "owner", "director", "head of")


def parse_document(document):
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 2:
        raise CommandError("Exigido contrato schema_version=2; v1 não contém apuração de campeões")
    exported_at = document.get("exported_at")
    try:
        exported_at = datetime.fromisoformat(exported_at)
    except (ValueError, TypeError) as exc:
        raise CommandError("exported_at deve ser uma data ISO 8601 com timezone") from exc
    if timezone.is_naive(exported_at):
        raise CommandError("exported_at deve incluir timezone")
    records = document.get("players")
    if not isinstance(records, list) or not records:
        raise CommandError("players deve ser uma lista não vazia")
    identities = set()
    parsed = []
    for index, row in enumerate(records, 1):
        prefix = f"Registro {index}"
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise CommandError(f"{prefix}: campos incompatíveis com o contrato v2")
        if type(row["is_major_winner"]) is not bool:
            raise CommandError(f"{prefix}: is_major_winner deve ser booleano real")
        for field in ("nick", "name", "source", "source_id"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise CommandError(f"{prefix}: {field} deve ser texto não vazio")
        identity = (row["source"], row["source_id"])
        if identity in identities:
            raise CommandError(f"{prefix}: identidade source + source_id duplicada")
        identities.add(identity)
        row = dict(row)
        row["current_team"] = normalize_team(row["current_team"])
        if row["career_status"] == "retired" and row["current_team"] != "No team":
            raise CommandError(f"{prefix}: aposentado deve ter current_team No team")
        if not isinstance(row["roles"], list) or any(not isinstance(role, str) for role in row["roles"]):
            raise CommandError(f"{prefix}: roles deve ser lista de strings")
        if any(any(staff in role.casefold() for staff in STAFF_ROLES) for role in row["roles"]):
            raise CommandError(f"{prefix}: cargo de staff não pode ser importado como função de jogador")
        values = dict(row)
        if values["source_collected_at"] is not None:
            try:
                date = datetime.fromisoformat(values["source_collected_at"])
            except (ValueError, TypeError) as exc:
                raise CommandError(f"{prefix}: source_collected_at inválido") from exc
            if timezone.is_naive(date):
                raise CommandError(f"{prefix}: source_collected_at deve incluir timezone")
            values["source_collected_at"] = date
        parsed.append(values)
    return parsed


def atomic_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class Command(BaseCommand):
    help = "Importa Player v2 por source + source_id; atualiza os existentes sem apagar registros."

    def add_arguments(self, parser):
        parser.add_argument("input", type=Path)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--report", type=Path)

    def handle(self, *args, **options):
        path = options["input"]
        if options["report"] and path.resolve() == options["report"].resolve():
            raise CommandError("Relatório não pode substituir o arquivo de entrada")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError(f"Arquivo JSON não pôde ser lido: {exc}") from exc
        records = parse_document(document)
        if connection.vendor != "postgresql":
            raise CommandError("Importação exige o PostgreSQL configurado no jogo")
        changes = []
        with transaction.atomic():
            if options["dry_run"]:
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
            before = Player.objects.count()
            for values in records:
                query = Player.objects if options["dry_run"] else Player.objects.select_for_update()
                existing = query.filter(source=values["source"], source_id=values["source_id"]).first()
                instance = existing or Player()
                changed = any(getattr(instance, field) != value for field, value in values.items())
                for field, value in values.items():
                    setattr(instance, field, value)
                try:
                    instance.full_clean()
                except ValidationError as exc:
                    raise CommandError(f"{values['source']} / {values['source_id']}: {exc.message_dict}") from exc
                action = "created" if existing is None else "updated" if changed else "unchanged"
                changes.append((instance, action))
            # Todos os registros são validados antes da primeira gravação.
            for instance, action in changes:
                if not options["dry_run"] and action != "unchanged":
                    instance.save()
            after = Player.objects.count()
        report = {"schema_version": 2, "input": str(path), "dry_run": options["dry_run"],
                  "database": {k:connection.settings_dict[k] for k in ("HOST", "PORT", "NAME")},
                  "before": before, "after": after, "total_read": len(records),
                  "created": sum(action == "created" for _, action in changes),
                  "updated": sum(action == "updated" for _, action in changes),
                  "unchanged": sum(action == "unchanged" for _, action in changes),
                  "major_winners": sum(instance.is_major_winner for instance, _ in changes),
                  "retired": sum(instance.career_status == "retired" for instance, _ in changes),
                  "players": [{"nick": p.nick, "source": p.source, "source_id": p.source_id,
                               "django_id": p.pk, "action": action} for p, action in changes]}
        if options["report"]:
            atomic_report(options["report"], report)
        self.stdout.write(self.style.SUCCESS(
            f"{'Validação' if options['dry_run'] else 'Importação'} v2: {len(records)} lidos; "
            f"{report['created']} novos; {report['updated']} atualizados; {report['unchanged']} inalterados. "
            f"Banco: {before} → {after}."))
        return None
