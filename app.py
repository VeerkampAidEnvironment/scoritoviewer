from __future__ import annotations

import concurrent.futures
import os
import threading
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


def get_market_id() -> int:
    return int(os.getenv("SCORITO_MARKET_ID", "309"))


def get_default_subleague_id() -> int | None:
    raw_value = os.getenv("SCORITO_DEFAULT_SUBLEAGUE_ID", "").strip()
    return int(raw_value) if raw_value else None


def get_client() -> ScoritoClient:
    email = os.getenv("SCORITO_EMAIL", "").strip()
    password = os.getenv("SCORITO_PASSWORD", "").strip()
    if not email or not password:
        searched_locations = ", ".join(str(path) for path in ENV_CANDIDATE_PATHS)
        loaded_message = (
            f" Loaded env file(s): {', '.join(str(path) for path in LOADED_ENV_PATHS)}."
            if LOADED_ENV_PATHS
            else ""
        )
        raise RuntimeError(
            "Missing Scorito credentials. "
            "Set SCORITO_EMAIL and SCORITO_PASSWORD in environment variables, "
            "or create a .env/.env.txt file. "
            f"Searched default locations: {searched_locations}."
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
        {"round": item, "nav_label": "Played"}
        for item in finished_rounds
    ]

    if current_round:
        button_rounds.append(
            {
                "round": current_round,
                "nav_label": "Live" if int(current_round.get("StageStatus", -1)) == 1 else "Current",
            }
        )
    if next_round:
        button_rounds.append({"round": next_round, "nav_label": "Next"})

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
                    "is_current_user": lineup.get("is_current_user", False),
                    "is_captain": rider.is_captain,
                    "display_points": rider.display_points,
                }
            )

    rider_card_list = list(rider_cards.values())
    for card in rider_card_list:
        card["pickers"].sort(
            key=lambda picker: (
                picker["full_name"].lower(),
                picker["username"].lower(),
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
) -> list[dict]:
    tabs: list[dict] = []

    if is_upcoming_stage and recommended_riders:
        tabs.append({"id": "next", "label": "Next stage"})
    if show_stage_lineups:
        tabs.append({"id": "lineups", "label": "Lineups"})
    if show_stage_lineups and lineups and rider_picker_view:
        tabs.append({"id": "picked", "label": "Who picked"})
    if classification_panels:
        tabs.append({"id": "classifications", "label": "Jerseys"})
    if projected_final_scores:
        tabs.append({"id": "finals", "label": "Final now"})
    if current_standings:
        tabs.append({"id": "standings", "label": "Standing"})

    return tabs


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
            item["participant"].get("FullName", "").lower(),
            item["participant"].get("Username", "").lower(),
        )
    )
    for index, item in enumerate(projected_final_scores, start=1):
        item["rank"] = index


@app.route("/")
def index():
    market_id = get_market_id()
    requested_subleague_id = request.args.get("subleague_id", type=int) or get_default_subleague_id()
    requested_market_round_id = request.args.get("market_round_id", type=int)
    requested_view = (request.args.get("view", type=str) or "").strip()

    context = {
        "market_id": market_id,
        "subleagues": [],
        "selected_subleague": None,
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
        "current_standings": [],
        "is_live_stage": False,
        "is_upcoming_stage": False,
        "is_next_stage_preview": False,
        "show_stage_lineups": True,
        "error": None,
        "status_label": stage_status_label,
    }

    try:
        client = get_client()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            subleagues_future = executor.submit(client.get_subleagues, market_id)
            rounds_future = executor.submit(client.get_market_rounds, market_id)
            subleagues = subleagues_future.result()
            rounds = rounds_future.result()

        selected_subleague = choose_subleague(subleagues, requested_subleague_id)
        current_round = choose_current_round(rounds)
        next_round = choose_next_round(rounds, current_round)
        stage_button_rounds = build_stage_button_rounds(rounds)
        selected_round = choose_market_round(rounds, requested_market_round_id)
        display_round = choose_points_source_round(rounds, selected_round)
        classification_round = choose_latest_finished_round(rounds)
        is_live_stage = bool(selected_round and int(selected_round.get("StageStatus", -1)) == 1)
        is_upcoming_stage = bool(selected_round and int(selected_round.get("StageStatus", -1)) == 0)
        is_next_stage_preview = bool(
            selected_round
            and next_round
            and int(selected_round.get("MarketRoundId") or 0) == int(next_round.get("MarketRoundId") or 0)
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

        if not selected_subleague:
            raise ScoritoError("No subleague was found for this market.")
        if not selected_round:
            raise ScoritoError("No stage information was found for this market.")

        lineups = []
        rider_picker_view = []
        recommended_riders: list = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
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
            current_standings_future = executor.submit(
                client.build_subleague_standings,
                market_id=market_id,
                subleague_id=int(selected_subleague["Id"]),
                finished_market_round_ids=finished_round_ids,
                finished_round_stage_orders=finished_round_stage_orders,
            )

            if lineups_future is not None:
                lineups = lineups_future.result()
                rider_picker_view = build_rider_picker_view(lineups)
            if recommended_riders_future is not None:
                recommended_riders = recommended_riders_future.result()

            classification_panels = classification_panels_future.result()
            projected_final_scores = projected_final_scores_future.result()
            current_standings = current_standings_future.result()
            merge_current_standings_into_projected_final_scores(
                projected_final_scores,
                current_standings,
            )
            view_tabs = build_view_tabs(
                show_stage_lineups=show_stage_lineups,
                is_upcoming_stage=is_upcoming_stage,
                lineups=lineups,
                rider_picker_view=rider_picker_view,
                recommended_riders=recommended_riders,
                classification_panels=classification_panels,
                projected_final_scores=projected_final_scores,
                current_standings=current_standings,
            )
            active_view = choose_active_view(view_tabs, requested_view)

        context.update(
            {
                "subleagues": subleagues,
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
        context["error"] = "Scorito login failed. Check the configured email and password."
    except ScoritoError as exc:
        context["error"] = str(exc)
    except Exception as exc:  # pragma: no cover - defensive fallback
        context["error"] = f"Unexpected error: {exc}"

    return render_template("index.html", **context)


@app.route("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
