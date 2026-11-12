from django.urls import path

from . import logo_views, views

app_name = "game"
urlpatterns = [
    path("health/", views.health, name="health"),

    # Páginas HTML.
    path("", views.home, name="home"),
    path("classic/", views.home, name="classic-page"),
    path("logo/", logo_views.page, name="logo-page"),

    # Rotas JSON consumidas pelo JavaScript da tela.
    path("game/classic/", views.classic, name="classic"),
    path("game/classic/guesses/", views.guesses, name="guesses"),
    path("game/classic/players/<int:player_id>/team-logo/", views.classic_team_logo, name="classic-team-logo"),
    path("game/players/search/", views.player_search, name="player-search"),

    # Modo Logo.
    path("game/logo/", logo_views.state, name="logo"),
    path("game/logo/image/", logo_views.image, name="logo-image"),
    path("game/logo/guesses/", logo_views.guesses, name="logo-guesses"),
    path("game/teams/search/", logo_views.team_search, name="team-search"),
]
