from __future__ import annotations

import concurrent.futures
import math
import os
import threading
from datetime import date
from pathlib import Path

from flask import Flask, render_template, request

from scorito_client import ScoritoAuthError, ScoritoClient, ScoritoError


BASE_DIR = Path(__file__).resolve().parent


ENV_CANDIDATE_PATHS = (
    BASE_DIR / ".env",
    BASE_DIR / ".env.txt",
    Path.cwd() / ".env",
    Path.cwd() / ".env.txt",
)


def load_env_file(path: Path) -> bool:
    if not path.exists():
        return False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)

    return True


def load_env_files() -> list[Path]:
    loaded_paths: list[Path] = []

    explicit_path = os.getenv("SCORITO_ENV_FILE", "").strip()
    if explicit_path:
        env_path = Path(explicit_path).expanduser()
        if load_env_file(env_path):
            loaded_paths.append(env_path)
        return loaded_paths

    seen: set[Path] = set()
    for candidate in ENV_CANDIDATE_PATHS:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if load_env_file(candidate):
            loaded_paths.append(candidate)

    return loaded_paths


LOADED_ENV_PATHS = load_env_files()

app = Flask(__name__)
CLIENT_CACHE_LOCK = threading.Lock()
CLIENTS_BY_CREDENTIALS: dict[tuple[str, str], ScoritoClient] = {}
GAME_OPTIONS: tuple[dict, ...] = (
    {
        "key": "tdf-2026",
        "label": "TDF 2026",
        "market_id": 309,
        "subleague_id": 1297399,
    },
    {
        "key": "giro-2026",
        "label": "Giro 2026",
        "market_id": 306,
        "subleague_id": 1041245,
    },
    {
        "key": "klassiekerspel-2026",
        "label": "Klassiekerspel 2026",
        "market_id": 302,
        "subleague_id": 1017615,
    },
    {
        "key": "vuelta-2025",
        "label": "Vuelta 2025",
        "market_id": 288,
        "subleague_id": 999619,
    },
    {
        "key": "tdf-2025",
        "label": "TDF 2025",
        "market_id": 286,
        "subleague_id": 973107,
    },
    {
        "key": "giro-2025",
        "label": "Giro 2025",
        "market_id": 283,
        "subleague_id": 958117,
    },
    {
        "key": "klassiekerspel-2025",
        "label": "Klassiekerspel 2025",
        "market_id": 281,
        "subleague_id": 950377,
    },
    {
        "key": "vuelta-2024",
        "label": "Vuelta 2024",
        "market_id": 270,
        "subleague_id": 929047,
    },
    {
        "key": "tdf-2024",
        "label": "TDF 2024",
        "market_id": 267,
        "subleague_id": 892049,
        "subleague_name": "nieuwe ronde,nieuwe kanse",
    },
    {
        "key": "giro-2024",
        "label": "Giro 2024",
        "market_id": 263,
        "subleague_id": 731076,
    },
    {
        "key": "klassiekerspel-2024",
        "label": "Klassiekerspel 2024",
        "market_id": 261,
        "subleague_id": 711187,
    },
    {
        "key": "vuelta-2023",
        "label": "Vuelta 2023",
        "market_id": 244,
        "subleague_id": 694525,
    },
    {
        "key": "tdf-2023",
        "label": "TDF 2023",
        "market_id": 235,
        "subleague_id": 669122,
    },
    {
        "key": "giro-2023",
        "label": "Giro 2023",
        "market_id": 231,
        "subleague_id": 656859,
    },
    {
        "key": "klassiekerspel-2023",
        "label": "Klassiekerspel 2023",
        "market_id": 227,
        "subleague_id": 647828,
    },
    {
        "key": "vuelta-2022",
        "label": "Vuelta 2022",
        "market_id": 208,
        "subleague_id": 508518,
    },
    {
        "key": "tdf-2022",
        "label": "TDF 2022",
        "market_id": 205,
        "subleague_id": 493432,
    },
    {
        "key": "giro-2022",
        "label": "Giro 2022",
        "market_id": 202,
        "subleague_id": 485667,
    },
    {
        "key": "klassiekerspel-2022",
        "label": "Klassiekerspel 2022",
        "market_id": 200,
        "subleague_id": 478444,
    },
    {
        "key": "vuelta-2021",
        "label": "Vuelta 2021",
        "market_id": 172,
        "subleague_id": 460868,
    },
    {
        "key": "tdf-2021",
        "label": "TDF 2021",
        "market_id": 171,
        "subleague_id": 394504,
    },
    {
        "key": "giro-2021",
        "label": "Giro 2021",
        "market_id": 170,
        "subleague_id": 337254,
    },
    {
        "key": "klassiekerspel-2021",
        "label": "Klassiekerspel 2021",
        "market_id": 173,
        "subleague_id": 311213,
    },
    {
        "key": "klassiekerspel-2020",
        "label": "Klassiekerspel 2020",
        "market_id": 141,
        "subleague_id": 267045,
        "subleague_name": "Klassiekergepieker",
    },
    {
        "key": "vuelta-2020",
        "label": "Vuelta 2020",
        "market_id": 159,
        "subleague_id": 302841,
    },
    {
        "key": "tdf-2020",
        "label": "TDF 2020",
        "market_id": 152,
        "subleague_id": 284097,
    },
    {
        "key": "giro-2020",
        "label": "Giro 2020",
        "market_id": 144,
        "subleague_id": 298134,
    },
    {
        "key": "vuelta-2019",
        "label": "Vuelta 2019",
        "market_id": 130,
        "subleague_id": 260819,
        "subleague_name": "To Bennett or to bennot",
    },
    {
        "key": "tdf-2019",
        "label": "TDF 2019",
        "market_id": 124,
        "subleague_id": 244350,
        "subleague_name": "Parijs is niet ver meer",
    },
    {
        "key": "giro-2019",
        "label": "Giro 2019",
        "market_id": 119,
        "subleague_id": 235849,
        "subleague_name": "Verslonde aan grote ronde",
    },
    {
        "key": "klassiekerspel-2019",
        "label": "Klassiekerspel 2019",
        "market_id": 117,
        "subleague_id": 229400,
        "subleague_name": "Klassiekergepieker",
    },
    {
        "key": "vuelta-2018",
        "label": "Vuelta 2018",
        "market_id": 101,
        "subleague_id": 224020,
        "subleague_name": "Het rode doelwit inMadrid",
    },
    {
        "key": "tdf-2018",
        "label": "TDF 2018",
        "market_id": 99,
        "subleague_id": 207572,
        "subleague_name": "Scorito wacht op niemand",
    },
    {
        "key": "giro-2018",
        "label": "Giro 2018",
        "market_id": 96,
        "subleague_id": 190753,
        "subleague_name": "Meerdere wegen naar Rome",
    },
    {
        "key": "klassiekerspel-2018",
        "label": "Klassiekerspel 2018",
        "market_id": 95,
        "subleague_id": 185994,
        "subleague_name": "Klassiekergepieker",
    },
    {
        "key": "vuelta-2017",
        "label": "Vuelta 2017",
        "market_id": 78,
        "subleague_id": 174235,
        "subleague_name": "Nieuwe ronde nieuwe kanse",
    },
    {
        "key": "tdf-2017",
        "label": "TDF 2017",
        "market_id": 75,
        "subleague_id": 156904,
        "subleague_name": "Nieuw Ronde nieuwe kansen",
    },
    {
        "key": "giro-2017",
        "label": "Giro 2017",
        "market_id": 72,
        "subleague_id": 146515,
        "subleague_name": "Geen van Avermaet",
    },
    {
        "key": "klassiekerspel-2017",
        "label": "Klassiekerspel 2017",
        "market_id": 82,
        "subleague_id": 142505,
        "subleague_name": "Klassiekerspel op afstand",
    },
)
GAME_OPTIONS_BY_KEY = {game["key"]: game for game in GAME_OPTIONS}
EVENT_COLUMNS: tuple[dict, ...] = (
    {"id": "klassiekerspel", "label": "Klassiekerspel"},
    {"id": "giro", "label": "Giro"},
    {"id": "tdf", "label": "TDF"},
    {"id": "vuelta", "label": "Vuelta"},
)
EVENT_LABELS = {item["id"]: item["label"] for item in EVENT_COLUMNS}
EVENT_TOOLTIP_LABELS = {
    "klassiekerspel": "Klassiekerspel",
    "giro": "Giro d'Italia",
    "tdf": "Tour de France",
    "vuelta": "Vuelta a Espana",
}
EVENT_ORDER = {item["id"]: index for index, item in enumerate(EVENT_COLUMNS)}
CURRENT_DATE = date(2026, 7, 21)
SEASON_END_BY_EVENT = {
    "klassiekerspel": (4, 30),
    "giro": (6, 30),
    "tdf": (8, 15),
    "vuelta": (10, 15),
}
MANAGER_ALIAS_GROUPS = {
    "Mevrouw Van Zetten uit Tiel": (
        "Mevrouw Van Zetten uit Tiel",
        "Berlinerbol",
    ),
}
MANAGER_ALIAS_BY_NAME = {
    alias.strip().casefold(): canonical_name
    for canonical_name, aliases in MANAGER_ALIAS_GROUPS.items()
    for alias in aliases
}
VEERKAMP_PODIUM_IDENTITIES = {
    "paul": {
        "full_names": ("paul veerkamp",),
        "usernames": ("w t", "wt"),
    },
    "sem": {
        "full_names": ("sem veerkamp",),
        "usernames": ("uae team semirates",),
    },
    "max": {
        "full_names": ("max veerkamp",),
        "usernames": ("wzewbedip",),
    },
}


def normalize_name_token(value: str | None) -> str:
    raw_value = str(value or "").strip().casefold()
    cleaned = [
        character if character.isalnum() else " "
        for character in raw_value
    ]
    return " ".join("".join(cleaned).split())


def get_veerkamp_podium_identity(*, username: str | None, full_name: str | None) -> str | None:
    normalized_username = normalize_name_token(username)
    normalized_full_name = normalize_name_token(full_name)
    for identity, config in VEERKAMP_PODIUM_IDENTITIES.items():
        if normalized_full_name in config["full_names"]:
            return identity
        if normalized_username in config["usernames"]:
            return identity
    return None


def is_veerkamp_podium(podium: list[dict]) -> bool:
    if len(podium) < 3:
        return False

    identities = {
        identity
        for identity in (
            get_veerkamp_podium_identity(
                username=entry.get("username"),
                full_name=entry.get("full_name"),
            )
            for entry in podium[:3]
        )
        if identity is not None
    }
    return identities == set(VEERKAMP_PODIUM_IDENTITIES)


def get_market_id() -> int:
    return int(os.getenv("SCORITO_MARKET_ID", "309"))


def get_default_subleague_id() -> int | None:
    raw_value = os.getenv("SCORITO_DEFAULT_SUBLEAGUE_ID", "").strip()
    return int(raw_value) if raw_value else None


def get_default_game_key() -> str:
    configured_key = os.getenv("SCORITO_DEFAULT_GAME_KEY", "").strip().lower()
    if configured_key in GAME_OPTIONS_BY_KEY:
        return configured_key

    configured_market_id = get_market_id()
    configured_subleague_id = get_default_subleague_id()

    for game in GAME_OPTIONS:
        if (
            configured_market_id == int(game["market_id"])
            and configured_subleague_id == int(game["subleague_id"])
        ):
            return str(game["key"])

    for game in GAME_OPTIONS:
        if configured_market_id == int(game["market_id"]):
            return str(game["key"])

    return str(GAME_OPTIONS[0]["key"])


def choose_game(requested_game_key: str, *, current_page: str = "live") -> dict:
    normalized_key = requested_game_key.strip().lower()
    if current_page == "history":
        selected_game = GAME_OPTIONS_BY_KEY.get(normalized_key)
        if selected_game is not None:
            return selected_game
        return GAME_OPTIONS_BY_KEY[get_default_game_key()]

    page_games = build_page_game_options(current_page)
    page_games_by_key = {str(game["key"]): game for game in page_games}
    selected_game = page_games_by_key.get(normalized_key)
    if selected_game is not None:
        return selected_game

    default_game = GAME_OPTIONS_BY_KEY.get(get_default_game_key())
    if default_game is not None and str(default_game["key"]) in page_games_by_key:
        return page_games_by_key[str(default_game["key"])]

    if page_games:
        return page_games[0]

    selected_game = GAME_OPTIONS_BY_KEY.get(normalized_key)
    if selected_game is not None:
        return selected_game
    return GAME_OPTIONS_BY_KEY[get_default_game_key()]


def choose_page(requested_page: str) -> str:
    normalized_page = requested_page.strip().lower()
    if normalized_page == "history":
        return "history"
    if normalized_page in {"archive", "historic-games"}:
        return "archive"
    return "live"


def choose_history_view(requested_history_view: str) -> str:
    normalized_view = requested_history_view.strip().lower()
    if normalized_view in {"stats", "trophies"}:
        return "stats"
    if normalized_view == "headtohead":
        return "headtohead"
    if normalized_view == "margins":
        return "margins"
    if normalized_view == "scores":
        return "scores"
    return "matrix"


def choose_history_scores_view(requested_history_scores_view: str) -> str:
    normalized_view = requested_history_scores_view.strip().lower()
    if normalized_view == "points":
        return "points"
    return "percentage"


def choose_history_stats_view(requested_history_stats_view: str) -> str:
    normalized_view = requested_history_stats_view.strip().lower()
    if normalized_view == "trophies":
        return "trophies"
    return "overview"


def choose_history_margin_view(requested_history_margin_view: str) -> str:
    normalized_view = requested_history_margin_view.strip().lower()
    if normalized_view == "smallest":
        return "smallest"
    return "largest"


def choose_history_user_id(requested_history_user_id: int | None) -> int | None:
    if requested_history_user_id is None or requested_history_user_id <= 0:
        return None
    return requested_history_user_id


def canonical_manager_name(name: str) -> str:
    normalized_name = name.strip().casefold()
    return MANAGER_ALIAS_BY_NAME.get(normalized_name, name.strip())


def apply_manager_display_alias(participant: dict) -> None:
    username = str(participant.get("Username") or "").strip()
    if not username:
        return

    canonical_name = canonical_manager_name(username)
    if canonical_name == username:
        return

    participant["Username"] = canonical_name
    participant["FullName"] = canonical_name


def apply_manager_display_aliases_to_rows(rows: list[dict]) -> None:
    for row in rows:
        participant = row.get("participant")
        if isinstance(participant, dict):
            apply_manager_display_alias(participant)


def apply_manager_display_aliases_to_lineups(lineups: list[dict]) -> None:
    for lineup in lineups:
        participant = lineup.get("participant")
        if isinstance(participant, dict):
            apply_manager_display_alias(participant)


def apply_manager_display_aliases_to_stage_score_matrix(stage_score_matrix: dict) -> None:
    for row in stage_score_matrix.get("rows", []):
        participant = row.get("participant")
        if isinstance(participant, dict):
            apply_manager_display_alias(participant)


def apply_history_manager_aliases(overview_cards: list[dict]) -> None:
    alias_profiles: dict[str, dict] = {}
    for card in overview_cards:
        for entry in card.get("standings", []):
            participant = entry.get("participant", {})
            username = str(participant.get("Username") or "").strip()
            if not username:
                continue

            canonical_name = canonical_manager_name(username)
            if canonical_name == username and canonical_name not in MANAGER_ALIAS_GROUPS:
                continue

            profile = alias_profiles.setdefault(
                canonical_name,
                {
                    "canonical_name": canonical_name,
                    "preferred_participant": None,
                    "preferred_user_id": 0,
                },
            )
            current_user_id = int(participant.get("UserId") or 0)
            if current_user_id > 0 and (
                username == canonical_name or profile["preferred_participant"] is None
            ):
                profile["preferred_participant"] = participant
                profile["preferred_user_id"] = current_user_id

    for card in overview_cards:
        for entry in card.get("standings", []):
            participant = entry.get("participant", {})
            username = str(participant.get("Username") or "").strip()
            canonical_name = canonical_manager_name(username)
            profile = alias_profiles.get(canonical_name)
            if not profile:
                continue

            participant["Username"] = canonical_name
            participant["FullName"] = canonical_name
            if int(profile.get("preferred_user_id") or 0) > 0:
                participant["UserId"] = int(profile["preferred_user_id"])

        for entry in card.get("podium", []):
            username = str(entry.get("username") or "").strip()
            canonical_name = canonical_manager_name(username)
            if canonical_name == username and canonical_name not in MANAGER_ALIAS_GROUPS:
                continue
            entry["username"] = canonical_name
            entry["full_name"] = canonical_name
def parse_history_compare_ids(requested_history_compare_ids: str) -> list[int]:
    user_ids: list[int] = []
    seen_ids: set[int] = set()
    for raw_part in requested_history_compare_ids.split(","):
        raw_part = raw_part.strip()
        if not raw_part:
            continue
        try:
            user_id = int(raw_part)
        except ValueError:
            continue
        if user_id <= 0 or user_id in seen_ids:
            continue
        seen_ids.add(user_id)
        user_ids.append(user_id)
    return user_ids


def choose_history_compare_ids(
    requested_history_compare_ids: str,
    *,
    valid_user_ids: set[int] | None = None,
    limit: int = 6,
) -> list[int]:
    compare_ids = parse_history_compare_ids(requested_history_compare_ids)
    if valid_user_ids is not None:
        compare_ids = [user_id for user_id in compare_ids if user_id in valid_user_ids]
    return compare_ids[:limit]


def serialize_history_compare_ids(compare_ids: list[int]) -> str:
    return ",".join(str(user_id) for user_id in compare_ids if user_id > 0)


def build_selected_subleague(selected_game: dict) -> dict:
    return {
        "Id": int(selected_game["subleague_id"]),
        "Name": str(selected_game["label"]),
        "IsMainPool": False,
    }


def get_client() -> ScoritoClient:
    email = os.getenv("SCORITO_EMAIL", "").strip()
    password = os.getenv("SCORITO_PASSWORD", "").strip()
    if not email or not password:
        searched_locations = ", ".join(str(path) for path in ENV_CANDIDATE_PATHS)
        loaded_message = (
            f" Geladen env-bestand(en): {', '.join(str(path) for path in LOADED_ENV_PATHS)}."
            if LOADED_ENV_PATHS
            else ""
        )
        raise RuntimeError(
            "Scorito-inloggegevens ontbreken. "
            "Zet SCORITO_EMAIL en SCORITO_PASSWORD in de omgevingsvariabelen, "
            "of maak een .env/.env.txt-bestand aan. "
            f"Gezochte standaardlocaties: {searched_locations}."
            f"{loaded_message}"
        )
    cache_key = (email, password)
    with CLIENT_CACHE_LOCK:
        client = CLIENTS_BY_CREDENTIALS.get(cache_key)
        if client is None:
            client = ScoritoClient(email=email, password=password)
            CLIENTS_BY_CREDENTIALS[cache_key] = client
    return client


def choose_subleague(subleagues: list[dict], requested_subleague_id: int | None) -> dict | None:
    if not subleagues:
        return None

    if requested_subleague_id is not None:
        for subleague in subleagues:
            if int(subleague["Id"]) == requested_subleague_id:
                return subleague

    for subleague in subleagues:
        if subleague.get("IsDefaultSelected"):
            return subleague

    for subleague in subleagues:
        if not subleague.get("IsMainPool"):
            return subleague

    return subleagues[0]


def choose_market_round(rounds: list[dict], requested_market_round_id: int | None) -> dict | None:
    if not rounds:
        return None

    if requested_market_round_id is not None:
        for market_round in rounds:
            if int(market_round["MarketRoundId"]) == requested_market_round_id:
                return market_round

    for status in (1, 0, 2):
        matching_rounds = [item for item in rounds if int(item.get("StageStatus", -1)) == status]
        if matching_rounds:
            if status == 2:
                return sorted(matching_rounds, key=lambda item: item["StageOrder"], reverse=True)[0]
            return sorted(matching_rounds, key=lambda item: item["StageOrder"])[0]

    return sorted(rounds, key=lambda item: item["StageOrder"])[0]


def choose_latest_finished_round(rounds: list[dict]) -> dict | None:
    finished_rounds = [item for item in rounds if int(item.get("StageStatus", -1)) == 2]
    if not finished_rounds:
        return None
    return sorted(finished_rounds, key=lambda item: item["StageOrder"], reverse=True)[0]


def choose_previous_finished_round(rounds: list[dict], selected_round: dict | None) -> dict | None:
    if not rounds or not selected_round:
        return None

    selected_order = int(selected_round.get("StageOrder") or 0)
    finished_before = [
        item
        for item in rounds
        if int(item.get("StageStatus", -1)) == 2
        and int(item.get("StageOrder") or 0) < selected_order
    ]
    if finished_before:
        return sorted(finished_before, key=lambda item: item["StageOrder"], reverse=True)[0]
    return choose_latest_finished_round(rounds)


def choose_points_source_round(rounds: list[dict], selected_round: dict | None) -> dict | None:
    if not selected_round:
        return None

    stage_status = int(selected_round.get("StageStatus", -1))
    if stage_status == 2:
        return selected_round

    return choose_previous_finished_round(rounds, selected_round)


def build_stage_button_rounds(rounds: list[dict]) -> list[dict]:
    if not rounds:
        return []

    ordered_rounds = sorted(rounds, key=lambda item: int(item.get("StageOrder") or 0))
    finished_rounds = [item for item in ordered_rounds if int(item.get("StageStatus", -1)) == 2]
    current_round = choose_current_round(rounds)
    next_round = choose_next_round(rounds, current_round)

    button_rounds: list[dict] = [
        {"round": item, "nav_label": "Gespeeld"}
        for item in finished_rounds
    ]

    if current_round:
        button_rounds.append(
            {
                "round": current_round,
                "nav_label": "Live" if int(current_round.get("StageStatus", -1)) == 1 else "Huidig",
            }
        )
    if next_round:
        button_rounds.append({"round": next_round, "nav_label": "Volgende"})

    return button_rounds


def choose_current_round(rounds: list[dict]) -> dict | None:
    if not rounds:
        return None

    ordered_rounds = sorted(rounds, key=lambda item: int(item.get("StageOrder") or 0))
    live_round = next((item for item in ordered_rounds if int(item.get("StageStatus", -1)) == 1), None)
    if live_round:
        return live_round

    return next((item for item in ordered_rounds if int(item.get("StageStatus", -1)) == 0), None)


def choose_next_round(rounds: list[dict], current_round: dict | None) -> dict | None:
    if not rounds or not current_round:
        return None

    current_order = int(current_round.get("StageOrder") or 0)
    ordered_rounds = sorted(rounds, key=lambda item: int(item.get("StageOrder") or 0))
    return next(
        (
            item
            for item in ordered_rounds
            if int(item.get("StageStatus", -1)) == 0
            and int(item.get("StageOrder") or 0) > current_order
        ),
        None,
    )


def stage_status_label(stage_status: int) -> str:
    return {
        0: "Upcoming",
        1: "Live",
        2: "Finished",
    }.get(stage_status, "Unknown")


def build_rider_picker_view(lineups: list[dict]) -> list[dict]:
    rider_cards: dict[int, dict] = {}

    for lineup in lineups:
        participant = lineup["participant"]
        for rider in lineup["selected_riders"]:
            card = rider_cards.setdefault(
                rider.rider_id,
                {
                    "rider_id": rider.rider_id,
                    "name_short": rider.name_short,
                    "initials": rider.initials,
                    "first_name": rider.first_name,
                    "last_name": rider.last_name,
                    "team_name": rider.team_name,
                    "team_abbreviation": rider.team_abbreviation,
                    "team_image_url": rider.team_image_url,
                    "jersey_url": rider.jersey_url,
                    "pick_count": rider.subleague_pick_count,
                    "pick_percentage": rider.subleague_pick_percentage,
                    "display_base_points": rider.display_base_points,
                    "pickers": [],
                },
            )
            card["pickers"].append(
                {
                    "full_name": participant.get("FullName", ""),
                    "username": participant.get("Username", ""),
                    "is_captain": rider.is_captain,
                    "display_points": rider.display_points,
                }
            )

    rider_card_list = list(rider_cards.values())
    for card in rider_card_list:
        card["pickers"].sort(
            key=lambda picker: (
                picker["username"].lower(),
                picker["full_name"].lower(),
            )
        )

    rider_card_list.sort(
        key=lambda card: (
            -card["pick_count"],
            card["name_short"].lower(),
        )
    )
    return rider_card_list


def build_view_tabs(
    *,
    show_stage_lineups: bool,
    is_upcoming_stage: bool,
    lineups: list[dict],
    rider_picker_view: list[dict],
    recommended_riders: list,
    classification_panels: list[dict],
    projected_final_scores: list[dict],
    current_standings: list[dict],
    stage_score_matrix: dict,
) -> list[dict]:
    tabs: list[dict] = []

    if is_upcoming_stage and recommended_riders:
        tabs.append({"id": "next", "label": "Volgende etappe"})
    if show_stage_lineups:
        tabs.append({"id": "lineups", "label": "Opstellingen"})
    if show_stage_lineups and lineups and rider_picker_view:
        tabs.append({"id": "picked", "label": "Wie koos"})
    if classification_panels:
        tabs.append({"id": "classifications", "label": "Klassementen"})
    if projected_final_scores:
        tabs.append({"id": "finals", "label": "Eindstand nu"})
    if stage_score_matrix.get("rows") and stage_score_matrix.get("stages"):
        tabs.append({"id": "graph", "label": "Grafiek"})
        tabs.append({"id": "stages", "label": "Etappes"})
    if current_standings:
        tabs.append({"id": "standings", "label": "Stand"})

    return tabs


def choose_archive_round(rounds: list[dict], requested_market_round_id: int | None) -> dict | None:
    finished_rounds = [
        item for item in rounds if int(item.get("StageStatus", -1)) == 2
    ]
    if not finished_rounds:
        return None

    if requested_market_round_id is not None:
        for market_round in finished_rounds:
            if int(market_round["MarketRoundId"]) == requested_market_round_id:
                return market_round

    return sorted(finished_rounds, key=lambda item: item["StageOrder"], reverse=True)[0]


def build_archive_stage_button_rounds(rounds: list[dict]) -> list[dict]:
    finished_rounds = sorted(
        (
            item
            for item in rounds
            if int(item.get("StageStatus", -1)) == 2
        ),
        key=lambda item: int(item.get("StageOrder") or 0),
    )
    return [{"round": item, "nav_label": "Archief"} for item in finished_rounds]


def parse_game_identity(game: dict) -> tuple[str, int]:
    key = str(game.get("key") or "")
    parts = key.split("-")
    if len(parts) < 2:
        return key, 0

    event_id = parts[0].strip().lower()
    try:
        year = int(parts[-1])
    except ValueError:
        year = 0
    return event_id, year


def classify_game_page(game: dict) -> str:
    event_id, year = parse_game_identity(game)
    if year <= 0:
        return "archive"
    if year < CURRENT_DATE.year:
        return "archive"
    if year > CURRENT_DATE.year:
        return "live"

    season_end = SEASON_END_BY_EVENT.get(event_id)
    if season_end is None:
        return "archive"

    season_end_date = date(year, season_end[0], season_end[1])
    if CURRENT_DATE <= season_end_date:
        return "live"
    return "archive"


def build_page_game_options(current_page: str) -> list[dict]:
    if current_page == "history":
        return list(GAME_OPTIONS)

    target_page = "archive" if current_page == "archive" else "live"
    page_games = [game for game in GAME_OPTIONS if classify_game_page(game) == target_page]
    return page_games or list(GAME_OPTIONS)


def uses_archive_only_flow(game: dict) -> bool:
    event_id, _year = parse_game_identity(game)
    return event_id == "klassiekerspel"


def normalize_history_standings(
    client: ScoritoClient,
    *,
    market_id: int,
    standings: list[dict],
) -> list[dict]:
    normalized_rows: list[dict] = []
    for index, entry in enumerate(standings, start=1):
        participant = entry.get("participant", {})
        user_id = int(participant.get("UserId") or 0)
        market_percentage = entry.get("market_percentage")
        if market_percentage is None and user_id > 0:
            market_percentage = client.get_user_market_percentage(user_id, market_id)

        normalized_rows.append(
            {
                "participant": participant,
                "rank": int(entry.get("rank") or index),
                "total_points": int(entry.get("total_points") or 0),
                "market_percentage": market_percentage,
                "is_current_user": bool(entry.get("is_current_user")),
            }
        )

    normalized_rows.sort(
        key=lambda item: (
            int(item.get("rank") or 0),
            item["participant"].get("Username", "").lower(),
            item["participant"].get("FullName", "").lower(),
        )
    )
    return normalized_rows


def build_game_podium_rows(standings: list[dict], *, limit: int = 3) -> list[dict]:
    podium: list[dict] = []
    for entry in standings[:limit]:
        participant = entry.get("participant", {})
        podium.append(
            {
                "rank": int(entry.get("rank") or (len(podium) + 1)),
                "username": participant.get("Username", ""),
                "full_name": participant.get("FullName", ""),
                "points": int(entry.get("total_points") or 0),
                "market_percentage": entry.get("market_percentage"),
                "is_current_user": bool(entry.get("is_current_user")),
            }
        )
    return podium


def build_game_overview_card(
    *,
    game: dict,
    rounds: list[dict],
    standings: list[dict],
    is_archive_game: bool,
    subleague_detail: dict | None = None,
    error: str | None = None,
) -> dict:
    current_round = choose_current_round(rounds)
    latest_finished_round = choose_latest_finished_round(rounds)
    event_id, year = parse_game_identity(game)
    podium = build_game_podium_rows(standings)
    subleague_name = str(
        (subleague_detail or {}).get("Name")
        or game.get("subleague_name")
        or game["label"]
    ).strip()
    subleague_invite_url = str((subleague_detail or {}).get("InviteUrl") or "").strip()

    if is_archive_game:
        status_label = "Historisch"
        summary = "Definitief podium"
    elif current_round and int(current_round.get("StageStatus", -1)) == 1:
        status_label = "Live"
        summary = f"Etappe {int(current_round.get('StageOrder') or 0)} live"
    elif latest_finished_round:
        status_label = "Actueel"
        summary = f"Na etappe {int(latest_finished_round.get('StageOrder') or 0)}"
    else:
        status_label = "Voor start"
        summary = "Nog geen eindstand"

    return {
        "game_key": str(game["key"]),
        "page": classify_game_page(game),
        "label": str(game["label"]),
        "event_id": event_id,
        "event_label": EVENT_LABELS.get(event_id, str(game["label"])),
        "year": year,
        "subleague_name": subleague_name,
        "subleague_invite_url": subleague_invite_url,
        "status_label": status_label,
        "summary": summary,
        "is_archive_game": is_archive_game,
        "podium": podium,
        "is_veerkamp_podium": is_veerkamp_podium(podium),
        "standings": standings,
        "participant_count": len(standings),
        "error": error,
    }


def load_game_overview_card(client: ScoritoClient, game: dict) -> dict:
    market_id = int(game["market_id"])
    subleague_id = int(game["subleague_id"])

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            rounds_future = executor.submit(client.get_market_rounds, market_id)
            participants_future = executor.submit(
                client.get_subleague_participants,
                subleague_id,
            )
            subleague_detail_future = executor.submit(
                client.get_subleague_detail,
                subleague_id,
            )
            rounds = rounds_future.result()
            participants = participants_future.result()
            try:
                subleague_detail = subleague_detail_future.result()
            except Exception:
                subleague_detail = None

        latest_finished_round = choose_latest_finished_round(rounds)
        if uses_archive_only_flow(game):
            is_archive_game = True
        else:
            archive_probe = probe_archive_game(
                client=client,
                market_id=market_id,
                participants=participants,
                latest_finished_round=latest_finished_round,
            )
            is_archive_game = bool(archive_probe["is_archive"])

        if is_archive_game:
            standings = client.build_archive_standings(
                market_id=market_id,
                subleague_id=subleague_id,
            )
        else:
            finished_round_ids = [
                int(item["MarketRoundId"])
                for item in sorted(rounds, key=lambda round_item: round_item["StageOrder"])
                if int(item.get("StageStatus", -1)) == 2
            ]
            finished_round_stage_orders = {
                int(item["MarketRoundId"]): int(item["StageOrder"])
                for item in rounds
                if int(item.get("StageStatus", -1)) == 2
            }
            standings = client.build_subleague_standings(
                market_id=market_id,
                subleague_id=subleague_id,
                finished_market_round_ids=finished_round_ids,
                finished_round_stage_orders=finished_round_stage_orders,
            )
        standings = normalize_history_standings(
            client,
            market_id=market_id,
            standings=standings,
        )

        return build_game_overview_card(
            game=game,
            rounds=rounds,
            standings=standings,
            is_archive_game=is_archive_game,
            subleague_detail=subleague_detail,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        return build_game_overview_card(
            game=game,
            rounds=[],
            standings=[],
            is_archive_game=False,
            subleague_detail=None,
            error=str(exc),
        )


def build_overview_podiums(
    client: ScoritoClient,
    *,
    selected_game_key: str | None,
    selected_game_card: dict | None,
) -> list[dict]:
    overview_cards_by_key: dict[str, dict] = {}
    if selected_game_key and selected_game_card:
        overview_cards_by_key[str(selected_game_key)] = selected_game_card

    remaining_games = [
        game for game in GAME_OPTIONS if str(game["key"]) not in overview_cards_by_key
    ]
    if remaining_games:
        worker_count = max(1, min(4, len(remaining_games)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(load_game_overview_card, client, game): str(game["key"])
                for game in remaining_games
            }
            for future in concurrent.futures.as_completed(futures):
                game_key = futures[future]
                overview_cards_by_key[game_key] = future.result()

    ordered_cards: list[dict] = []
    for game in GAME_OPTIONS:
        game_key = str(game["key"])
        card = overview_cards_by_key.get(game_key)
        if card is not None:
            ordered_cards.append(card)
    return ordered_cards


def build_history_year_rows(overview_cards: list[dict]) -> list[dict]:
    cards_by_slot: dict[tuple[int, str], dict] = {
        (int(card.get("year") or 0), str(card.get("event_id") or "")): card
        for card in overview_cards
        if int(card.get("year") or 0) > 0 and str(card.get("event_id") or "")
    }
    years = sorted(
        {int(card.get("year") or 0) for card in overview_cards if int(card.get("year") or 0) > 0},
        reverse=True,
    )

    rows: list[dict] = []
    for year in years:
        rows.append(
            {
                "year": year,
                "cells": [
                    {
                        "event": event_column,
                        "card": cards_by_slot.get((year, str(event_column["id"]))),
                    }
                    for event_column in EVENT_COLUMNS
                ],
            }
        )
    return rows


def _empty_history_event_years() -> dict[str, list[int]]:
    return {str(event_column["id"]): [] for event_column in EVENT_COLUMNS}


def _append_history_event_year(event_years: dict[str, list[int]], event_id: str, year: int) -> None:
    if event_id not in event_years or year <= 0:
        return
    event_years[event_id].append(year)


def _normalize_history_event_years(event_years: dict[str, list[int]]) -> dict[str, list[int]]:
    normalized: dict[str, list[int]] = {}
    for event_column in EVENT_COLUMNS:
        event_id = str(event_column["id"])
        years = sorted(
            {int(year) for year in event_years.get(event_id, []) if int(year) > 0},
            reverse=True,
        )
        normalized[event_id] = years
    return normalized


def format_history_event_years_tooltip(event_years: dict[str, list[int]]) -> str:
    lines: list[str] = []
    for event_column in EVENT_COLUMNS:
        event_id = str(event_column["id"])
        years = [str(int(year)) for year in event_years.get(event_id, []) if int(year) > 0]
        if years:
            event_label = EVENT_TOOLTIP_LABELS.get(event_id, EVENT_LABELS.get(event_id, event_id))
            lines.append(f"{event_label}: {', '.join(years)}")
    return "\n".join(lines)


def build_history_users(overview_cards: list[dict]) -> list[dict]:
    users_by_id: dict[int, dict] = {}
    for card in overview_cards:
        event_id = str(card.get("event_id") or "")
        year = int(card.get("year") or 0)
        for entry in card.get("standings", []):
            participant = entry.get("participant", {})
            user_id = int(participant.get("UserId") or 0)
            if user_id <= 0:
                continue

            user_row = users_by_id.setdefault(
                user_id,
                {
                    "user_id": user_id,
                    "username": participant.get("Username", ""),
                    "full_name": participant.get("FullName", ""),
                    "game_count": 0,
                    "wins": 0,
                    "podiums": 0,
                    "total_points": 0,
                    "market_percentage_sum": 0.0,
                    "market_percentage_count": 0,
                    "best_market_percentage": None,
                    "gold_trophies": 0,
                    "silver_trophies": 0,
                    "bronze_trophies": 0,
                    "event_wins": {str(event_column["id"]): 0 for event_column in EVENT_COLUMNS},
                    "win_years": _empty_history_event_years(),
                    "podium_years": _empty_history_event_years(),
                    "gold_trophy_years": _empty_history_event_years(),
                    "silver_trophy_years": _empty_history_event_years(),
                    "bronze_trophy_years": _empty_history_event_years(),
                },
            )
            user_row["game_count"] += 1
            rank = int(entry.get("rank") or 0)
            total_points = int(entry.get("total_points") or 0)
            user_row["total_points"] += total_points
            if rank == 1:
                user_row["wins"] += 1
                event_wins = user_row.get("event_wins", {})
                if event_id in event_wins:
                    event_wins[event_id] += 1
                _append_history_event_year(user_row["win_years"], event_id, year)
            if 1 <= rank <= 3:
                user_row["podiums"] += 1
                _append_history_event_year(user_row["podium_years"], event_id, year)

            market_percentage = entry.get("market_percentage")
            if market_percentage is not None:
                current_best = user_row.get("best_market_percentage")
                if current_best is None or float(market_percentage) > float(current_best):
                    user_row["best_market_percentage"] = market_percentage
                user_row["market_percentage_sum"] += float(market_percentage)
                user_row["market_percentage_count"] += 1
                if float(market_percentage) > 99:
                    user_row["gold_trophies"] += 1
                    _append_history_event_year(user_row["gold_trophy_years"], event_id, year)
                elif float(market_percentage) > 97:
                    user_row["silver_trophies"] += 1
                    _append_history_event_year(user_row["silver_trophy_years"], event_id, year)
                elif float(market_percentage) > 95:
                    user_row["bronze_trophies"] += 1
                    _append_history_event_year(user_row["bronze_trophy_years"], event_id, year)

    users = list(users_by_id.values())
    for user_row in users:
        user_row["win_years"] = _normalize_history_event_years(user_row["win_years"])
        user_row["podium_years"] = _normalize_history_event_years(user_row["podium_years"])
        user_row["gold_trophy_years"] = _normalize_history_event_years(user_row["gold_trophy_years"])
        user_row["silver_trophy_years"] = _normalize_history_event_years(user_row["silver_trophy_years"])
        user_row["bronze_trophy_years"] = _normalize_history_event_years(user_row["bronze_trophy_years"])
        user_row["total_trophies"] = (
            int(user_row.get("gold_trophies") or 0)
            + int(user_row.get("silver_trophies") or 0)
            + int(user_row.get("bronze_trophies") or 0)
        )
        user_row["total_trophy_years"] = _normalize_history_event_years(
            {
                str(event_column["id"]): [
                    *user_row["gold_trophy_years"].get(str(event_column["id"]), []),
                    *user_row["silver_trophy_years"].get(str(event_column["id"]), []),
                    *user_row["bronze_trophy_years"].get(str(event_column["id"]), []),
                ]
                for event_column in EVENT_COLUMNS
            }
        )
        game_count = int(user_row.get("game_count") or 0)
        percentage_count = int(user_row.get("market_percentage_count") or 0)
        user_row["average_points"] = (
            float(user_row.get("total_points") or 0) / game_count if game_count else 0.0
        )
        user_row["average_market_percentage"] = (
            float(user_row.get("market_percentage_sum") or 0.0) / percentage_count
            if percentage_count
            else None
        )
        user_row["wins_tooltip"] = format_history_event_years_tooltip(user_row["win_years"])
        user_row["podiums_tooltip"] = format_history_event_years_tooltip(user_row["podium_years"])
        user_row["gold_trophies_tooltip"] = format_history_event_years_tooltip(user_row["gold_trophy_years"])
        user_row["silver_trophies_tooltip"] = format_history_event_years_tooltip(user_row["silver_trophy_years"])
        user_row["bronze_trophies_tooltip"] = format_history_event_years_tooltip(user_row["bronze_trophy_years"])
        user_row["total_trophies_tooltip"] = format_history_event_years_tooltip(user_row["total_trophy_years"])
        user_row["event_wins_tooltips"] = {
            str(event_column["id"]): format_history_event_years_tooltip(
                {
                    str(other_event["id"]): (
                        user_row["win_years"].get(str(event_column["id"]), [])
                        if str(other_event["id"]) == str(event_column["id"])
                        else []
                    )
                    for other_event in EVENT_COLUMNS
                }
            )
            for event_column in EVENT_COLUMNS
        }
    users.sort(
        key=lambda item: (
            -int(item.get("game_count") or 0),
            -int(item.get("wins") or 0),
            -(float(item.get("best_market_percentage") or 0)),
            item["username"].lower(),
            item["full_name"].lower(),
        )
    )
    return users


def build_history_trophy_rows(
    history_users: list[dict],
    *,
    selected_history_user_id: int | None = None,
) -> list[dict]:
    rows = [
        {
            **user,
            "trophy_points": (
                int(user.get("gold_trophies") or 0) * 3
                + int(user.get("silver_trophies") or 0) * 2
                + int(user.get("bronze_trophies") or 0)
            ),
        }
        for user in history_users
        if not selected_history_user_id or int(user.get("user_id") or 0) == selected_history_user_id
    ]
    rows.sort(
        key=lambda item: (
            -int(item.get("gold_trophies") or 0),
            -int(item.get("silver_trophies") or 0),
            -int(item.get("bronze_trophies") or 0),
            -int(item.get("total_trophies") or 0),
            -(float(item.get("best_market_percentage") or 0)),
            item.get("username", "").lower(),
            item.get("full_name", "").lower(),
        )
    )
    for position, row in enumerate(rows, start=1):
        row["position"] = position
    return rows


def build_history_stats_rows(
    history_users: list[dict],
    *,
    selected_history_user_id: int | None = None,
) -> list[dict]:
    rows = [
        {**user}
        for user in history_users
        if not selected_history_user_id or int(user.get("user_id") or 0) == selected_history_user_id
    ]
    rows.sort(
        key=lambda item: (
            -int(item.get("total_points") or 0),
            -float(item.get("average_points") or 0.0),
            -int(item.get("wins") or 0),
            -int(item.get("podiums") or 0),
            -(float(item.get("average_market_percentage") or 0.0) if item.get("average_market_percentage") is not None else -1.0),
            item.get("username", "").lower(),
            item.get("full_name", "").lower(),
        )
    )
    for position, row in enumerate(rows, start=1):
        row["position"] = position
    return rows


def build_archive_game_rows(games: list[dict]) -> list[dict]:
    grouped_games: dict[int, list[dict]] = {}
    for game in games:
        event_id, year = parse_game_identity(game)
        grouped_games.setdefault(year, []).append(
            {
                **game,
                "event_id": event_id,
                "event_label": EVENT_LABELS.get(event_id, str(game.get("label") or "")),
            }
        )

    rows: list[dict] = []
    for year in sorted(grouped_games.keys(), reverse=True):
        year_games = sorted(
            grouped_games[year],
            key=lambda item: EVENT_ORDER.get(str(item.get("event_id") or ""), len(EVENT_ORDER)),
        )
        rows.append({"year": year, "games": year_games})
    return rows


def build_history_compare_chips(
    history_users: list[dict],
    *,
    selected_compare_ids: list[int],
) -> list[dict]:
    selected_set = set(selected_compare_ids)
    chips: list[dict] = []
    for user in history_users:
        user_id = int(user["user_id"])
        if user_id in selected_set:
            next_ids = [item for item in selected_compare_ids if item != user_id]
        else:
            next_ids = [*selected_compare_ids, user_id]

        chips.append(
            {
                **user,
                "is_selected": user_id in selected_set,
                "next_compare_ids_param": serialize_history_compare_ids(next_ids),
            }
        )
    return chips


def history_event_group(event_id: str) -> str:
    return "klassiekerspel" if event_id == "klassiekerspel" else "grand_tours"


def attach_selected_history_user(
    overview_cards: list[dict],
    *,
    selected_history_user_id: int | None,
) -> None:
    for card in overview_cards:
        selected_entry = None
        if selected_history_user_id:
            for entry in card.get("standings", []):
                participant = entry.get("participant", {})
                if int(participant.get("UserId") or 0) == selected_history_user_id:
                    selected_entry = entry
                    break
        card["selected_user_entry"] = selected_entry


def build_history_leaderboard(
    overview_cards: list[dict],
    *,
    metric: str,
    selected_history_user_id: int | None = None,
    event_group: str | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for card in overview_cards:
        current_event_group = history_event_group(str(card.get("event_id") or ""))
        if event_group and current_event_group != event_group:
            continue

        for entry in card.get("standings", []):
            participant = entry.get("participant", {})
            user_id = int(participant.get("UserId") or 0)
            if selected_history_user_id and user_id != selected_history_user_id:
                continue
            market_percentage = entry.get("market_percentage")
            if metric == "market_percentage" and market_percentage is None:
                continue

            rows.append(
                {
                    "game": card,
                    "game_key": str(card.get("game_key") or ""),
                    "game_label": str(card.get("label") or ""),
                    "event_id": str(card.get("event_id") or ""),
                    "event_label": str(card.get("event_label") or ""),
                    "year": int(card.get("year") or 0),
                    "event_group": current_event_group,
                    "status_label": str(card.get("status_label") or ""),
                    "summary": str(card.get("summary") or ""),
                    "participant": participant,
                    "user_id": user_id,
                    "username": participant.get("Username", ""),
                    "full_name": participant.get("FullName", ""),
                    "rank": int(entry.get("rank") or 0),
                    "total_points": int(entry.get("total_points") or 0),
                    "market_percentage": market_percentage,
                    "is_current_user": bool(entry.get("is_current_user")),
                }
            )

    if metric == "total_points":
        rows.sort(
            key=lambda item: (
                -int(item.get("total_points") or 0),
                -(float(item.get("market_percentage") or 0)),
                -int(item.get("year") or 0),
                EVENT_ORDER.get(str(item.get("event_id") or ""), len(EVENT_ORDER)),
                int(item.get("rank") or 0),
                item.get("username", "").lower(),
                item.get("full_name", "").lower(),
            )
        )
    else:
        rows.sort(
            key=lambda item: (
                -float(item.get("market_percentage") or 0),
                -int(item.get("total_points") or 0),
                -int(item.get("year") or 0),
                EVENT_ORDER.get(str(item.get("event_id") or ""), len(EVENT_ORDER)),
                int(item.get("rank") or 0),
                item.get("username", "").lower(),
                item.get("full_name", "").lower(),
            )
        )

    for position, row in enumerate(rows, start=1):
        row["position"] = position

    return rows


def build_history_high_scores(
    overview_cards: list[dict],
    *,
    selected_history_user_id: int | None = None,
    event_group: str | None = None,
) -> list[dict]:
    return build_history_leaderboard(
        overview_cards,
        metric="market_percentage",
        selected_history_user_id=selected_history_user_id,
        event_group=event_group,
    )


def build_history_top_scores(
    overview_cards: list[dict],
    *,
    selected_history_user_id: int | None = None,
    event_group: str | None = None,
) -> list[dict]:
    return build_history_leaderboard(
        overview_cards,
        metric="total_points",
        selected_history_user_id=selected_history_user_id,
        event_group=event_group,
    )


def build_history_margin_rows(
    overview_cards: list[dict],
    *,
    selected_history_user_id: int | None = None,
    margin_view: str = "largest",
) -> list[dict]:
    rows: list[dict] = []
    for card in overview_cards:
        standings = card.get("standings", [])
        if not standings:
            continue

        selected_entry = None
        if selected_history_user_id:
            for entry in standings:
                participant = entry.get("participant", {})
                if int(participant.get("UserId") or 0) == selected_history_user_id:
                    selected_entry = entry
                    break
            if selected_entry is None:
                continue

        winner = standings[0]
        runner_up = standings[1] if len(standings) > 1 else None
        winner_participant = winner.get("participant", {})
        runner_up_participant = runner_up.get("participant", {}) if runner_up else {}
        winner_points = int(winner.get("total_points") or 0)
        runner_up_points = int(runner_up.get("total_points") or 0) if runner_up else 0

        rows.append(
            {
                "game": card,
                "game_key": str(card.get("game_key") or ""),
                "game_label": str(card.get("label") or ""),
                "event_id": str(card.get("event_id") or ""),
                "event_label": str(card.get("event_label") or ""),
                "year": int(card.get("year") or 0),
                "status_label": str(card.get("status_label") or ""),
                "summary": str(card.get("summary") or ""),
                "winner": winner,
                "winner_user_id": int(winner_participant.get("UserId") or 0),
                "winner_username": winner_participant.get("Username", ""),
                "winner_full_name": winner_participant.get("FullName", ""),
                "winner_points": winner_points,
                "winner_market_percentage": winner.get("market_percentage"),
                "runner_up": runner_up,
                "runner_up_user_id": int(runner_up_participant.get("UserId") or 0),
                "runner_up_username": runner_up_participant.get("Username", ""),
                "runner_up_full_name": runner_up_participant.get("FullName", ""),
                "runner_up_points": runner_up_points,
                "runner_up_market_percentage": runner_up.get("market_percentage") if runner_up else None,
                "margin_points": winner_points - runner_up_points,
                "selected_user_entry": selected_entry,
            }
        )

    if margin_view == "smallest":
        rows.sort(
            key=lambda item: (
                int(item.get("margin_points") or 0),
                -int(item.get("winner_points") or 0),
                -int(item.get("year") or 0),
                EVENT_ORDER.get(str(item.get("event_id") or ""), len(EVENT_ORDER)),
                item.get("winner_username", "").lower(),
                item.get("winner_full_name", "").lower(),
            )
        )
    else:
        rows.sort(
            key=lambda item: (
                -int(item.get("margin_points") or 0),
                -int(item.get("winner_points") or 0),
                -int(item.get("year") or 0),
                EVENT_ORDER.get(str(item.get("event_id") or ""), len(EVENT_ORDER)),
                item.get("winner_username", "").lower(),
                item.get("winner_full_name", "").lower(),
            )
        )

    for position, row in enumerate(rows, start=1):
        row["position"] = position

    return rows


def build_history_head_to_head(
    overview_cards: list[dict],
    *,
    compare_user_ids: list[int],
) -> dict:
    selected_ids = [user_id for user_id in compare_user_ids if user_id > 0]
    if len(selected_ids) < 2:
        return {
            "comparison_rows": [],
            "pair_rows": [],
            "summary_rows": [],
            "common_game_count": 0,
            "selected_user_count": len(selected_ids),
        }

    summary_by_user_id: dict[int, dict] = {
        user_id: {
            "user_id": user_id,
            "username": "",
            "full_name": "",
            "games": 0,
            "group_wins": 0,
            "pairwise_wins": 0,
            "pairwise_losses": 0,
            "pairwise_ties": 0,
            "total_points": 0,
            "total_rank": 0,
            "percentage_sum": 0.0,
            "percentage_count": 0,
            "best_points": 0,
            "best_percentage": None,
        }
        for user_id in selected_ids
    }
    pair_counts: dict[tuple[int, int], dict[str, int]] = {}
    comparison_rows: list[dict] = []

    for card in overview_cards:
        entries_by_user_id: dict[int, dict] = {}
        for entry in card.get("standings", []):
            participant = entry.get("participant", {})
            user_id = int(participant.get("UserId") or 0)
            if user_id > 0:
                entries_by_user_id[user_id] = entry

        present_ids = [user_id for user_id in selected_ids if user_id in entries_by_user_id]
        if len(present_ids) < 2:
            continue

        compare_entries: list[dict] = []
        for user_id in present_ids:
            entry = entries_by_user_id[user_id]
            participant = entry.get("participant", {})
            points = int(entry.get("total_points") or 0)
            rank = int(entry.get("rank") or 0)
            market_percentage = entry.get("market_percentage")
            compare_entries.append(
                {
                    "user_id": user_id,
                    "username": participant.get("Username", ""),
                    "full_name": participant.get("FullName", ""),
                    "rank": rank,
                    "total_points": points,
                    "market_percentage": market_percentage,
                }
            )

            summary_row = summary_by_user_id[user_id]
            summary_row["username"] = participant.get("Username", "")
            summary_row["full_name"] = participant.get("FullName", "")
            summary_row["games"] += 1
            summary_row["total_points"] += points
            summary_row["total_rank"] += rank
            if market_percentage is not None:
                summary_row["percentage_sum"] += float(market_percentage)
                summary_row["percentage_count"] += 1
                current_best_percentage = summary_row.get("best_percentage")
                if current_best_percentage is None or float(market_percentage) > float(current_best_percentage):
                    summary_row["best_percentage"] = market_percentage
            if points > int(summary_row.get("best_points") or 0):
                summary_row["best_points"] = points

        compare_entries.sort(
            key=lambda item: (
                int(item.get("rank") or 0),
                -int(item.get("total_points") or 0),
                item.get("username", "").lower(),
                item.get("full_name", "").lower(),
            )
        )
        leading_rank = min(int(item.get("rank") or 0) for item in compare_entries)
        for item in compare_entries:
            if int(item.get("rank") or 0) == leading_rank:
                summary_by_user_id[int(item["user_id"])]["group_wins"] += 1

        comparison_rows.append(
            {
                "game": card,
                "game_key": str(card.get("game_key") or ""),
                "game_label": str(card.get("label") or ""),
                "event_id": str(card.get("event_id") or ""),
                "event_label": str(card.get("event_label") or ""),
                "year": int(card.get("year") or 0),
                "summary": str(card.get("summary") or ""),
                "status_label": str(card.get("status_label") or ""),
                "subleague_name": str(card.get("subleague_name") or ""),
                "compare_entries": compare_entries,
            }
        )

        for left_index, left_user_id in enumerate(present_ids):
            left_entry = entries_by_user_id[left_user_id]
            left_rank = int(left_entry.get("rank") or 0)
            left_points = int(left_entry.get("total_points") or 0)
            for right_user_id in present_ids[left_index + 1:]:
                right_entry = entries_by_user_id[right_user_id]
                right_rank = int(right_entry.get("rank") or 0)
                right_points = int(right_entry.get("total_points") or 0)
                pair_key = tuple(sorted((left_user_id, right_user_id)))
                pair_row = pair_counts.setdefault(
                    pair_key,
                    {
                        "user_a_id": pair_key[0],
                        "user_b_id": pair_key[1],
                        "user_a_wins": 0,
                        "user_b_wins": 0,
                        "ties": 0,
                        "games": 0,
                    },
                )
                pair_row["games"] += 1

                if left_rank < right_rank or (
                    left_rank == right_rank and left_points > right_points
                ):
                    winner_id = left_user_id
                elif right_rank < left_rank or (
                    left_rank == right_rank and right_points > left_points
                ):
                    winner_id = right_user_id
                else:
                    winner_id = 0

                if winner_id == 0:
                    pair_row["ties"] += 1
                    summary_by_user_id[left_user_id]["pairwise_ties"] += 1
                    summary_by_user_id[right_user_id]["pairwise_ties"] += 1
                elif winner_id == pair_key[0]:
                    pair_row["user_a_wins"] += 1
                    summary_by_user_id[pair_key[0]]["pairwise_wins"] += 1
                    summary_by_user_id[pair_key[1]]["pairwise_losses"] += 1
                else:
                    pair_row["user_b_wins"] += 1
                    summary_by_user_id[pair_key[1]]["pairwise_wins"] += 1
                    summary_by_user_id[pair_key[0]]["pairwise_losses"] += 1

    comparison_rows.sort(
        key=lambda item: (
            -int(item.get("year") or 0),
            EVENT_ORDER.get(str(item.get("event_id") or ""), len(EVENT_ORDER)),
            item.get("game_label", "").lower(),
        )
    )

    summary_rows: list[dict] = []
    for user_id in selected_ids:
        summary_row = summary_by_user_id[user_id]
        games = int(summary_row.get("games") or 0)
        percentage_count = int(summary_row.get("percentage_count") or 0)
        summary_rows.append(
            {
                **summary_row,
                "average_points": (
                    float(summary_row["total_points"]) / games if games else 0.0
                ),
                "average_rank": (
                    float(summary_row["total_rank"]) / games if games else 0.0
                ),
                "average_percentage": (
                    float(summary_row["percentage_sum"]) / percentage_count
                    if percentage_count
                    else None
                ),
            }
        )

    summary_rows.sort(
        key=lambda item: (
            -int(item.get("pairwise_wins") or 0),
            -int(item.get("group_wins") or 0),
            -int(item.get("total_points") or 0),
            item.get("username", "").lower(),
            item.get("full_name", "").lower(),
        )
    )

    pair_rows: list[dict] = []
    for pair_key, pair_row in pair_counts.items():
        user_a_summary = summary_by_user_id.get(pair_key[0], {})
        user_b_summary = summary_by_user_id.get(pair_key[1], {})
        pair_rows.append(
            {
                **pair_row,
                "user_a_username": user_a_summary.get("username", ""),
                "user_a_full_name": user_a_summary.get("full_name", ""),
                "user_b_username": user_b_summary.get("username", ""),
                "user_b_full_name": user_b_summary.get("full_name", ""),
            }
        )

    pair_rows.sort(
        key=lambda item: (
            -int(item.get("games") or 0),
            -abs(int(item.get("user_a_wins") or 0) - int(item.get("user_b_wins") or 0)),
            item.get("user_a_username", "").lower(),
            item.get("user_b_username", "").lower(),
        )
    )

    total_points_leader = max(
        summary_rows,
        key=lambda item: (
            int(item.get("total_points") or 0),
            int(item.get("group_wins") or 0),
        ),
        default=None,
    )
    average_points_leader = max(
        summary_rows,
        key=lambda item: (
            float(item.get("average_points") or 0.0),
            int(item.get("games") or 0),
        ),
        default=None,
    )
    average_percentage_leader = max(
        summary_rows,
        key=lambda item: (
            float(item.get("average_percentage") or 0.0)
            if item.get("average_percentage") is not None
            else -1.0,
            int(item.get("games") or 0),
        ),
        default=None,
    )
    pairwise_wins_leader = max(
        summary_rows,
        key=lambda item: (
            int(item.get("pairwise_wins") or 0),
            -int(item.get("pairwise_losses") or 0),
        ),
        default=None,
    )

    return {
        "comparison_rows": comparison_rows,
        "pair_rows": pair_rows,
        "summary_rows": summary_rows,
        "common_game_count": len(comparison_rows),
        "selected_user_count": len(selected_ids),
        "leaders": {
            "total_points": total_points_leader,
            "average_points": average_points_leader,
            "average_percentage": average_percentage_leader,
            "pairwise_wins": pairwise_wins_leader,
        },
    }


def probe_archive_game(
    *,
    client: ScoritoClient,
    market_id: int,
    participants: list[dict],
    latest_finished_round: dict | None,
) -> dict:
    probe = {
        "is_archive": False,
        "sample_team_selection_size": None,
        "sample_stage_selection_size": None,
    }
    if not participants or not latest_finished_round:
        return probe

    sample_user_id = int(participants[0].get("UserId") or 0)
    if sample_user_id <= 0:
        return probe

    team_selection = client.get_team_selection(market_id, sample_user_id)
    stage_selection = client.get_stage_selection(
        int(latest_finished_round["MarketRoundId"]),
        sample_user_id,
    )
    team_selection_size = len(team_selection)
    stage_selection_size = len(stage_selection.get("RiderIds", []))
    captain_id = int(stage_selection.get("CaptainId") or 0)

    probe.update(
        {
            "sample_team_selection_size": team_selection_size,
            "sample_stage_selection_size": stage_selection_size,
            "is_archive": (
                team_selection_size == 0
                and stage_selection_size == 0
                and captain_id == 0
            ),
        }
    )
    return probe


def build_archive_view_tabs(
    *,
    archive_total_rider_scores: list,
    archive_standings: list[dict],
    archive_stage_points: list,
) -> list[dict]:
    tabs: list[dict] = []
    if archive_standings:
        tabs.append({"id": "standings", "label": "Eindstand"})
    if archive_total_rider_scores:
        tabs.append({"id": "totals", "label": "Totaalscore"})
    if archive_stage_points:
        tabs.append({"id": "stagepoints", "label": "Renner punten per etappe"})
    return tabs


def build_archive_participants(
    participants: list[dict],
    archive_standings: list[dict] | None = None,
) -> list[dict]:
    standings_by_user_id = {
        int(item["participant"]["UserId"]): item
        for item in (archive_standings or [])
    }
    rows = [
        {
            "user_id": int(participant.get("UserId") or 0),
            "username": participant.get("Username", ""),
            "full_name": participant.get("FullName", ""),
            "join_sequence": int(participant.get("JoinSequence") or 0),
            "rank": (
                standings_by_user_id.get(int(participant.get("UserId") or 0), {}).get("rank")
            ),
            "total_points": (
                standings_by_user_id.get(int(participant.get("UserId") or 0), {}).get("total_points")
            ),
            "market_percentage": (
                standings_by_user_id.get(int(participant.get("UserId") or 0), {}).get("market_percentage")
            ),
        }
        for participant in participants
    ]
    rows.sort(
        key=lambda item: (
            item["username"].lower(),
            item["full_name"].lower(),
            item["join_sequence"],
        )
    )
    return rows


def build_archive_summary(
    *,
    rounds: list[dict],
    participants: list[dict],
    rider_count: int,
    classification_panels: list[dict],
    archive_standings: list[dict],
    archive_stage_points: list,
    selected_round: dict | None,
    archive_probe: dict,
    market_score_summary: dict | None,
) -> dict:
    finished_rounds = [
        item for item in rounds if int(item.get("StageStatus", -1)) == 2
    ]
    finished_round_count = len(finished_rounds)
    total_round_count = len(rounds)
    selected_stage_order = (
        int(selected_round.get("StageOrder") or 0) if selected_round else None
    )
    archive_winner = archive_standings[0] if archive_standings else None
    archive_percentages_available = any(
        item.get("market_percentage") is not None for item in archive_standings
    )

    if total_round_count and finished_round_count != total_round_count:
        stage_detail = (
            f"Scorito markeert {finished_round_count} van {total_round_count} etappes nog als afgerond."
        )
    else:
        stage_detail = f"{finished_round_count} bewaarde etappes zijn nog zichtbaar."

    return {
        "message": (
            "Scorito bewaart dit spel nog als subleague, maar de managerploegen, "
            "etappe-opstellingen en ploegselecties zijn verdwenen. "
            "De eindscores en de Scorito %-score per deelnemer zijn wel nog terug te vinden."
        ),
        "stats": [
            {
                "label": "Deelnemers",
                "value": len(participants),
                "detail": "Actieve subleague-leden",
            },
            {
                "label": "Etappes",
                "value": finished_round_count,
                "detail": stage_detail,
            },
            {
                "label": "Winnaar",
                "value": (
                    archive_winner["total_points"]
                    if archive_winner
                    else 0
                ),
                "detail": (
                    f"{archive_winner['participant'].get('Username', '')} leidt deze subleague."
                    if archive_winner
                    else "Geen eindscore gevonden."
                ),
            },
            {
                "label": "Klassementen",
                "value": len(classification_panels),
                "detail": "Algemeen, punten, berg en jongeren",
            },
            {
                "label": "Scorito max",
                "value": int((market_score_summary or {}).get("MaxPoints") or 0),
                "detail": "Hoogste totale score in het hele Scorito-spel",
            },
            {
                "label": "Scorito gem.",
                "value": int((market_score_summary or {}).get("AveragePoints") or 0),
                "detail": "Gemiddelde totale score in het hele Scorito-spel",
            },
        ],
        "capabilities": [
            {
                "label": "Subleague-leden",
                "available": bool(participants),
                "detail": f"{len(participants)} actieve deelnemers blijven zichtbaar.",
            },
            {
                "label": "Etappekalender",
                "available": bool(finished_rounds),
                "detail": stage_detail,
            },
            {
                "label": "Rennerspool",
                "available": rider_count > 0,
                "detail": f"{rider_count} renners kunnen nog worden opgehaald.",
            },
            {
                "label": "Klassementen",
                "available": bool(classification_panels),
                "detail": (
                    f"{len(classification_panels)} klassementen blijven beschikbaar."
                    if classification_panels
                    else "Scorito geeft geen klassementen meer terug."
                ),
            },
            {
                "label": "Eindscores per deelnemer",
                "available": bool(archive_standings),
                "detail": (
                    f"{len(archive_standings)} deelnemers hebben een bewaarde totaalscore."
                    if archive_standings
                    else "Er kwam geen eindscore per deelnemer terug."
                ),
            },
            {
                "label": "Scorito % per deelnemer",
                "available": archive_percentages_available,
                "detail": (
                    "De globale Scorito %-score is per deelnemer nog beschikbaar."
                    if archive_percentages_available
                    else "De Scorito %-score ontbreekt voor deze deelnemers."
                ),
            },
            {
                "label": "Scorito-punten per etappe",
                "available": bool(archive_stage_points),
                "detail": (
                    f"{len(archive_stage_points)} renners met punten in etappe {selected_stage_order}."
                    if archive_stage_points and selected_stage_order
                    else "Voor de gekozen etappe kwamen geen punten terug."
                ),
            },
            {
                "label": "Managerploegen",
                "available": False,
                "detail": (
                    "Scorito geeft voor een testdeelnemer 0 ploegselecties terug."
                    if archive_probe["sample_team_selection_size"] == 0
                    else "Managerploegen ontbreken in de historische respons."
                ),
            },
            {
                "label": "Etappe-opstellingen",
                "available": False,
                "detail": (
                    "Scorito geeft voor een testdeelnemer 0 geselecteerde renners terug."
                    if archive_probe["sample_stage_selection_size"] == 0
                    else "Etappe-opstellingen ontbreken in de historische respons."
                ),
            },
            {
                "label": "Betrouwbare subleague-stand",
                "available": bool(archive_standings),
                "detail": (
                    "De rangorde is opnieuw opgebouwd uit de bewaarde finale Scorito-punten."
                    if archive_standings
                    else "Er is geen bruikbare rangorde teruggekomen."
                ),
            },
        ],
    }


def choose_active_view(view_tabs: list[dict], requested_view: str) -> str:
    available_view_ids = {tab["id"] for tab in view_tabs}
    if requested_view in available_view_ids:
        return requested_view
    return view_tabs[0]["id"] if view_tabs else ""


def merge_current_standings_into_projected_final_scores(
    projected_final_scores: list[dict],
    current_standings: list[dict],
) -> None:
    standings_by_user_id = {
        int(item["participant"]["UserId"]): item for item in current_standings
    }

    for score in projected_final_scores:
        user_id = int(score["participant"]["UserId"])
        current_standing = standings_by_user_id.get(user_id)
        score["current_rank"] = current_standing.get("rank") if current_standing else None
        score["current_points"] = (
            current_standing.get("total_points")
            if current_standing
            else None
        )
        score["total_projected_points"] = (
            (score["current_points"] or 0) + score["total_projected_final_points"]
        )

    projected_final_scores.sort(
        key=lambda item: (
            -item["total_projected_points"],
            -(item["current_points"] or 0),
            -item["total_projected_final_points"],
            -item["individual_final_points"],
            -item["teammate_winner_points"],
            item["participant"].get("Username", "").lower(),
            item["participant"].get("FullName", "").lower(),
        )
    )
    for index, item in enumerate(projected_final_scores, start=1):
        item["rank"] = index


def nice_axis_step(max_value: int, *, target_steps: int = 5) -> int:
    if max_value <= 0:
        return 50

    rough_step = max_value / max(1, target_steps)
    magnitude = 10 ** math.floor(math.log10(rough_step))
    normalized = rough_step / magnitude

    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 2.5:
        nice = 2.5
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10

    return max(1, int(nice * magnitude))


def build_score_trend_chart(stage_score_matrix: dict) -> dict:
    stages = stage_score_matrix.get("stages", [])
    rows = stage_score_matrix.get("rows", [])
    if not stages or not rows:
        return {"stages": [], "series": [], "y_ticks": [], "width": 0, "height": 0}

    ordered_stages = sorted(stages, key=lambda item: int(item.get("stage_order") or 0))
    stage_ids = [int(stage["market_round_id"]) for stage in ordered_stages]

    width = max(900, 110 + (len(stage_ids) * 90))
    height = 460
    margin_left = 72
    margin_right = 36
    margin_top = 26
    margin_bottom = 54
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    leader_totals_by_stage = {
        stage_id: max(
            (
                int(row.get("cumulative_points_by_round", {}).get(stage_id, 0))
                for row in rows
            ),
            default=0,
        )
        for stage_id in stage_ids
    }
    max_gap = max(
        (
            max(
                0,
                leader_totals_by_stage.get(stage_id, 0)
                - int(row.get("cumulative_points_by_round", {}).get(stage_id, 0)),
            )
            for row in rows
            for stage_id in stage_ids
        ),
        default=0,
    )
    y_step = nice_axis_step(max_gap, target_steps=6)
    y_max = max(y_step * 4, int(math.ceil(max_gap / y_step) * y_step) if max_gap else y_step * 4)

    def x_position(index: int) -> float:
        if len(stage_ids) == 1:
            return margin_left + (plot_width / 2)
        return margin_left + (plot_width * index / (len(stage_ids) - 1))

    def y_position(value: int) -> float:
        if y_max <= 0:
            return margin_top + plot_height
        return margin_top + plot_height - ((value / y_max) * plot_height)

    y_ticks = []
    tick_value = 0
    while tick_value <= y_max:
        y_ticks.append(
            {
                "value": tick_value,
                "label": str(tick_value),
                "y": round(y_position(tick_value), 2),
            }
        )
        tick_value += y_step

    chart_stages = [
        {
            "market_round_id": stage_id,
            "stage_order": ordered_stages[index]["stage_order"],
            "x": round(x_position(index), 2),
        }
        for index, stage_id in enumerate(stage_ids)
    ]

    palette = [
        "#69aef7",
        "#39d57f",
        "#ff8b5c",
        "#ff6f8f",
        "#9e89ff",
        "#7ce0d5",
        "#ffa9d0",
        "#c4e06b",
        "#9fd3ff",
        "#ffb347",
        "#91f2b2",
        "#d8b5ff",
    ]

    series = []
    palette_index = 0
    for row in rows:
        color = palette[palette_index % len(palette)]
        palette_index += 1

        cumulative_points = row.get("cumulative_points_by_round", {})
        point_dicts = []
        for index, stage_id in enumerate(stage_ids):
            total_points = int(cumulative_points.get(stage_id, 0))
            gap_to_leader = max(0, leader_totals_by_stage.get(stage_id, 0) - total_points)
            point_dicts.append(
                {
                    "x": round(x_position(index), 2),
                    "y": round(y_position(gap_to_leader), 2),
                    "value": gap_to_leader,
                    "gap_to_leader": gap_to_leader,
                    "total_points": total_points,
                    "stage_order": ordered_stages[index]["stage_order"],
                }
            )

        points_attr = " ".join(f"{point['x']},{point['y']}" for point in point_dicts)
        participant = row["participant"]
        final_total_points = int(cumulative_points.get(stage_ids[-1], 0))
        series.append(
            {
                "name": participant.get("Username", "") or participant.get("FullName", ""),
                "username": participant.get("Username", ""),
                "color": color,
                "stroke_width": 2.4,
                "opacity": 0.82,
                "marker_radius": 3.2,
                "points": point_dicts,
                "points_attr": points_attr,
                "total_points": row.get("total_points", 0),
                "gap_to_leader": max(0, leader_totals_by_stage.get(stage_ids[-1], 0) - final_total_points),
            }
        )

    return {
        "width": width,
        "height": height,
        "plot_top": margin_top,
        "plot_right": width - margin_right,
        "plot_bottom": height - margin_bottom,
        "plot_left": margin_left,
        "stages": chart_stages,
        "y_ticks": y_ticks,
        "series": series,
    }


def build_stage_result_snapshots(stage_score_matrix: dict) -> list[dict]:
    stages = stage_score_matrix.get("stages", [])
    rows = stage_score_matrix.get("rows", [])
    if not stages or not rows:
        return []

    ordered_stages = sorted(stages, key=lambda item: int(item.get("stage_order") or 0))
    snapshots: list[dict] = []

    for stage in ordered_stages:
        market_round_id = int(stage.get("market_round_id") or 0)
        if market_round_id <= 0:
            continue

        entries: list[dict] = []
        for row in rows:
            participant = row["participant"]
            stage_meta = next(
                (
                    item
                    for item in row.get("stage_points", [])
                    if int(item.get("market_round_id") or 0) == market_round_id
                ),
                None,
            )
            stage_points = int(row.get("stage_points_by_round", {}).get(market_round_id, 0))
            cumulative_points = int(row.get("cumulative_points_by_round", {}).get(market_round_id, 0))
            entries.append(
                {
                    "name": participant.get("Username", "") or participant.get("FullName", ""),
                    "username": participant.get("Username", ""),
                    "stage_points": stage_points,
                    "cumulative_points": cumulative_points,
                    "is_stage_winner": bool(stage_meta and stage_meta.get("is_stage_winner")),
                    "is_subleague_leader": bool(stage_meta and stage_meta.get("is_subleague_leader")),
                }
            )

        entries.sort(
            key=lambda item: (
                -item["stage_points"],
                -item["cumulative_points"],
                item["username"].lower(),
                item["name"].lower(),
            )
        )

        last_score_key: tuple[int, int] | None = None
        current_rank = 0
        for position, entry in enumerate(entries, start=1):
            score_key = (entry["stage_points"], entry["cumulative_points"])
            if score_key != last_score_key:
                current_rank = position
                last_score_key = score_key
            entry["rank"] = current_rank

        winner_names = [entry["username"] for entry in entries if entry["is_stage_winner"]]
        leader_names = [entry["username"] for entry in entries if entry["is_subleague_leader"]]

        snapshots.append(
            {
                "market_round_id": market_round_id,
                "stage_order": int(stage.get("stage_order") or 0),
                "winner_score": int(stage.get("winner_score") or 0),
                "winner_names": winner_names,
                "leader_names": leader_names,
                "entries": entries,
            }
        )

    return snapshots


@app.route("/")
def index():
    requested_game_key = (request.args.get("game", type=str) or "").strip().lower()
    current_page = choose_page(request.args.get("page", type=str) or "")
    requested_history_view = (
        request.args.get("history_view", type=str) or ""
    ).strip().lower()
    requested_history_scores_view = (
        request.args.get("history_scores_view", type=str) or ""
    ).strip().lower()
    requested_history_stats_view = (
        request.args.get("history_stats_view", type=str) or ""
    ).strip().lower()
    requested_history_margin_view = (
        request.args.get("history_margin_view", type=str) or ""
    ).strip().lower()
    requested_history_compare_ids = (
        request.args.get("history_compare_ids", type=str) or ""
    ).strip()
    requested_history_user_id = request.args.get("history_user_id", type=int)
    history_view = choose_history_view(requested_history_view)
    history_scores_view = choose_history_scores_view(requested_history_scores_view)
    history_stats_view = choose_history_stats_view(requested_history_stats_view)
    history_margin_view = choose_history_margin_view(requested_history_margin_view)
    history_user_id = choose_history_user_id(requested_history_user_id)
    page_games = build_page_game_options(current_page)
    selected_game = choose_game(
        requested_game_key or get_default_game_key(),
        current_page=current_page,
    )
    market_id = int(selected_game["market_id"])
    selected_subleague = build_selected_subleague(selected_game)
    requested_market_round_id = request.args.get("market_round_id", type=int)
    requested_view = (request.args.get("view", type=str) or "").strip()

    context = {
        "games": page_games,
        "selected_game": selected_game,
        "current_page": current_page,
        "requested_history_view": requested_history_view,
        "history_view": history_view,
        "requested_history_scores_view": requested_history_scores_view,
        "history_scores_view": history_scores_view,
        "requested_history_stats_view": requested_history_stats_view,
        "history_stats_view": history_stats_view,
        "requested_history_margin_view": requested_history_margin_view,
        "history_margin_view": history_margin_view,
        "requested_history_compare_ids": requested_history_compare_ids,
        "history_compare_ids": [],
        "history_compare_ids_param": "",
        "history_compare_chips": [],
        "selected_history_compare_users": [],
        "history_head_to_head": {
            "comparison_rows": [],
            "pair_rows": [],
            "summary_rows": [],
            "common_game_count": 0,
            "selected_user_count": 0,
            "leaders": {
                "total_points": None,
                "average_points": None,
                "average_percentage": None,
                "pairwise_wins": None,
            },
        },
        "history_event_columns": EVENT_COLUMNS,
        "history_year_rows": [],
        "history_high_scores": [],
        "history_high_scores_by_group": {
            "grand_tours": [],
            "klassiekerspel": [],
        },
        "history_top_scores_by_group": {
            "grand_tours": [],
            "klassiekerspel": [],
        },
        "history_stats_rows": [],
        "history_trophy_rows": [],
        "history_margin_rows": [],
        "history_users": [],
        "selected_history_user_id": history_user_id,
        "selected_history_user": None,
        "requested_market_round_id": requested_market_round_id,
        "requested_view": requested_view,
        "overview_podiums": [],
        "market_id": market_id,
        "selected_subleague": selected_subleague,
        "rounds": [],
        "stage_button_rounds": [],
        "view_tabs": [],
        "active_view": "",
        "selected_round": None,
        "lineups": [],
        "rider_picker_view": [],
        "recommended_riders": [],
        "classification_panels": [],
        "display_round": None,
        "classification_round": None,
        "projected_final_scores": [],
        "stage_score_matrix": {"stages": [], "rows": []},
        "score_trend_chart": {"stages": [], "series": [], "y_ticks": [], "width": 0, "height": 0},
        "stage_result_snapshots": [],
        "selected_stage_result_market_round_id": None,
        "current_standings": [],
        "is_archive_game": False,
        "archive_standings": [],
        "archive_stage_points": [],
        "archive_total_rider_scores": [],
        "is_live_stage": False,
        "is_upcoming_stage": False,
        "is_next_stage_preview": False,
        "show_stage_lineups": True,
        "error": None,
        "status_label": stage_status_label,
        "archive_game_rows": build_archive_game_rows(page_games) if current_page == "archive" else [],
    }

    try:
        client = get_client()
        if current_page == "history":
            overview_podiums = build_overview_podiums(
                client,
                selected_game_key=None,
                selected_game_card=None,
            )
            apply_history_manager_aliases(overview_podiums)
            history_users = build_history_users(overview_podiums)
            valid_user_ids = {int(user["user_id"]) for user in history_users}
            selected_history_user_id = (
                history_user_id if history_user_id in valid_user_ids else None
            )
            history_compare_ids = choose_history_compare_ids(
                requested_history_compare_ids,
                valid_user_ids=valid_user_ids,
            )
            attach_selected_history_user(
                overview_podiums,
                selected_history_user_id=selected_history_user_id,
            )
            context["overview_podiums"] = overview_podiums
            context["history_users"] = history_users
            context["selected_history_user_id"] = selected_history_user_id
            context["history_compare_ids"] = history_compare_ids
            context["history_compare_ids_param"] = serialize_history_compare_ids(history_compare_ids)
            context["history_compare_chips"] = build_history_compare_chips(
                history_users,
                selected_compare_ids=history_compare_ids,
            )
            context["selected_history_compare_users"] = [
                user for user in history_users if int(user["user_id"]) in set(history_compare_ids)
            ]
            context["selected_history_user"] = next(
                (
                    user
                    for user in history_users
                    if int(user["user_id"]) == int(selected_history_user_id or 0)
                ),
                None,
            )
            context["history_stats_rows"] = build_history_stats_rows(
                history_users,
                selected_history_user_id=selected_history_user_id,
            )
            context["history_trophy_rows"] = build_history_trophy_rows(
                history_users,
                selected_history_user_id=selected_history_user_id,
            )
            context["history_year_rows"] = build_history_year_rows(overview_podiums)
            context["history_high_scores"] = build_history_high_scores(
                overview_podiums,
                selected_history_user_id=selected_history_user_id,
            )
            context["history_high_scores_by_group"] = {
                "grand_tours": build_history_high_scores(
                    overview_podiums,
                    selected_history_user_id=selected_history_user_id,
                    event_group="grand_tours",
                ),
                "klassiekerspel": build_history_high_scores(
                    overview_podiums,
                    selected_history_user_id=selected_history_user_id,
                    event_group="klassiekerspel",
                ),
            }
            context["history_margin_rows"] = build_history_margin_rows(
                overview_podiums,
                selected_history_user_id=selected_history_user_id,
                margin_view=history_margin_view,
            )
            context["history_head_to_head"] = build_history_head_to_head(
                overview_podiums,
                compare_user_ids=history_compare_ids,
            )
            context["history_top_scores_by_group"] = {
                "grand_tours": build_history_top_scores(
                    overview_podiums,
                    selected_history_user_id=selected_history_user_id,
                    event_group="grand_tours",
                ),
                "klassiekerspel": build_history_top_scores(
                    overview_podiums,
                    selected_history_user_id=selected_history_user_id,
                    event_group="klassiekerspel",
                ),
            }
            return render_template("index.html", **context)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            rounds_future = executor.submit(client.get_market_rounds, market_id)
            participants_future = executor.submit(
                client.get_subleague_participants,
                int(selected_subleague["Id"]),
            )
            rounds = rounds_future.result()
            participants = participants_future.result()

        classification_round = choose_latest_finished_round(rounds)
        if uses_archive_only_flow(selected_game):
            archive_probe = {
                "is_archive": True,
                "sample_team_selection_size": None,
                "sample_stage_selection_size": None,
            }
            is_archive_game = True
        else:
            archive_probe = probe_archive_game(
                client=client,
                market_id=market_id,
                participants=participants,
                latest_finished_round=classification_round,
            )
            is_archive_game = bool(archive_probe["is_archive"])

        if is_archive_game:
            selected_round = choose_archive_round(rounds, requested_market_round_id)
            if not selected_round:
                raise ScoritoError(
                    "Scorito bewaart voor dit oude spel geen afgeronde etappes meer."
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                archive_standings_future = executor.submit(
                    client.build_archive_standings,
                    market_id=market_id,
                    subleague_id=int(selected_subleague["Id"]),
                )
                archive_total_rider_scores_future = executor.submit(
                    client.build_total_rider_scores,
                    market_id=market_id,
                )
                archive_stage_points_future = executor.submit(
                    client.build_recommended_riders,
                    market_id=market_id,
                    points_market_round_id=int(selected_round["MarketRoundId"]),
                    points_mode="all",
                )

                archive_standings = archive_standings_future.result()
                archive_total_rider_scores = archive_total_rider_scores_future.result()
                archive_stage_points = archive_stage_points_future.result()
                apply_manager_display_aliases_to_rows(archive_standings)

            stage_button_rounds = build_archive_stage_button_rounds(rounds)
            view_tabs = build_archive_view_tabs(
                archive_total_rider_scores=archive_total_rider_scores,
                archive_standings=archive_standings,
                archive_stage_points=archive_stage_points,
            )
            active_view = choose_active_view(view_tabs, requested_view)

            context.update(
                {
                    "rounds": rounds,
                    "stage_button_rounds": stage_button_rounds,
                    "view_tabs": view_tabs,
                    "active_view": active_view,
                    "selected_round": selected_round,
                    "display_round": selected_round,
                    "is_archive_game": True,
                    "archive_standings": archive_standings,
                    "archive_stage_points": archive_stage_points,
                    "archive_total_rider_scores": archive_total_rider_scores,
                    "show_stage_lineups": False,
                }
            )
        else:
            current_round = choose_current_round(rounds)
            next_round = choose_next_round(rounds, current_round)
            stage_button_rounds = build_stage_button_rounds(rounds)
            selected_round = choose_market_round(rounds, requested_market_round_id)
            display_round = choose_points_source_round(rounds, selected_round)
            is_live_stage = bool(
                selected_round and int(selected_round.get("StageStatus", -1)) == 1
            )
            is_upcoming_stage = bool(
                selected_round and int(selected_round.get("StageStatus", -1)) == 0
            )
            is_next_stage_preview = bool(
                selected_round
                and next_round
                and int(selected_round.get("MarketRoundId") or 0)
                == int(next_round.get("MarketRoundId") or 0)
            )
            show_stage_lineups = not is_upcoming_stage
            finished_round_ids = [
                int(item["MarketRoundId"])
                for item in sorted(rounds, key=lambda round_item: round_item["StageOrder"])
                if int(item.get("StageStatus", -1)) == 2
            ]
            finished_round_stage_orders = {
                int(item["MarketRoundId"]): int(item["StageOrder"])
                for item in rounds
                if int(item.get("StageStatus", -1)) == 2
            }

            if not selected_round:
                raise ScoritoError("Er is geen etappe-informatie gevonden voor deze markt.")

            lineups = []
            rider_picker_view = []
            recommended_riders: list = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                lineups_future = None
                recommended_riders_future = None
                if show_stage_lineups:
                    lineups_future = executor.submit(
                        client.build_lineups,
                        market_id=market_id,
                        subleague_id=int(selected_subleague["Id"]),
                        market_round_id=int(selected_round["MarketRoundId"]),
                        points_market_round_id=(
                            int(display_round["MarketRoundId"]) if display_round else None
                        ),
                        points_mode=(
                            "classification_team"
                            if int(selected_round.get("StageStatus", -1)) != 2
                            else "all"
                        ),
                        include_bench=int(selected_round.get("StageStatus", -1)) == 2,
                    )
                elif is_upcoming_stage and display_round:
                    recommended_riders_future = executor.submit(
                        client.build_recommended_riders,
                        market_id=market_id,
                        points_market_round_id=int(display_round["MarketRoundId"]),
                    )

                classification_panels_future = executor.submit(
                    client.build_classification_panels,
                    market_id,
                )
                projected_final_scores_future = executor.submit(
                    client.build_projected_final_classification_scores,
                    market_id=market_id,
                    subleague_id=int(selected_subleague["Id"]),
                )
                stage_score_matrix_future = executor.submit(
                    client.build_stage_score_matrix,
                    market_id=market_id,
                    subleague_id=int(selected_subleague["Id"]),
                    finished_market_round_ids=finished_round_ids,
                    finished_round_stage_orders=finished_round_stage_orders,
                )
                current_standings_future = executor.submit(
                    client.build_subleague_standings,
                    market_id=market_id,
                    subleague_id=int(selected_subleague["Id"]),
                    finished_market_round_ids=finished_round_ids,
                    finished_round_stage_orders=finished_round_stage_orders,
                )

                if lineups_future is not None:
                    lineups = lineups_future.result()
                    apply_manager_display_aliases_to_lineups(lineups)
                    rider_picker_view = build_rider_picker_view(lineups)
                if recommended_riders_future is not None:
                    recommended_riders = recommended_riders_future.result()

                classification_panels = classification_panels_future.result()
                projected_final_scores = projected_final_scores_future.result()
                apply_manager_display_aliases_to_rows(projected_final_scores)
                stage_score_matrix = stage_score_matrix_future.result()
                apply_manager_display_aliases_to_stage_score_matrix(stage_score_matrix)
                score_trend_chart = build_score_trend_chart(stage_score_matrix)
                stage_result_snapshots = build_stage_result_snapshots(stage_score_matrix)
                current_standings = current_standings_future.result()
                apply_manager_display_aliases_to_rows(current_standings)
                merge_current_standings_into_projected_final_scores(
                    projected_final_scores,
                    current_standings,
                )
                selected_stage_result_market_round_id = None
                if selected_round:
                    selected_stage_result_market_round_id = next(
                        (
                            snapshot["market_round_id"]
                            for snapshot in stage_result_snapshots
                            if snapshot["market_round_id"]
                            == int(selected_round.get("MarketRoundId") or 0)
                        ),
                        None,
                    )
                if selected_stage_result_market_round_id is None and stage_result_snapshots:
                    selected_stage_result_market_round_id = stage_result_snapshots[-1]["market_round_id"]
                view_tabs = build_view_tabs(
                    show_stage_lineups=show_stage_lineups,
                    is_upcoming_stage=is_upcoming_stage,
                    lineups=lineups,
                    rider_picker_view=rider_picker_view,
                    recommended_riders=recommended_riders,
                    classification_panels=classification_panels,
                    projected_final_scores=projected_final_scores,
                    current_standings=current_standings,
                    stage_score_matrix=stage_score_matrix,
                )
                active_view = choose_active_view(view_tabs, requested_view)

            context.update(
                {
                    "selected_game": selected_game,
                    "selected_subleague": selected_subleague,
                    "rounds": rounds,
                    "stage_button_rounds": stage_button_rounds,
                    "view_tabs": view_tabs,
                    "active_view": active_view,
                    "selected_round": selected_round,
                    "display_round": display_round,
                    "classification_round": classification_round,
                    "lineups": lineups,
                    "rider_picker_view": rider_picker_view,
                    "recommended_riders": recommended_riders,
                    "classification_panels": classification_panels,
                    "projected_final_scores": projected_final_scores,
                    "stage_score_matrix": stage_score_matrix,
                    "score_trend_chart": score_trend_chart,
                    "stage_result_snapshots": stage_result_snapshots,
                    "selected_stage_result_market_round_id": selected_stage_result_market_round_id,
                    "current_standings": current_standings,
                    "is_live_stage": is_live_stage,
                    "is_upcoming_stage": is_upcoming_stage,
                    "is_next_stage_preview": is_next_stage_preview,
                    "show_stage_lineups": show_stage_lineups,
                }
            )
    except RuntimeError as exc:
        context["error"] = str(exc)
    except ScoritoAuthError:
        context["error"] = "Inloggen bij Scorito is mislukt. Controleer het ingestelde e-mailadres en wachtwoord."
    except ScoritoError as exc:
        context["error"] = str(exc)
    except Exception as exc:  # pragma: no cover - defensive fallback
        context["error"] = f"Onverwachte fout: {exc}"

    return render_template("index.html", **context)


@app.route("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
