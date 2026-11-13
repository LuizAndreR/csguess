# CSGuess

Jogo diário de adivinhação sobre Counter-Strike, com dois modos:

- **Clássico:** descubra o jogador comparando nacionalidade, time, funções e outras características. Dicas opcionais são liberadas após 10 e 15 erros.
- **Logo:** descubra a equipe pelo escudo desfocado, que fica mais nítido a cada 10 tentativas.

Os desafios mudam à meia-noite de **America/Fortaleza**. O progresso de cada modo fica em cookies assinados no navegador; limpar os cookies apaga suas tentativas.

## Como executar

Requisitos: Docker Engine ou Desktop em execução e Docker Compose v2.

1. Na raiz do projeto, crie o arquivo de configuração **somente se `.env` ainda não existir**:

   ```bash
   cp .env.example .env
   ```

2. Edite `.env`: defina uma `SECRET_KEY` aleatória e as credenciais `POSTGRES_USER` e `POSTGRES_PASSWORD`.

3. Inicie os serviços:

   ```bash
   docker compose up --build -d
   docker compose ps
   ```

| Endereço | Acesso |
| --- | --- |
| [localhost:8000](http://localhost:8000/) | Modo Clássico |
| [localhost:8000/logo/](http://localhost:8000/logo/) | Modo Logo |
| [localhost:8000/admin/](http://localhost:8000/admin/) | Cadastro de jogadores e times |
| [localhost:8000/health/](http://localhost:8000/health/) | Status da aplicação e do banco |

Na inicialização, o container aplica migrations, prepara os arquivos estáticos, baixa os logos conhecidos e tenta criar os desafios do dia. **Um banco novo precisa de jogadores cadastrados ou importados** para disponibilizar o Clássico; o modo Logo precisa de times com URL e PNG local.

Para acessar o Admin, crie seu usuário:

```bash
docker compose exec web python manage.py createsuperuser
```

## Carregar os dados

Com o JSON v2 do coletor disponível, valide e importe os jogadores:

```bash
docker compose cp ./players-v2.json web:/tmp/players-v2.json
docker compose exec -T web python manage.py import_players /tmp/players-v2.json --dry-run
docker compose exec -T web python manage.py import_players /tmp/players-v2.json
docker compose exec -T web python manage.py fetch_team_logos
docker compose exec -T web python manage.py ensure_daily_challenge
```

O importador cria ou reutiliza os times e associa os jogadores a eles. O downloader preenche URLs conhecidas e salva os PNGs usados pelo jogo.

Para criar os desafios dos próximos dias sem reiniciar o container, adicione ao `crontab -e` a entrada de [deploy/csguess-docker.cron](deploy/csguess-docker.cron), ajustando os caminhos. O comando é seguro para repetir: desafios existentes são preservados.

## Comandos frequentes

```bash
# Acompanhar logs
docker compose logs -f web

# Aplicar alterações no código
docker compose up --build -d web

# Rodar os testes em um banco separado
docker compose exec -T web python manage.py test --noinput

# Parar os serviços preservando os dados
docker compose stop
```

Os dados do PostgreSQL e os PNGs dos logos ficam em volumes persistentes. `docker compose down -v` remove esses volumes.

## Detalhes técnicos

Consulte [docs/tecnico.md](docs/tecnico.md) para regras dos desafios, formato da importação, rotas da API e configuração do banco.

## Tecnologias

Python 3.12, Django 5.2, PostgreSQL 17, Gunicorn e WhiteNoise. Interface em templates Django, CSS e JavaScript, sem etapa de build de front-end. Dependências fixadas em [requirements.txt](requirements.txt).

## Créditos

- Ícone AK-47 por [Skoll / Game-icons.net](https://game-icons.net/1x1/skoll/ak47.html), [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/), com cor adaptada.
- Logos e marcas pertencem às equipes. O catálogo usa imagens do [BO3](https://bo3.gg/teams); as páginas de origem estão em [game/data/team_logos.json](game/data/team_logos.json).
