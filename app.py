from __future__ import annotations

import concurrent.futures
import math
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
        "stage_score_matrix": {"stages": [], "rows": []},
        "score_trend_chart": {"stages": [], "series": [], "y_ticks": [], "width": 0, "height": 0},
        "stage_result_snapshots": [],
        "selected_stage_result_market_round_id": None,
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
            raise ScoritoError("Er is geen subleague gevonden voor deze markt.")
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
                rider_picker_view = build_rider_picker_view(lineups)
            if recommended_riders_future is not None:
                recommended_riders = recommended_riders_future.result()

            classification_panels = classification_panels_future.result()
            projected_final_scores = projected_final_scores_future.result()
            stage_score_matrix = stage_score_matrix_future.result()
            score_trend_chart = build_score_trend_chart(stage_score_matrix)
            stage_result_snapshots = build_stage_result_snapshots(stage_score_matrix)
            current_standings = current_standings_future.result()
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
                        if snapshot["market_round_id"] == int(selected_round.get("MarketRoundId") or 0)
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
