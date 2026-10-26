"""Crest matching. Payloads are SYNTHETIC samples in TheSportsDB's response shape."""

from app.providers.thesportsdb import best_match

TEAMS = [
    {"idTeam": "1", "strTeam": "Brighton WFC", "strSport": "Soccer", "strGender": "Female", "strBadge": "w.png",
     "strLeague": "English Womens Super League"},
    {"idTeam": "2", "strTeam": "Brighton and Hove Albion", "strTeamAlternate": "Brighton, BHAFC", "strSport": "Soccer",
     "strGender": "Male", "strBadge": "m.png", "strLeague": "English Premier League"},
    {"idTeam": "3", "strTeam": "Brighton Hockey", "strSport": "Ice Hockey", "strBadge": "h.png"},
    {"idTeam": "4", "strTeam": "Nottingham Forest", "strSport": "Soccer", "strBadge": "nf.png", "strLeague": "English Premier League"},
]


def test_matches_men_football_team_via_alternate_name():
    crest = best_match(TEAMS, ["Brighton"], "English Premier League")
    assert crest is not None and crest.url == "m.png"


def test_rejects_weak_matches_instead_of_guessing():
    assert best_match(TEAMS, ["Burnley"], "English Premier League") is None


def test_uses_curated_aliases_for_abbreviated_names():
    assert best_match(TEAMS, ["Nott'm Forest", "Nottingham Forest"], None).url == "nf.png"


def test_ignores_teams_without_badge_or_other_sports():
    assert best_match([TEAMS[2]], ["Brighton Hockey"], None) is None


def test_same_name_club_in_another_country_is_rejected():
    jets = {"idTeam": "9", "strTeam": "Newcastle Jets", "strSport": "Soccer", "strGender": "Male", "strBadge": "jets.png",
            "strLeague": "Australian A-League", "strCountry": "Australia"}
    united = {"idTeam": "10", "strTeam": "Newcastle United", "strSport": "Soccer", "strGender": "Male", "strBadge": "nufc.png",
              "strLeague": "English Premier League", "strCountry": "England"}
    assert best_match([jets], ["Newcastle"], "English Premier League", "England") is None
    assert best_match([jets, united], ["Newcastle", "Newcastle United"], "English Premier League", "England").url == "nufc.png"


def test_crest_stored_concurrently_is_reused_not_fatal(db):
    """A visitor's request can cache the same crest between our lookup and our commit."""
    import httpx

    from app.db.models import Team, TeamCrest
    from app.db.session import session_factory
    from app.services.crests import fetch_crest

    team = Team(name="Synthetic FC", logo_url="https://example.test/badge.png", logo_source="thesportsdb")
    db.add(team)
    db.commit()

    class RacingClient:
        def get(self, url):
            with session_factory()() as other:
                other.add(TeamCrest(team_id=team.id, size="tiny", content=b"theirs", content_type="image/png",
                                    source_url=team.logo_url))
                other.commit()
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"ours")

    crest = fetch_crest(db, team, "tiny", RacingClient())
    assert crest is not None and crest.content == b"theirs"
