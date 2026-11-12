# API do modo clássico

O banco continua sendo o PostgreSQL configurado em `.env`. Sem DRF, Redis ou Celery.
Todas as datas do jogo usam **America/Fortaleza**, explicitamente, mesmo que o
fuso ativo de uma requisição seja outro. A virada ocorre às 00:00 (UTC−03:00).

## Desafios e snapshots

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py ensure_daily_challenge
.venv/bin/python manage.py ensure_daily_challenge --date 2026-11-06
```

Sem `--date`, garante somente hoje; não preenche dias perdidos. Reexecuções retornam
o UUID público existente, sem novo sorteio nem atualização de snapshots. GET nunca
chama esse serviço. Se o desafio não estiver pronto, a API responde 503.

O serviço adquire um `pg_advisory_xact_lock` global antes de consultar o histórico.
Dentro da mesma transação, exclui os jogadores escolhidos entre D−6 e D+6 (inclusive),
sorteia com `secrets.choice` e grava o desafio com os dados do jogador secreto. Assim, protege datas
concorrentes diferentes e preenchimento de lacunas com desafios futuros. A data é
única no banco. Um jogador de 06/11 pode voltar em 13/11, mas não entre 07 e 12/11.
Todos os criadores de desafios devem usar esse serviço; escritas SQL manuais não
recebem a garantia de distância entre datas. Não há rotina de substituição.

A busca e as tentativas consultam os perfis comparáveis diretamente em `game_player`,
inclusive jogadores bloqueados para sorteio. A restrição de sete dias afeta apenas a seleção secreta.
Aposentados, inativos, reservas, jogadores sem foto ou sem equipe participam.
Exigem-se nick/nome não vazios, pelo menos uma nacionalidade válida, pelo menos uma
função em `rifle`, `awp`, `igl`, status válido e booleano real de Major.
`unknown` é um status explícito e comparável; não é condição no elenco.

Atividade exige `AAAA – AAAA` ou `AAAA – Present`, com travessão curto U+2013,
ano inicial >= 1900 e fim >= início. Perfis inválidos são excluídos da busca, das tentativas e do sorteio,
com ID e motivo no logger `game.services`; não se alteram os registros. Não se
relaxa o bloqueio se faltarem candidatos: erro registrado e comando termina com
código diferente de zero. Corrija os perfis de origem antes de repetir o comando.
Não se convertem funções antigas como `entry`/`lurk` por suposição.

Não existe cópia diária de todos os jogadores. `game_dailyplayer` foi removida na
migração 0006. Busca, envio de tentativas e restauração do progresso usam os dados
atuais de `Player`, com os mesmos validadores de elegibilidade do sorteio. Novos
cadastros válidos ficam disponíveis sem recriar o desafio.

A política de manutenção é atualizar os cadastros manualmente com o jogo parado.
Alterações em Player passam a valer imediatamente na busca e nas características
das tentativas, inclusive ao restaurar uma partida. Por isso, a aplicação não
promete pistas imutáveis se houver edição de jogadores durante uma partida.

Somente o jogador secreto mantém uma cópia de suas características no campo
`secret_snapshot` de `game_dailychallenge`. Essa cópia não exige outra tabela e
preserva a resposta do desafio já sorteado. Antes do acerto, somente as dicas
desbloqueadas de nacionalidade e time podem ser retornadas, nos limites abaixo.
A migração 0006 não altera esse campo, os jogadores, os desafios, o histórico de
sorteios ou o cookie de progresso. Não há alteração no bloqueio de sete dias.

A equipe atual é a relação `Player.team` (chave estrangeira opcional para `Team`, com
`on_delete=PROTECT`). `Team` tem `id`, `name` (único, sem espaços nas pontas; o nome
`No team` é reservado) e `photo_url`. Sem equipe (`team` nulo) o jogador aparece como
`No team`. Vários jogadores compartilham a mesma equipe, e renomear ou trocar a foto de
uma equipe vale para todos. Aposentados devem ficar sem equipe; cadastro e importação
rejeitam equipe associada a aposentado. A propriedade `Player.current_team` devolve o
nome (ou `No team`) e é o valor usado no snapshot e na comparação, então o contrato
JSON da API e os snapshots já gravados em `secret_snapshot` não mudaram. A importação
JSON v2 continua usando o campo texto `current_team` e cria/reutiliza a `Team` pelo nome.
A migração 0009 copiou os textos existentes para `Team`; a 0010 removeu a coluna antiga.
Para trocar um jogador de time, edite o campo Equipe no Admin (ou reimporte); não é
necessário apagar equipes. Equipes com jogadores não podem ser removidas.
Como no Django, operações bulk/update ignoram validadores; devem validar antes.

## Progresso somente no navegador e CSRF

O progresso do clássico fica exclusivamente no cookie `csguess_classic_progress`
do navegador. Não existem mais tabelas de partidas ou tentativas. O cookie contém
somente o UUID público do desafio e a lista ordenada de IDs já tentados. Não contém
resposta secreta, pistas antecipadas ou cópia do snapshot secreto.

O cookie é assinado com a API de [assinatura do Django](https://docs.djangoproject.com/en/5.2/topics/signing/),
HttpOnly e SameSite=Lax, com duração de 14 dias e Secure em HTTPS. Uma assinatura
inválida é descartada. O UUID vincula o progresso ao desafio: outro dia ou um reset
do desafio inicia uma nova partida. A assinatura protege a integridade; os dados
assinados não são criptografados (contêm apenas os IDs que o próprio jogador tentou).

Primeiro carregue `GET /game/classic/`, que inicializa esse cookie e o `csrftoken`.
Mantenha ambos e envie o token CSRF no header `X-CSRFToken` do POST. A proteção CSRF
padrão permanece ativa. Requisições sem progresso inicializado recebem
`session_required`. As sessões administrativas do Django continuam independentes;
o clássico não usa nem cria `django_session` para armazenar progresso.

Cada dispositivo/perfil do navegador tem seu próprio cookie. Limpar cookies,
usar janela anônima ou trocar de navegador começa uma partida vazia. Não há
recuperação do histórico no servidor nem sincronização entre dispositivos. As
pistas são recalculadas no servidor a partir dos IDs assinados, dos dados atuais
de Player e da resposta secreta preservada no desafio, com o mesmo contrato JSON.

A migração 0005 remove `game_classicmatch` e `game_guess`, apagando as tentativas
legadas. Não altera Player, o jogador secreto, desafios existentes ou os snapshots.
A migração 0007 remove o contador de requisições `game_ratelimitbucket`.
As tabelas padrão do Django/Admin são preservadas.

```bash
curl -c /tmp/csguess-cookies http://127.0.0.1:8000/game/classic/
curl -b /tmp/csguess-cookies 'http://127.0.0.1:8000/game/players/search/?q=getright'
# Substitua TOKEN pelo csrftoken recebido e 123 pelo ID de uma sugestão.
curl -b /tmp/csguess-cookies -H 'X-CSRFToken: TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{"challenge_date":"2026-11-06","player_id":123}' \
  http://127.0.0.1:8000/game/classic/guesses/
```

IDs e dados abaixo são exemplos ilustrativos.

### GET /game/classic/

```json
{
  "challenge_date": "2026-11-06",
  "challenge_id": "6bea760e-e8f6-4195-bbb3-d8abe631a41f",
  "next_rollover": "2026-11-07T00:00:00-03:00",
  "state": "in_progress",
  "guesses": []
}
```

`guesses` contém as respostas anteriores, em ordem de tentativa. Após acertar,
`state` passa a `completed` e `victory` contém o snapshot público do jogador e
`attempts`. Antes do acerto, a resposta não inclui a identidade secreta; somente
as dicas desbloqueadas podem revelar nacionalidade e time.

### Dicas após 10 e 15 erros

Somente tentativas válidas e diferentes, aceitas no cookie assinado, contam.
Após 10 erros, GET do estado e POST de tentativa passam a incluir:

```json
{"hints": {"nationalities": ["BR"]}}
```

Após 15 erros, o mesmo campo inclui também o time:

```json
{"hints": {"nationalities": ["BR"], "current_team": "No team"}}
```

São exemplos fictícios. Os valores vêm de `DailyChallenge.secret_snapshot`,
salvo no PostgreSQL no sorteio, mantendo a mesma resposta usada nas comparações.
Antes de cada limite, a respectiva dica não é enviada. Busca e HTML não contêm
esses valores. No acerto, retorna-se `victory` e omite-se `hints`.

A tela mostra dois botões desde o início. Botões bloqueados têm aparência
apagada e informam quantas tentativas faltam. Após a liberação pelo servidor,
o usuário pode clicar para revelar ou ocultar cada dica abaixo dos botões.
Recarregar preserva o desbloqueio pelo cookie, mas pede um novo clique para
mostrar os valores. Outro navegador ou novo desafio começa com dicas bloqueadas.
Não há tabelas novas nem gravação de tentativas no banco.

A interação foi inspirada nos botões de dicas do
[Onepiecedle clássico](https://onepiecedle.net/classic), adaptada ao CSGuess.

### GET /game/players/search/?q=...

Consulta nick e nome completo diretamente em Player, com casefold, remoção de acentos e de
separadores: `getright` encontra `GeT_RiGhT`. A letra `o` e o número `0` são
equivalentes na busca: `ropz` encontra `r0pz`, e o contrário também funciona.
O nick original e o ID de cada jogador são preservados. Exige pelo menos dois caracteres
alfanuméricos normalizados e no máximo 100 caracteres de entrada. No máximo dez
sugestões, ordenadas por correspondência exata de nick/nome, início de nick e demais
ocorrências; desempate por nick normalizado, nome normalizado e ID. Nicks repetidos
são preservados. Jogadores já enviados como tentativa pelo navegador atual são
ocultados das sugestões somente naquele desafio, inclusive após recarregar a
página. Outras sessões e o próximo desafio continuam podendo encontrá-los.
Nenhuma consulta externa é executada.

```json
{"players":[{"id":123,"nick":"GeT_RiGhT","name":"Christopher Alesund","photo_url":""}]}
```

O campo `name` da busca contém as duas primeiras palavras. O nome completo do
cadastro permanece intacto. Não inclui nacionalidade, equipe ou outras pistas.

### POST /game/classic/guesses/

Aceita somente objeto JSON com `challenge_date` ISO e `player_id` inteiro positivo
(booleans não são inteiros aceitos). Valida a existência e a elegibilidade atual do jogador.
Retorno 201, sem limite total de tentativas:

```json
{
  "player": {
    "id": 123, "nick": "Exemplo", "name": "Nome Completo Jogador",
    "display_name": "Nome Completo", "photo_url": "",
    "nationalities": ["BR"], "career_status": "active",
    "current_team": "No team", "roles": ["rifle"],
    "is_major_winner": false, "years_active": "2010 – 2020"
  },
  "comparison": {
    "player": "incorrect", "nationalities": "partial",
    "career_status": "correct", "current_team": "incorrect",
    "roles": "correct", "is_major_winner": "correct",
    "activity": {
      "start": {"status": "incorrect", "direction": "up"},
      "end": {"status": "incorrect", "direction": "ongoing"}
    }
  },
  "number": 1, "correct": false, "state": "in_progress"
}
```

Acerto depende de identidade interna. Nacionalidades e funções com conjuntos
iguais retornam `correct`, interseção parcial `partial`, disjuntos `incorrect`.
Status, equipe e booleano usam igualdade (`false`/`false` também é `correct`).
Ausência de equipe retorna sempre `No team`.

Atividade tem resultados independentes para início/fim: `direction` é `null`
se correto, `up` se o ano secreto é maior, `down` se menor. Para fim aberto,
`ongoing` significa secreto ainda em andamento; `ended` significa secreto com fim
definido e tentativa `Present`. Ambos `Present` são corretos. Nunca se fornece o
ano secreto como pista nem se converte `Present` para o ano atual.

As respostas erradas não incluem `victory`. No acerto, inclui-se
`"victory": {"player": { ...dados públicos do snapshot... }, "attempts": 2}`.
O estado GET reconstrói esse resumo a partir do cookie após recarregar a página.

A API rejeita jogadores repetidos e novas tentativas após o acerto usando os IDs
assinados do cookie. O front-end bloqueia clique duplo, usa Web Locks quando
disponível para coordenar requisições entre abas, reconcilia o estado após cada
POST e usa BroadcastChannel para atualizar as demais abas do mesmo navegador.

Sem armazenamento de partidas no servidor, não há mais unicidade/lock transacional
de tentativas no PostgreSQL. Clientes HTTP que deliberadamente copiam um cookie
antigo ou enviam requisições paralelas fora dessa coordenação podem repetir um
estado anterior. Limpar/restaurar um cookie permite recomeçar, mas não altera o
desafio compartilhado. Isso é uma consequência da política de progresso local;
não há ranking, limite global de tentativas ou sincronização de contas nesta versão.
O lock PostgreSQL do sorteio diário e o bloqueio de sete dias permanecem iguais.

### Erros

Formato comum: `{"error":{"code":"duplicate_guess","message":"..."}}`.

| HTTP | Exemplos de códigos |
| --- | --- |
| 400 | invalid_query, invalid_json, invalid_body, invalid_date, invalid_player |
| 403 | csrf_failed |
| 405 | method_not_allowed (header Allow) |
| 409 | challenge_changed, duplicate_guess, match_completed, session_required |
| 413 | invalid_body (mais de 4096 bytes) |
| 415 | invalid_content_type |
| 503 | challenge_unavailable, temporarily_unavailable |

Ao receber `challenge_changed`, descarte a seleção antiga e recarregue
`/game/classic/`. O servidor não joga automaticamente no novo dia. Dados internos
do banco não são incluídos nos erros; respostas da API usam `Cache-Control: no-store`.

Não há limite de requisições por IP na aplicação, nem contadores persistidos no
banco. A infraestrutura de hospedagem fica responsável pelos controles de tráfego.
As rotas JSON podem ser chamadas diretamente por clientes HTTP, mesmo sendo usadas
pelo front-end; o front-end não é uma barreira de acesso. CSRF, validação das
requisições e assinatura do progresso continuam ativos.

## Agendamento dedicado com systemd de usuário

Os arquivos em `deploy/` estão prontos para este checkout Linux. Ajuste
`WorkingDirectory` e `ExecStart` se mover o projeto; não copie segredos para a unit.
A unit chama o comando no container web, que deve estar iniciado e migrado. A configuração `.env` é fornecida pelo Compose. Para execução de Django no host, substitua ExecStart pelo caminho de `.venv/bin/python manage.py ensure_daily_challenge`. O cron externo descrito no README é a opção recomendada para Docker.

```bash
mkdir -p ~/.config/systemd/user
cp deploy/csguess-daily.service deploy/csguess-daily.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now csguess-daily.timer
systemctl --user start csguess-daily.service
systemctl --user list-timers csguess-daily.timer
journalctl --user -u csguess-daily.service -n 50
```

Para manter a rotina ativa sem login, o administrador deve habilitar linger para
seu usuário (`loginctl enable-linger "$USER"`). O servidor web não inicia timers.
O timer chama o comando a cada minuto, incluindo **00:00 America/Fortaleza**,
com precisão de um segundo. Isso garante recuperação após indisponibilidade do
banco; `Persistent=true` cobre retorno do serviço de timers após desligamento.
Somente o desafio da data local atual é criado. Se a máquina estiver desligada,
a criação ocorre ao voltar; não existe garantia de execução durante a indisponibilidade.

Verificação de idempotência: execute o comando duas vezes e confira o mesmo UUID.
Para interromper apenas a rotina: `systemctl --user disable --now csguess-daily.timer`.
Nenhum volume precisa ser recriado. A configuração é entregue no repositório;
a instalação/ativação no gerenciador de serviços do host é uma etapa operacional.

## Validação

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --check
.venv/bin/python manage.py test --noinput
```

A suíte usa PostgreSQL real e banco de teste separado. Cobre validação e
persistência de Player e, para dicas, limites de 10/15 erros, tentativas inválidas
ou repetidas, isolamento entre navegadores, vitória, novo dia e proteção dos
valores antes da liberação. O teste opcional `game.test_hints_browser` cobre os
botões bloqueados, contagem, clique e teclado para revelar/ocultar, recarga e
visual desktop/celular. Veja como ativá-lo no README. Não modificar jogadores
reais para criar fixtures.
