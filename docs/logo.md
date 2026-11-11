# Modo Logo

Adivinhe a equipe pelo logo. Tela em `/logo/`; API JSON em `/game/logo/`. A virada do dia,
o fuso (America/Fortaleza), o bloqueio de sete dias (D−6 a D+6) e o progresso em cookie
assinado seguem o modo clássico, com cookie próprio (`csguess_logo_progress`).

## Desfoque no servidor

O logo original **nunca** é enviado ao navegador antes do acerto: `GET /game/logo/image/`
devolve um PNG já desfocado, no nível calculado pelo cookie assinado (não pelo cliente).
A cada **10 tentativas** o raio diminui: `BLUR_RADII = (26, 15, 7, 0)` em `game/logo.py`
(0 tentativas = muito desfocado; 30 ou mais, ou acerto = nítido). Ajuste `BLUR_STEP` e
`BLUR_RADII` para mudar a dificuldade. As respostas JSON nunca trazem `photo_url` nem o nome
da equipe secreta antes da vitória, e a URL da imagem não contém o ID da equipe.

## Logos locais

`Team.photo_url` guarda o link de origem (Liquipedia). Para o jogo, os arquivos são baixados
uma vez e reduzidos (lado maior de 600 px) em `game/team_logos/<id>.png`, fora de `static/`
para não ficarem públicos (o nome do arquivo original revelaria a equipe).

```bash
python manage.py fetch_team_logos           # baixa os que faltam (1 s entre downloads)
python manage.py fetch_team_logos --force   # refaz todos
```

Só participam do sorteio e da busca as equipes com `photo_url` preenchido **e** arquivo local.
Ao cadastrar uma equipe nova ou trocar a foto, rode o comando (use `--force` para substituir).
O diretório precisa estar na imagem Docker (ele é copiado com o código).

## Desafio diário

`ensure_daily_challenge` agora garante os dois desafios (Clássico e Logo). Um modo sem
candidatos não impede o outro, mas o comando termina com erro. O sorteio do logo usa
`pg_advisory_xact_lock` próprio e `secrets.choice`. Uma equipe sorteada não pode ser apagada
(`PROTECT`).

## API

| Rota | Descrição |
|---|---|
| `GET /game/logo/` | Estado: tentativas, `blur_level`, `attempts_to_next_level`, `image_url`; `victory` só após acertar |
| `GET /game/logo/image/` | PNG desfocado conforme o progresso |
| `GET /game/teams/search/?q=` | Sugestões (mín. 2 caracteres, até 10), sem as já tentadas |
| `POST /game/logo/guesses/` | `{"challenge_date": "AAAA-MM-DD", "team_id": 1}`; 201 com `correct`, `number`, nível e imagem |

Erros seguem o formato do clássico (`session_required`, `duplicate_guess`, `match_completed`,
`challenge_changed`, `invalid_team`, CSRF etc.).

## Créditos

Logos e marcas pertencem às respectivas equipes; as imagens vêm da
[Liquipedia](https://liquipedia.net/counterstrike/) ([CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/)).
O crédito aparece na ajuda da tela.
