# Referência técnica

[Voltar ao README](../README.md)

## Banco e configuração

`Player.team` referencia `Team`: um jogador pode ter uma equipe ou nenhuma, e uma equipe pode ter vários jogadores. Sem vínculo, a interface mostra `No team`. Aposentados devem ficar sem equipe. Times referenciados por jogadores ou desafios têm exclusão protegida.

No Docker, o web conecta em `db:5432`. A porta do PostgreSQL publicada no host é definida por `POSTGRES_PORT` (padrão `5434`). Alterar credenciais no `.env` não modifica um banco já inicializado. Para outro domínio, ajuste `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` e recrie o web.

## Desafios e progresso

- `ensure_daily_challenge` prepara os dois modos para a data em `America/Fortaleza`. Não refaz desafios existentes nem preenche dias passados sem data explícita.
- O sorteio impede repetição do jogador ou time entre D−6 e D+6. Locks do PostgreSQL serializam a criação; se faltarem candidatos, o comando registra erro.
- No Clássico, o desafio guarda uma cópia da resposta secreta. Busca e tentativas usam os cadastros atuais; faça manutenção dos perfis com o jogo parado para evitar mudanças de pistas durante partidas.
- As tentativas ficam apenas nos cookies assinados e HttpOnly de cada modo, sem sincronização entre dispositivos. A assinatura protege a integridade; não criptografa os IDs tentados.
- No Clássico, a nacionalidade é liberada após 10 erros e o time após 15. As dicas são opcionais e desbloqueadas pelo servidor.
- No Logo, o desfoque diminui a cada 10 tentativas; após 30, ou ao acertar, a imagem fica nítida. A imagem já é processada no servidor.

Para participar do Clássico, o perfil precisa de nick e nome, nacionalidade, função válida, status de carreira, classificação de Major e atividade comparável (`AAAA – AAAA` ou `AAAA – Present`, início a partir de 1900). Jogadores sem foto ou equipe podem participar. Perfis inválidos são ignorados com o motivo nos logs.

## Importação JSON v2

O documento deve conter `schema_version: 2`, `exported_at` em ISO 8601 com fuso e uma lista não vazia `players`. Cada jogador exige estes 13 campos:

| Campos | Formato |
| --- | --- |
| `nick`, `name`, `source`, `source_id` | Texto obrigatório |
| `nationalities` | Lista de códigos de duas letras, sem duplicatas |
| `career_status` | `active`, `inactive`, `retired` ou `unknown` |
| `current_team` | Nome da equipe; `null`, vazio ou espaços viram `No team` |
| `roles` | Lista com `rifle`, `awp` ou `igl`, sem duplicatas; cargos de staff não são aceitos |
| `years_active` | Texto do período informado |
| `photo_url`, `source_url` | URL ou string vazia |
| `is_major_winner` | Booleano JSON: `true` ou `false` |
| `source_collected_at` | Data com fuso ou `null` |

`current_team` é convertido em uma referência à equipe. A identidade de importação é `source + source_id`: reimportar atualiza os correspondentes, preserva IDs e não remove registros ausentes. A gravação é transacional; `--dry-run` só valida. Use `--report caminho.json` para gerar um relatório separado.

## Logos

`fetch_team_logos` usa `Team.photo_url`. Se o campo estiver vazio, procura o nome da equipe no [catálogo](../game/data/team_logos.json) e salva a URL após validar o download. URLs existentes são preservadas; equipes desconhecidas precisam de cadastro no Admin ou de uma entrada no catálogo.

Os PNGs ficam em `game/team_logos/`, nomeados pelo hash da URL e fora dos arquivos públicos. No Docker, essa pasta usa o volume `team_logos`. O modo Logo exige URL e arquivo local. Use `fetch_team_logos --force` para refazer os downloads.

No Clássico, o PNG aparece ao lado do nome da equipe após uma tentativa. A rota da imagem verifica o progresso assinado; se faltar imagem, o nome continua visível.

## API

| Método e rota | Uso |
| --- | --- |
| `GET /health/` | Verificar aplicação e banco |
| `GET /game/classic/` | Estado e inicialização do progresso do Clássico |
| `GET /game/players/search/?q=...` | Buscar jogadores |
| `POST /game/classic/guesses/` | Enviar `challenge_date` e `player_id` |
| `GET /game/classic/players/<player_id>/team-logo/` | PNG da equipe de um jogador já tentado |
| `GET /game/logo/` | Estado e inicialização do progresso do Logo |
| `GET /game/teams/search/?q=...` | Buscar equipes |
| `POST /game/logo/guesses/` | Enviar `challenge_date` e `team_id` |
| `GET /game/logo/image/` | Imagem no nível de desfoque atual |

Carregue primeiro o estado do modo e preserve os cookies. POSTs exigem `Content-Type: application/json`, `X-CSRFToken` e data `AAAA-MM-DD`. IDs devem ser inteiros positivos. As buscas exigem pelo menos dois caracteres normalizados e retornam até dez sugestões.

Tentativas válidas retornam 201 com comparação, número e estado; o acerto inclui `victory`. Repetições e tentativas após vitória são rejeitadas. As comparações e o desbloqueio das dicas são calculados no servidor.

Erros usam `{"error":{"code":"...","message":"..."}}`. Os principais são 400 para entrada inválida, 403 para CSRF, 409 para progresso ausente, repetição ou troca de dia, e 503 para desafio indisponível ou falha de banco. Na troca de dia, recarregue o estado. `/health/` não garante a existência dos desafios.

## Verificações

```bash
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py makemigrations --check --dry-run
docker compose exec -T web python manage.py test --noinput
```

Os testes usam PostgreSQL e um banco separado, criado e removido pelo runner. O usuário do banco precisa de permissão para criar bancos.
