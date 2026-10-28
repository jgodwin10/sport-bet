"""Internal competition codes and their identifiers at each provider.

Provider identifiers below come from the providers' public documentation:
football-data.co.uk division codes, football-data.org competition codes,
The Odds API sport keys and API-Football league ids. `None` means the provider
does not cover the competition (or coverage was not verified).

Cups have no football-data.co.uk files: their fixtures and odds come from The
Odds API (and football-data.org for the Champions League), their history from
API-Football. A cup has too few matches to fit a model on its own, so cup
predictions pool the matches of the leagues its teams come from (see `pool_codes`).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompetitionDef:
    code: str
    name: str
    country: str
    tier: int
    fdcuk: str | None  # football-data.co.uk division
    fdorg: str | None  # football-data.org competition code
    odds_api: str | None  # The Odds API sport key
    api_football: int | None  # API-Football league id
    timezone: str = "Europe/London"  # timezone of football-data.co.uk kickoff times
    format: str = "league"  # league|cup


COMPETITIONS: dict[str, CompetitionDef] = {c.code: c for c in [
    CompetitionDef("ENG-1", "Premier League", "England", 1, "E0", "PL", "soccer_epl", 39),
    CompetitionDef("ENG-2", "Championship", "England", 2, "E1", "ELC", "soccer_efl_champ", 40),
    CompetitionDef("ENG-3", "League One", "England", 3, "E2", None, "soccer_england_league1", 41),
    CompetitionDef("ENG-4", "League Two", "England", 4, "E3", None, "soccer_england_league2", 42),
    CompetitionDef("ENG-5", "National League", "England", 5, "EC", None, None, 43),
    CompetitionDef("SCO-1", "Scottish Premiership", "Scotland", 1, "SC0", None, "soccer_spl", 179),
    CompetitionDef("SCO-2", "Scottish Championship", "Scotland", 2, "SC1", None, None, 180),
    CompetitionDef("SCO-3", "Scottish League One", "Scotland", 3, "SC2", None, None, 183),
    CompetitionDef("SCO-4", "Scottish League Two", "Scotland", 4, "SC3", None, None, 184),
    CompetitionDef("GER-1", "Bundesliga", "Germany", 1, "D1", "BL1", "soccer_germany_bundesliga", 78),
    CompetitionDef("GER-2", "2. Bundesliga", "Germany", 2, "D2", None, "soccer_germany_bundesliga2", 79),
    CompetitionDef("ESP-1", "La Liga", "Spain", 1, "SP1", "PD", "soccer_spain_la_liga", 140),
    CompetitionDef("ESP-2", "Segunda Division", "Spain", 2, "SP2", None, "soccer_spain_segunda_division", 141),
    CompetitionDef("ITA-1", "Serie A", "Italy", 1, "I1", "SA", "soccer_italy_serie_a", 135),
    CompetitionDef("ITA-2", "Serie B", "Italy", 2, "I2", None, "soccer_italy_serie_b", 136),
    CompetitionDef("FRA-1", "Ligue 1", "France", 1, "F1", "FL1", "soccer_france_ligue_one", 61),
    CompetitionDef("FRA-2", "Ligue 2", "France", 2, "F2", None, "soccer_france_ligue_two", 62),
    CompetitionDef("NED-1", "Eredivisie", "Netherlands", 1, "N1", "DED", "soccer_netherlands_eredivisie", 88),
    CompetitionDef("BEL-1", "Pro League", "Belgium", 1, "B1", None, "soccer_belgium_first_div", 144),
    CompetitionDef("POR-1", "Primeira Liga", "Portugal", 1, "P1", "PPL", "soccer_portugal_primeira_liga", 94),
    CompetitionDef("TUR-1", "Super Lig", "Turkey", 1, "T1", None, "soccer_turkey_super_league", 203),
    CompetitionDef("GRE-1", "Super League", "Greece", 1, "G1", None, "soccer_greece_super_league", 197),
    # Cups
    CompetitionDef("UEFA-CL", "Champions League", "Europe", 0, None, "CL", "soccer_uefa_champs_league", 2,
                   format="cup"),
    CompetitionDef("UEFA-EL", "Europa League", "Europe", 0, None, None, "soccer_uefa_europa_league", 3,
                   format="cup"),
    CompetitionDef("UEFA-ECL", "Conference League", "Europe", 0, None, None,
                   "soccer_uefa_europa_conference_league", 848, format="cup"),
    CompetitionDef("ENG-FAC", "FA Cup", "England", 0, None, None, "soccer_fa_cup", 45, format="cup"),
    CompetitionDef("ENG-LC", "EFL Cup", "England", 0, None, None, "soccer_england_efl_cup", 48, format="cup"),
    CompetitionDef("ESP-CDR", "Copa del Rey", "Spain", 0, None, None, "soccer_spain_copa_del_rey", 143,
                   format="cup"),
    CompetitionDef("GER-DFB", "DFB-Pokal", "Germany", 0, None, None, "soccer_germany_dfb_pokal", 81, format="cup"),
    CompetitionDef("ITA-CI", "Coppa Italia", "Italy", 0, None, None, "soccer_italy_coppa_italia", 137,
                   format="cup"),
    CompetitionDef("FRA-CDF", "Coupe de France", "France", 0, None, None, "soccer_france_coupe_de_france", 66,
                   format="cup"),
]}

CUPS = [c.code for c in COMPETITIONS.values() if c.format == "cup"]

BY_FDCUK = {c.fdcuk: c for c in COMPETITIONS.values() if c.fdcuk}
BY_FDORG = {c.fdorg: c for c in COMPETITIONS.values() if c.fdorg}
BY_ODDS_API = {c.odds_api: c for c in COMPETITIONS.values() if c.odds_api}


def pool_codes(code: str) -> list[str]:
    """Competitions whose matches train the model for `code`: a league on its own, a
    domestic cup with every competition of its country, a European cup with all of them
    (European ties are what make ratings comparable across leagues)."""
    comp = COMPETITIONS[code]
    if comp.format == "league":
        return [code]
    if comp.country == "Europe":
        return list(COMPETITIONS)
    return [c.code for c in COMPETITIONS.values() if c.country == comp.country]
