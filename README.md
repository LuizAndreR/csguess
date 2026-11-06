# csguess

Jogo diário e colaborativo de adivinhação sobre jogadores profissionais de Counter-Strike. O modo clássico possui tela oficial em templates Django integrada ao back-end JSON: desafios diários, sessões, busca e tentativas. Inclui cadastro de jogadores, Django Admin e importação JSON v2. Veja [API, snapshots e rotina diária](docs/classic.md).

## Execução recomendada: Docker Compose

Acesse **http://localhost:8000/**. `/classic/` é um alias da página HTML;
`/game/classic/` continua sendo o endpoint JSON. O visual segue o arquivo
`csguess-tela-classico-v1.html`, preservado na raiz, sem o editor ou jogadores de demonstração.

Se ainda não tiver `.env`, copie `.env.example` e defina SECRET_KEY e as credenciais
PostgreSQL. **Não substitua o `.env` existente.** A imagem exclui `.env`, Git,
ambiente virtual e configurações locais; os segredos entram somente em runtime.
O Compose preserva o serviço db, as credenciais, o volume `postgres_data` e a porta
externa `POSTGRES_PORT` (5433 por padrão). Não use `down -v`.

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail=80 web
curl --fail http://localhost:8000/health/
```

O `web` aguarda db saudável, aplica migrações, executa collectstatic e garante o
desafio atual **uma vez por container**, antes do master Gunicorn. Esses passos não
rodam por worker. Se faltarem jogadores comparáveis, o comando registra o erro e
o web continua disponível para exibir a indisponibilidade e permitir recuperação.
Migrações ou collectstatic com erro impedem a inicialização. O healthcheck verifica
HTTP e conexão ao banco, retornando apenas status, sem detalhes internos. WhiteNoise
serve CSS, JS e imagens locais mesmo com DEBUG=False, conforme sua
[configuração oficial para Django](https://whitenoise.readthedocs.io/en/stable/django.html).

Comandos de manutenção, sempre na raiz do projeto:

```bash
# Reaplicar migrações ou verificar sua situação
docker compose exec -T web python manage.py migrate --noinput
docker compose exec -T web python manage.py migrate --check
# Preparar estáticos explicitamente
docker compose exec -T web python manage.py collectstatic --noinput
# Criar superusuário interativamente
docker compose exec web python manage.py createsuperuser
# Verificar aplicação e rodar testes em banco separado
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py test --noinput
# Logs em stdout/stderr
docker compose logs -f web db
# Reconstruir após mudanças (sem bind mount de fontes)
docker compose up --build -d web
# Parar mantendo dados e containers
docker compose stop
# Alternativa: remover somente containers/rede, preservando volume
docker compose down
```

Dentro do web, `DB_HOST=db` e `DB_PORT=5432` têm precedência sobre os valores
`POSTGRES_HOST/PORT` usados no host. `ALLOWED_HOSTS` deve incluir localhost e
127.0.0.1; `CSRF_TRUSTED_ORIGINS` inclui http://localhost:8000 e
http://127.0.0.1:8000. Para outro domínio, ajuste ambos no `.env` e recrie o web.
A porta 8000 só é publicada no loopback local. Gunicorn e WhiteNoise estão fixados
em requirements.txt. Não há scheduler, Node ou framework de front-end na imagem.

### Rotina diária no Docker

Prefira **cron externo**, com uma única entrada (modelo em
`deploy/csguess-docker.cron`). Abra `crontab -e` e acrescente a linha do arquivo,
ajustando os caminhos do checkout e do executável Docker (`command -v docker`).
Não substitua outras entradas do seu crontab.

A verificação a cada minuto inclui 00:00 America/Fortaleza, independentemente do
fuso do cron: quem determina a data é o serviço Django. O mesmo comando recupera
o desafio atual após indisponibilidade do web/banco, sem preencher dias perdidos.
Se o host estiver desligado, recupera no primeiro minuto depois de voltar.
Não há terceiro container nem scheduler nos workers web.

```bash
# Primeira execução e verificação de idempotência (mesmo UUID)
docker compose exec -T web python manage.py ensure_daily_challenge
docker compose exec -T web python manage.py ensure_daily_challenge
# Conferir entrada instalada e resultados
crontab -l
tail -n 30 daily-challenge.log
```

A configuração fica pronta no repositório; **instalar a entrada no cron é um passo
manual do host**. Escolha somente cron ou o timer systemd alternativo, não ambos.
O timer fornecido também chama o comando no container web. Não é necessário
modificar modelos nem dados dos jogadores para iniciar a rotina.

### Comportamento e validação da tela

Busca com debounce de 300 ms, cancelamento de respostas antigas e seleção por
mouse/teclado. Tentativas usam ID, data e CSRF; o navegador apenas apresenta os
resultados calculados pelo servidor. Tentativa mais recente no topo, vitória,
restauração pelo cookie local do navegador, ajuda em modal, silhueta para fotos ausentes/falhas e rolagem
horizontal restrita à tabela com a coluna Jogador fixa. O countdown usa
`next_rollover` e sincroniza o relógio pelo header Date quando disponível.
A tela recarrega na virada; falhas de estado são repetidas com intervalo crescente
de 5 até 60 segundos. Após erro de rede no POST, restaura o cookie antes de permitir reenviar.

As tentativas ficam somente no navegador, em cookie assinado e HttpOnly; não
são salvas no PostgreSQL. Outro dispositivo começa com a tabela vazia. Limpar os
cookies apaga o progresso local. A migração 0005 remove as tabelas antigas de
partidas/tentativas e zera esse histórico legado, preservando jogadores, desafios
e snapshots. Veja [política de armazenamento](docs/classic.md).

A migração 0006 remove `game_dailyplayer`: busca e tentativas consultam diretamente
`game_player`. Os cadastros serão atualizados manualmente, com o sistema parado.
Mudanças passam a valer também ao restaurar tentativas. Somente a resposta secreta
permanece copiada dentro do próprio desafio, sem uma tabela adicional. Remover a
base diária não apaga jogadores, desafios ou o progresso salvo nos navegadores.

A migração 0007 remove `game_ratelimitbucket`. Não há limite de requisições por IP
implementado no Django; o controle de tráfego fica na hospedagem. As rotas JSON
continuam acessíveis por HTTP diretamente, além do uso pelo front-end. CSRF,
validação de entradas e cookies assinados permanecem ativos.

Os testes comuns não exigem navegador. Os testes opcionais em Chrome usam
Playwright apenas como ferramenta de desenvolvimento e PostgreSQL de testes,
sem alterar a resposta real do dia:

```bash
# No host, com ambiente Python e PostgreSQL disponíveis
.venv/bin/python -m pip install --target /tmp/csguess-browser-runtime playwright
PYTHONPATH=/tmp/csguess-browser-runtime CSGUESS_BROWSER_TESTS=1 \
  .venv/bin/python manage.py test game.test_browser --noinput
```

Por padrão usa `/opt/google/chrome/chrome`; ajuste `CSGUESS_CHROME_PATH` se necessário.
Não é dependência da aplicação nem exige Node. Os testes geram capturas em
`/tmp/csguess-desktop.png` e `/tmp/csguess-mobile.png`. Créditos do ícone AK-47 em
[docs/assets.md](docs/assets.md) e na ajuda da tela.

## Tecnologias

Python **3.12** (validado com 3.12.3), Django **5.2.19 LTS**, Psycopg **3.3.8** e PostgreSQL **17**. As dependências diretas e transitivas estão fixadas em `requirements.txt`; o extra `psycopg[binary]` instala o binário da mesma versão do driver. A execução recomendada usa Docker Compose com web (Gunicorn/WhiteNoise, Python 3.12.13 slim, usuário sem privilégios) e db (PostgreSQL). A execução de Django no host continua disponível.

Referências de compatibilidade e suporte: [Django](https://www.djangoproject.com/download/), [Psycopg](https://www.psycopg.org/psycopg3/docs/basic/install.html) e [PostgreSQL](https://www.postgresql.org/support/versioning/).

## Estrutura

```text
config/                    Configuração Django, URLs, ASGI e WSGI
game/                      App, Player, Admin, página inicial e testes
  migrations/              Migrações versionadas
  templates/game/          Base e tela oficial do clássico
  static/game/             CSS, JavaScript e ícones locais
deploy/                    Inicialização web, cron e timer alternativo
docs/                      Contrato da API e créditos dos assets
templates/base.html        Template compartilhado
static/game/css/            CSS
static/game/js/             JavaScript
compose.yaml               Serviços web e db, volume PostgreSQL preservado
requirements.txt           Dependências Python fixadas
.env.example               Exemplo de configuração sem credenciais reais
manage.py                  Comandos Django
```

## Instalação local

Requisitos: Python 3.12 com suporte a `venv`, Docker Engine/Desktop em execução e Docker Compose v2 com suporte a `--wait`. Comandos para Linux/macOS, na raiz do repositório:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Edite `.env`: cole a chave gerada em `SECRET_KEY` e escolha uma senha local para `POSTGRES_PASSWORD`. Não versione esse arquivo. Se ele já existir, preserve e confira sua configuração antes de copiar o exemplo. Nenhum superusuário é criado automaticamente.

| Variável | Uso |
| --- | --- |
| `SECRET_KEY` | Chave secreta do Django, obrigatória |
| `DEBUG` | `True` no desenvolvimento; padrão `False` se omitida |
| `ALLOWED_HOSTS` | Hosts separados por vírgulas |
| `POSTGRES_DB` | Banco, usar `csguess` |
| `POSTGRES_USER` | Usuário do banco, obrigatório |
| `POSTGRES_PASSWORD` | Senha do banco, obrigatória |
| `POSTGRES_HOST` | `127.0.0.1`, pois Django roda no computador |
| `POSTGRES_PORT` | Porta local do banco, padrão `5433` |

O Django lê `.env` com `python-dotenv`; variáveis já exportadas no ambiente têm precedência. Idioma `pt-br`, fuso `America/Fortaleza` e `USE_TZ=True` estão configurados no projeto.

## Alternativa: Django no host e banco no Docker

Para usar `runserver` na porta 8000, pare o web do Compose com `docker compose stop web`.

```bash
docker compose up -d db
docker compose ps
docker compose exec db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose logs --tail=50 db
```

Aguarde o serviço ficar `healthy`. Para iniciar e aguardar em um único comando:

```bash
docker compose up -d --wait db
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Página inicial: http://127.0.0.1:8000/ — Admin: http://127.0.0.1:8000/admin/.

O projeto Compose chama-se **`csguess-game`** para isolar o jogo de um Compose de coleta já chamado `csguess`. O volume persistente é `csguess-game_postgres_data` e o container é `csguess-game-db-1`. A porta só é publicada em `127.0.0.1:5433`; se estiver ocupada, altere `POSTGRES_PORT` no `.env`. Nenhum banco ou volume do coletor é utilizado. Dois bancos chamados `csguess` podem coexistir em instâncias distintas: o jogo conecta na porta 5433 e a coleta pode continuar na 5432.

O banco e as credenciais do PostgreSQL são inicializados apenas quando o volume está vazio. Alterar `POSTGRES_DB` no `.env` não cria nem renomeia bancos em um volume existente; mudar a senha também não altera um usuário existente. Se aparecer `database "csguessjogo" does not exist` depois de mudar o nome, restaure `POSTGRES_DB=csguess` e execute `docker compose up -d --wait db` para atualizar o container preservando o volume. A mensagem `Skipping initialization` é normal quando os dados já existem.

Para parar preservando os dados:

```bash
docker compose stop db
```

Para remover os containers e a rede, preservando o volume:

```bash
docker compose down
```

Não use `down -v` se quiser preservar o banco.

## Modelo Player

`Player` é o cadastro de domínio; o clássico adiciona desafios (com os dados do jogador secreto). Partidas e tentativas ficam somente no cookie de cada navegador. Usa chave primária interna e identidade única composta por `source` e `source_id`. Ambos são obrigatórios; `source_id` é texto livre, inclusive não numérico. `nick` é obrigatório, tem índice de busca e pode se repetir. `name` é obrigatório e suporta Unicode.

Convenção de ausência: `current_team` usa **`No team`** para null, vazio ou espaços na entrada; os demais campos textuais opcionais (`years_active`, `photo_url`, `source_url`) usam **string vazia**, nunca `NULL`. Aposentados devem usar `No team`. As listas usam `[]`; `career_status` usa `unknown`; a data opcional `source_collected_at` usa `NULL`. `created_at` e `updated_at` são automáticos. URLs aceitam até 4096 caracteres; nenhuma imagem é baixada.

`nationalities` usa `JSONField(default=list)`, aceita códigos de duas letras ASCII, normaliza para maiúsculas e rejeita repetições. É uma validação de formato, sem catálogo de países. `roles` também usa `default=list`, aceita somente `rifle`, `awp` e `igl`, rejeitando duplicatas. Não converte funções antigas por suposição; perfis legados incompatíveis são reportados e excluídos da busca e do sorteio, sem alteração dos dados.

O status (`active`, `inactive`, `retired`, `unknown`) descreve a carreira e não a posição no elenco. Não implica elenco principal nem banco de reservas. Equipe atual de aposentados deve ser `No team`. O período de atividade mantém o texto informado; a elegibilidade no clássico exige um intervalo comparável, conforme a documentação da API.

`full_clean()` valida e normaliza; `save()` também chama essa validação, inclusive em `objects.create()`. Como no Django, `bulk_create()`, `bulk_update()` e `QuerySet.update()` não chamam `save()` e exigem validação explícita de cada objeto por quem os utilizar no futuro. A unicidade de origem também é garantida por restrição no PostgreSQL. As datas técnicas são somente leitura no Admin.

## Validação e testes

Com o ambiente virtual ativo e o banco saudável:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
docker compose config --quiet
python manage.py test
```

Os testes cobrem formato, ausência, duplicatas e normalização das listas, Unicode, URLs longas, persistência, unicidade no PostgreSQL e página inicial. Usam PostgreSQL real e um banco temporário `test_csguess`, criado e removido pelo runner; o usuário precisa de permissão para criar bancos (o usuário inicial do container local já possui). Não há fallback para SQLite.

Depois de alterações futuras no modelo, gere e versione novas migrações com `python manage.py makemigrations game` e aplique-as com `python manage.py migrate`.

## Importação JSON v2

O comando `import_players` recebe o contrato v2 gerado pelo coletor, sem consultar
a Liquipedia. A identidade é `source + source_id`: registros existentes são atualizados,
IDs internos e `created_at` são preservados; dados idênticos não alteram `updated_at`.
Registros ausentes do arquivo não são removidos automaticamente.

```bash
# A partir da raiz do projeto Django, com o ambiente virtual ativo
python manage.py check
python manage.py makemigrations --check --dry-run

# Para banco legado: primeiro adiciona a flag sem inventar False
python manage.py migrate game 0002
python manage.py import_players ../csdle/exports/players-v2.json --dry-run \
  --report ../csdle/exports/django-v2-dry-run.report.json
python manage.py import_players ../csdle/exports/players-v2.json \
  --report ../csdle/exports/django-v2-import.report.json

# Depois de todos os cadastros terem a classificação conhecida
python manage.py migrate
python manage.py test --noinput
```

Em um banco novo vazio, `python manage.py migrate` pode aplicar todas as migrações
antes da importação. Em banco legado, 0002 cria a flag anulável; 0003 recusa avançar
se houver valores não apurados. Não atribui False a cadastros antigos. Ao final,
`Player.is_major_winner` é booleano obrigatório, sem default presumido.

O documento precisa ter schema_version=2, exported_at válido com timezone e os
13 campos do contrato. O booleano deve ser True/False real no JSON, nunca string,
inteiro ou null. Aposentados devem vir sem equipe, cargos de coach/staff não são
aceitos como funções de jogador, e source_collected_at é preservado (com timezone).
Nacionalidades múltiplas são preservadas; funções novas devem ser `rifle`, `awp` ou `igl`, e equipe ausente é normalizada para `No team`. Campeões
históricos que hoje são coaches entram com as funções de jogador fornecidas pelo
coletor, possivelmente vazias, sem reutilizar a equipe ou período de coach.

Toda a entrada passa por validação do contrato e `Player.full_clean()` antes da
primeira gravação. A operação usa uma única transação PostgreSQL. O dry-run usa
transação somente leitura; o relatório é separado e escrito atomicamente. Não baixa
fotos, não altera fontes do coletor e não implementa novos modos de jogo.

A coleta v2 validada em 05/11/2026 contém **191 registros coletados** (a elegibilidade diária depende das validações do clássico), 77 campeões
de Major e 16 aposentados. O total anterior de 192 incluía Guerri, excluído agora
como staff sem conquista de Major como jogador. O importador não cria um registro
extra para manter a contagem anterior e não apaga cadastros legados sem autorização.
