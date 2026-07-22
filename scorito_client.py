from __future__ import annotations

import base64
import concurrent.futures
import copy
import hashlib
import html
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class ScoritoError(Exception):
    """Base exception for Scorito-related errors."""


class ScoritoAuthError(ScoritoError):
    """Raised when the login flow fails."""


class ScoritoApiError(ScoritoError):
    """Raised when an API call fails."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class RiderSummary:
    rider_id: int
    name_short: str
    first_name: str
    last_name: str
    initials: str
    team_id: int
    team_name: str
    team_abbreviation: str
    team_image_url: str
    jersey_url: str
    is_captain: bool
    display_points: int = 0
    display_base_points: int = 0
    subleague_pick_count: int = 0
    subleague_pick_percentage: float = 0.0
    price: int = 0


class ScoritoClient:
    config_url = "https://www.scorito.com/config.json"
    redirect_uri = "https://www.scorito.com/signincallback"
    request_timeout_seconds = 30
    token_safety_margin_seconds = 60
    config_required_keys = (
        "cyclingApi",
        "leagueApi",
        "indexQueryApi",
        "rankingApi",
        "identityServer",
    )
    default_config_fallback = {
        "cyclingApi": "https://cycling.scorito.com",
        "leagueApi": "https://league.scorito.com",
        "indexQueryApi": "https://index-query.scorito.com",
        "rankingApi": "https://ranking.scorito.com",
        "identityServer": {
            "authority": "https://idsrv.scorito.com",
            "clientId": "Scorito.Website.Client",
            "redirectUriWeb": "https://www.scorito.com/signincallback",
            "postLogoutRedirectUriWeb": "https://www.scorito.com/signoutcallback",
            "silentRedirectUriWeb": "https://www.scorito.com/silent-renew.html",
            "scopes": [
                "Scorito.Games.Cycling.API.Read",
                "Scorito.Games.Cycling.API.Write",
                "Scorito.Games.Motorsports.API.Read",
                "Scorito.Games.Motorsports.API.Write",
                "Scorito.Games.Football.API.Read",
                "Scorito.Games.Football.API.Write",
                "Scorito.Games.Cycling.API.Read",
                "Scorito.Games.Cycling.API.Write",
                "Scorito.Games.Tennis.API.Read",
                "Scorito.Games.Tennis.API.Write",
                "Scorito.Games.Darts.API.Read",
                "Scorito.Games.Darts.API.Write",
                "Scorito.Platform.API.Read",
                "Scorito.Platform.API.Write",
                "User.API",
                "Scorito.Ranking.API.Read",
                "Scorito.Score.API.Read",
                "Scorito.Score.API.Write",
                "openid",
                "profile",
                "email",
                "roles",
            ],
        },
    }
    stage_result_point_types = {1, 2, 3, 4}
    classification_team_point_types = {101, 102, 103, 104, 201, 202, 203, 204}
    captain_factor_point_types = {1, 3}
    final_classification_rank_points = {
        1: {
            1: 100,
            2: 80,
            3: 60,
            4: 50,
            5: 40,
            6: 36,
            7: 32,
            8: 28,
            9: 24,
            10: 22,
            11: 20,
            12: 18,
            13: 16,
            14: 14,
            15: 12,
            16: 10,
            17: 8,
            18: 6,
            19: 4,
            20: 2,
        },
        2: {
            1: 80,
            2: 60,
            3: 40,
            4: 30,
            5: 20,
            6: 10,
            7: 8,
            8: 6,
            9: 4,
            10: 2,
        },
        3: {
            1: 60,
            2: 40,
            3: 30,
            4: 20,
            5: 10,
        },
        4: {
            1: 60,
            2: 40,
            3: 30,
            4: 20,
            5: 10,
        },
    }
    final_classification_winner_team_points = {
        1: 24,
        2: 18,
        3: 9,
        4: 9,
    }

    def __init__(self, email: str, password: str) -> None:
        self.email = email.strip()
        self.password = password
        self._config = self._load_config()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._current_user_id: int | None = None
        self._token_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._cache: dict[tuple, tuple[float, object]] = {}

    @property
    def current_user_id(self) -> int | None:
        self._ensure_access_token()
        return self._current_user_id

    def get_subleagues(self, market_id: int) -> list[dict]:
        return self._cached_value(
            ("subleagues", market_id),
            ttl_seconds=300,
            loader=lambda: self._api_get(
                f"{self._config['leagueApi']}/subleague/v1.0/data/poollist/{market_id}"
            ),
        )

    def get_market_rounds(self, market_id: int) -> list[dict]:
        return self._cached_value(
            ("market_rounds", market_id),
            ttl_seconds=300,
            loader=lambda: self._api_get(
                f"{self._config['cyclingApi']}/cycling/v2.0/marketroundstage/{market_id}"
            ),
        )

    def get_market_enriched(self, market_id: int) -> dict:
        return self._cached_value(
            ("market_enriched", market_id),
            ttl_seconds=900,
            loader=lambda: self._api_get(
                f"{self._config['cyclingApi']}/cyclingmanager/v1.0/marketenriched/{market_id}"
            ),
        )

    def get_rider_map(self, market_id: int) -> dict[int, dict]:
        return self._cached_value(
            ("rider_map", market_id),
            ttl_seconds=900,
            loader=lambda: {
                int(rider["RiderId"]): rider
                for rider in self._api_get(
                    f"{self._config['cyclingApi']}/cyclingmanager/v1.0/eventriderenriched/{market_id}"
                )
            },
        )

    def get_team_map(self) -> dict[int, dict]:
        return self._cached_value(
            ("team_map",),
            ttl_seconds=3600,
            loader=lambda: {
                int(team["Id"]): team
                for team in self._api_get(
                    f"{self._config['cyclingApi']}/cycling/v2.0/team"
                )
            },
        )

    def get_subleague_participants(self, subleague_id: int) -> list[dict]:
        return self._cached_value(
            ("subleague_participants", subleague_id),
            ttl_seconds=300,
            loader=lambda: [
                item
                for item in self._api_get(
                    f"{self._config['leagueApi']}/subleague/v1.0/participant/pool/{subleague_id}"
                )
                if int(item.get("ParticipantStatus", 0)) == 1
            ],
        )

    def get_subleague_detail(self, subleague_id: int) -> dict:
        return self._cached_value(
            ("subleague_detail", subleague_id),
            ttl_seconds=3600,
            loader=lambda: self._api_get(
                f"{self._config['leagueApi']}/subleague/v1.0/subleague/{subleague_id}"
            ),
        )

    def get_stage_selection(self, market_round_id: int, user_id: int) -> dict:
        return self._cached_value(
            ("stage_selection", market_round_id, user_id),
            ttl_seconds=60,
            loader=lambda: self._api_get(
                f"{self._config['cyclingApi']}/cyclingmanager/v1.0/stageselection/{market_round_id}/{user_id}"
            ),
        )

    def get_team_selection(self, market_id: int, user_id: int) -> list[int]:
        return self._cached_value(
            ("team_selection", market_id, user_id),
            ttl_seconds=120,
            loader=lambda: [
                int(rider_id)
                for rider_id in self._api_get(
                    f"{self._config['cyclingApi']}/cyclingmanager/v1.0/teamselection/{market_id}/{user_id}"
                )
            ],
        )

    def get_market_round_points(self, market_id: int) -> dict[int, dict[int, list[dict]]]:
        return self._cached_value(
            ("market_round_points", market_id),
            ttl_seconds=180,
            loader=lambda: self._load_market_round_points(market_id),
        )

    def get_classifications(self, market_id: int) -> list[dict]:
        return self._cached_value(
            ("classifications", market_id),
            ttl_seconds=300,
            loader=lambda: self._api_get(
                f"{self._config['cyclingApi']}/cycling/v2.0/classification/{market_id}"
            ),
        )

    def get_classification_results(self, market_id: int) -> list[dict]:
        return self._cached_value(
            ("classification_results", market_id),
            ttl_seconds=300,
            loader=lambda: self._api_get(
                f"{self._config['cyclingApi']}/cycling/v2.0/classificationresult/{market_id}"
            ),
        )

    def get_user_market_percentages(self, user_id: int) -> list[dict]:
        return self._cached_value(
            ("user_market_percentages", user_id),
            ttl_seconds=1800,
            loader=lambda: self._api_get(
                f"{self._config['indexQueryApi']}/v1.0/usermarketpercentage/{user_id}"
            ),
        )

    def get_user_market_percentage(self, user_id: int, market_id: int) -> float | None:
        for item in self.get_user_market_percentages(user_id):
            if int(item.get("marketId") or 0) == market_id:
                percentage = item.get("percentage")
                return float(percentage) if percentage is not None else None
        return None

    def get_total_user_score(self, market_id: int, user_id: int) -> int:
        return self._cached_value(
            ("total_user_score", market_id, user_id),
            ttl_seconds=1800,
            loader=lambda: int(
                (
                    self._api_get(
                        self._ranking_api_url_for_user(
                            user_id,
                            f"scoreblock/totaluserscore/{market_id}/{user_id}",
                        )
                    )
                ).get("Points")
                or 0
            ),
        )

    def get_total_max_average_score(self, market_id: int) -> dict:
        return self._cached_value(
            ("total_max_average_score", market_id),
            ttl_seconds=1800,
            loader=lambda: self._api_get(
                f"{self._config['rankingApi']}/ranking/v2.0/scoreblock/totalmaxaveragescores/{market_id}"
            ),
        )

    def build_classification_panels(self, market_id: int, *, max_rows: int = 5) -> list[dict]:
        return self._cached_value(
            ("classification_panels", market_id, max_rows),
            ttl_seconds=180,
            loader=lambda: self._build_classification_panels_uncached(
                market_id=market_id,
                max_rows=max_rows,
            ),
        )

    def _build_classification_panels_uncached(self, market_id: int, *, max_rows: int = 5) -> list[dict]:
        rider_map = self.get_rider_map(market_id)
        team_map = self.get_team_map()
        result_map = {
            int(item.get("Id") or 0): item.get("Results", [])
            for item in self.get_classification_results(market_id)
        }

        panels: list[dict] = []
        for classification in self.get_classifications(market_id):
            classification_id = int(classification.get("Id") or 0)
            classification_type = int(classification.get("Type") or 0)
            meta = self._classification_meta(classification_type)
            results = result_map.get(classification_id, [])
            leader_time_ms = int(results[0].get("Time") or 0) if results else 0
            rows: list[dict] = []

            for result in results[:max_rows]:
                rider_id = int(result.get("RiderId") or 0)
                rider = rider_map.get(rider_id, {})
                team_id = int(rider.get("TeamId") or 0)
                team = team_map.get(team_id, {})
                rows.append(
                    {
                        "rank": int(result.get("Rank") or 0),
                        "rider_id": rider_id,
                        "name_short": rider.get("NameShort") or f"Rider {rider_id}",
                        "initials": self._rider_initials(
                            rider.get("FirstName", ""),
                            rider.get("LastName", ""),
                            rider.get("NameShort", ""),
                        ),
                        "team_name": team.get("Name", ""),
                        "team_abbreviation": team.get("Abbreviation", ""),
                        "team_image_url": team.get("ImageUrl", ""),
                        "jersey_url": self._team_jersey_url(team_id),
                        "metric_value": self._format_classification_metric(
                            result_type=int(classification.get("ResultType") or 0),
                            points=int(result.get("Points") or 0),
                            time_ms=int(result.get("Time") or 0),
                            leader_time_ms=leader_time_ms,
                        ),
                    }
                )

            panels.append(
                {
                    "id": classification_id,
                    "name": meta["name"],
                    "theme": meta["theme"],
                    "jersey_name": meta["jersey_name"],
                    "rows": rows,
                    "leader": rows[0] if rows else None,
                }
            )

        return panels

    def build_archive_standings(
        self,
        *,
        market_id: int,
        subleague_id: int,
    ) -> list[dict]:
        return self._cached_value(
            ("archive_standings", market_id, subleague_id),
            ttl_seconds=1800,
            loader=lambda: self._build_archive_standings_uncached(
                market_id=market_id,
                subleague_id=subleague_id,
            ),
        )

    def _build_archive_standings_uncached(
        self,
        *,
        market_id: int,
        subleague_id: int,
    ) -> list[dict]:
        participants = self.get_subleague_participants(subleague_id)
        if not participants:
            return []

        access_token = self._ensure_access_token()
        worker_count = max(1, min(8, len(participants)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._fetch_archive_standing_for_participant,
                    participant,
                    market_id,
                    access_token,
                ): participant
                for participant in participants
            }

            standings: list[dict] = []
            for future in concurrent.futures.as_completed(futures):
                standings.append(future.result())

        standings.sort(
            key=lambda item: (
                -int(item.get("total_points") or 0),
                -(item.get("market_percentage") or -1),
                item["participant"].get("Username", "").lower(),
                item["participant"].get("FullName", "").lower(),
            )
        )

        last_points: int | None = None
        current_rank = 0
        for position, item in enumerate(standings, start=1):
            total_points = int(item.get("total_points") or 0)
            if total_points != last_points:
                current_rank = position
                last_points = total_points
            item["rank"] = current_rank

        return standings

    def build_lineups(
        self,
        *,
        market_id: int,
        subleague_id: int,
        market_round_id: int,
        points_market_round_id: int | None = None,
        points_mode: str = "all",
        include_bench: bool = True,
    ) -> list[dict]:
        return self._cached_value(
            (
                "lineups",
                market_id,
                subleague_id,
                market_round_id,
                points_market_round_id,
                points_mode,
                include_bench,
            ),
            ttl_seconds=60,
            loader=lambda: self._build_lineups_uncached(
                market_id=market_id,
                subleague_id=subleague_id,
                market_round_id=market_round_id,
                points_market_round_id=points_market_round_id,
                points_mode=points_mode,
                include_bench=include_bench,
            ),
        )

    def _build_lineups_uncached(
        self,
        *,
        market_id: int,
        subleague_id: int,
        market_round_id: int,
        points_market_round_id: int | None = None,
        points_mode: str = "all",
        include_bench: bool = True,
    ) -> list[dict]:
        participants = self.get_subleague_participants(subleague_id)
        rider_map = self.get_rider_map(market_id)
        team_map = self.get_team_map()
        captain_factor = int(self.get_market_enriched(market_id).get("CaptainFactor") or 2)
        points_by_round = self.get_market_round_points(market_id)
        points_by_rider = (
            points_by_round.get(points_market_round_id, {})
            if points_market_round_id is not None
            else {}
        )
        access_token = self._ensure_access_token()

        worker_count = max(1, min(8, len(participants)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._fetch_lineup_for_participant,
                    participant,
                    market_id,
                    market_round_id,
                    rider_map,
                    team_map,
                    points_by_rider,
                    captain_factor,
                    points_mode,
                    include_bench,
                    access_token,
                ): participant
                for participant in participants
            }

            lineups: list[dict] = []
            for future in concurrent.futures.as_completed(futures):
                lineups.append(future.result())

        lineups.sort(
            key=lambda item: (
                item["participant"].get("Username", "").lower(),
                item["participant"].get("FullName", "").lower(),
            )
        )
        self._apply_subleague_pick_stats(lineups)
        return lineups

    def build_recommended_riders(
        self,
        *,
        market_id: int,
        points_market_round_id: int,
        limit: int | None = None,
        points_mode: str = "classification_team",
    ) -> list[RiderSummary]:
        return self._cached_value(
            ("recommended_riders", market_id, points_market_round_id, limit, points_mode),
            ttl_seconds=180,
            loader=lambda: self._build_recommended_riders_uncached(
                market_id=market_id,
                points_market_round_id=points_market_round_id,
                limit=limit,
                points_mode=points_mode,
            ),
        )

    def _build_recommended_riders_uncached(
        self,
        *,
        market_id: int,
        points_market_round_id: int,
        limit: int | None = None,
        points_mode: str = "classification_team",
    ) -> list[RiderSummary]:
        rider_map = self.get_rider_map(market_id)
        team_map = self.get_team_map()
        points_by_rider = self.get_market_round_points(market_id).get(points_market_round_id, {})

        riders: list[RiderSummary] = []
        for rider_id, rider in rider_map.items():
            team_id = int(rider.get("TeamId") or 0)
            riders.append(
                self._to_rider_summary(
                    rider=rider,
                    team=team_map.get(team_id),
                    rider_id=rider_id,
                    captain_id=0,
                    points_collection=points_by_rider.get(rider_id, []),
                    captain_factor=1,
                    points_mode=points_mode,
                )
            )

        riders = [rider for rider in riders if rider.display_base_points > 0]
        riders.sort(
            key=lambda rider: (
                -rider.display_base_points,
                rider.name_short.lower(),
            )
        )
        if limit is None:
            return riders
        return riders[:limit]

    def build_total_rider_scores(
        self,
        *,
        market_id: int,
        limit: int | None = None,
        points_mode: str = "all",
    ) -> list[RiderSummary]:
        return self._cached_value(
            ("total_rider_scores", market_id, limit, points_mode),
            ttl_seconds=1800,
            loader=lambda: self._build_total_rider_scores_uncached(
                market_id=market_id,
                limit=limit,
                points_mode=points_mode,
            ),
        )

    def _build_total_rider_scores_uncached(
        self,
        *,
        market_id: int,
        limit: int | None = None,
        points_mode: str = "all",
    ) -> list[RiderSummary]:
        rider_map = self.get_rider_map(market_id)
        team_map = self.get_team_map()
        totals_by_rider: dict[int, int] = {}

        for points_by_rider in self.get_market_round_points(market_id).values():
            for rider_id, points_collection in points_by_rider.items():
                totals_by_rider[rider_id] = totals_by_rider.get(rider_id, 0) + self._calculate_points(
                    points_collection,
                    include_types=self._display_point_types(points_mode),
                )

        riders: list[RiderSummary] = []
        for rider_id, total_points in totals_by_rider.items():
            if total_points <= 0:
                continue

            rider = rider_map.get(rider_id, {})
            team_id = int(rider.get("TeamId") or 0)
            team = team_map.get(team_id, {})
            riders.append(
                RiderSummary(
                    rider_id=rider_id,
                    name_short=rider.get("NameShort") or f"Rider {rider_id}",
                    first_name=rider.get("FirstName", ""),
                    last_name=rider.get("LastName", ""),
                    initials=self._rider_initials(
                        rider.get("FirstName", ""),
                        rider.get("LastName", ""),
                        rider.get("NameShort", ""),
                    ),
                    team_id=team_id,
                    team_name=team.get("Name", ""),
                    team_abbreviation=team.get("Abbreviation", ""),
                    team_image_url=team.get("ImageUrl", ""),
                    jersey_url=self._team_jersey_url(team_id),
                    is_captain=False,
                    display_points=total_points,
                    display_base_points=total_points,
                    price=int(rider.get("Price") or 0),
                )
            )

        riders.sort(
            key=lambda rider: (
                -rider.display_base_points,
                rider.name_short.lower(),
            )
        )
        if limit is None:
            return riders
        return riders[:limit]

    @staticmethod
    def _apply_subleague_pick_stats(lineups: list[dict]) -> None:
        total_members = len(lineups)
        if total_members == 0:
            return

        pick_counts: dict[int, int] = {}
        for lineup in lineups:
            rider_ids = {rider.rider_id for rider in lineup["selected_riders"]}
            for rider_id in rider_ids:
                pick_counts[rider_id] = pick_counts.get(rider_id, 0) + 1

        for lineup in lineups:
            for rider in lineup["selected_riders"]:
                rider.subleague_pick_count = pick_counts.get(rider.rider_id, 0)
                rider.subleague_pick_percentage = (
                    rider.subleague_pick_count / total_members
                ) * 100

    def _fetch_lineup_for_participant(
        self,
        participant: dict,
        market_id: int,
        market_round_id: int,
        rider_map: dict[int, dict],
        team_map: dict[int, dict],
        points_by_rider: dict[int, list[dict]],
        captain_factor: int,
        points_mode: str,
        include_bench: bool,
        access_token: str,
    ) -> dict:
        user_id = int(participant["UserId"])
        self._ensure_access_token_from_cached(access_token)
        stage_selection = self.get_stage_selection(market_round_id, user_id)
        team_selection = self.get_team_selection(market_id, user_id)

        captain_id = int(stage_selection.get("CaptainId") or 0)
        team_selection_ids = [int(rider_id) for rider_id in team_selection]
        selected_rider_ids = [int(rider_id) for rider_id in stage_selection.get("RiderIds", [])]
        selected_rider_id_set = set(selected_rider_ids)
        summary_rider_ids = list(dict.fromkeys(team_selection_ids + selected_rider_ids))
        rider_summaries = {
            rider_id: self._to_rider_summary(
                rider=rider_map.get(rider_id),
                team=team_map.get(int((rider_map.get(rider_id) or {}).get("TeamId") or 0)),
                rider_id=rider_id,
                captain_id=captain_id,
                points_collection=points_by_rider.get(rider_id, []),
                captain_factor=captain_factor,
                points_mode=points_mode,
            )
            for rider_id in summary_rider_ids
        }

        selected_riders = [rider_summaries[rider_id] for rider_id in selected_rider_ids if rider_id in rider_summaries]
        bench_riders = [
            rider_summaries[rider_id]
            for rider_id in team_selection_ids
            if rider_id in rider_summaries and rider_id not in selected_rider_id_set
        ]
        bench_riders.sort(key=lambda rider: (-rider.display_base_points, rider.name_short.lower()))

        display_total_points = sum(rider.display_points for rider in selected_riders)
        bench_points_total = 0
        if include_bench:
            selected_base_total = sum(rider.display_base_points for rider in selected_riders)
            best_nine_points_total = sum(
                sorted(
                    (
                        rider_summaries[rider_id].display_base_points
                        for rider_id in team_selection_ids
                        if rider_id in rider_summaries
                    ),
                    reverse=True,
                )[:9]
            )
            bench_points_total = max(0, best_nine_points_total - selected_base_total)

        return {
            "participant": participant,
            "captain_id": captain_id,
            "selected_riders": selected_riders,
            "display_total_points": display_total_points,
            "bench_points_total": bench_points_total,
            "bench_riders": bench_riders,
            "has_lineup": bool(selected_riders),
            "is_current_user": user_id == self._current_user_id,
        }

    def build_projected_final_classification_scores(
        self,
        *,
        market_id: int,
        subleague_id: int,
    ) -> list[dict]:
        return self._cached_value(
            ("projected_final_classification_scores", market_id, subleague_id),
            ttl_seconds=180,
            loader=lambda: self._build_projected_final_classification_scores_uncached(
                market_id=market_id,
                subleague_id=subleague_id,
            ),
        )

    def get_projected_final_scoring_snapshot(self, market_id: int) -> dict:
        return self._cached_value(
            ("projected_final_scoring_snapshot", market_id),
            ttl_seconds=1800,
            loader=lambda: self._get_projected_final_scoring_snapshot_uncached(
                market_id=market_id,
            ),
        )

    def _get_projected_final_scoring_snapshot_uncached(self, *, market_id: int) -> dict:
        rider_map = self.get_rider_map(market_id)
        rider_team_ids = {
            rider_id: int((rider or {}).get("TeamId") or 0)
            for rider_id, rider in rider_map.items()
        }
        (
            rider_final_points,
            rider_final_breakdowns,
            teammate_bonus_rules,
        ) = self._build_projected_final_scoring_snapshot(
            market_id=market_id,
            rider_team_ids=rider_team_ids,
        )
        return {
            "rider_team_ids": rider_team_ids,
            "rider_final_points": rider_final_points,
            "rider_final_breakdowns": rider_final_breakdowns,
            "teammate_bonus_rules": teammate_bonus_rules,
        }

    def _build_projected_final_classification_scores_uncached(
        self,
        *,
        market_id: int,
        subleague_id: int,
    ) -> list[dict]:
        participants = self.get_subleague_participants(subleague_id)
        if not participants:
            return []

        rider_map = self.get_rider_map(market_id)
        rider_team_ids = {
            rider_id: int((rider or {}).get("TeamId") or 0)
            for rider_id, rider in rider_map.items()
        }
        (
            rider_final_points,
            rider_final_breakdowns,
            teammate_bonus_rules,
        ) = self._build_projected_final_scoring_snapshot(
            market_id=market_id,
            rider_team_ids=rider_team_ids,
        )
        access_token = self._ensure_access_token()

        worker_count = max(1, min(8, len(participants)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._fetch_projected_final_classification_for_participant,
                    participant,
                    market_id,
                    rider_map,
                    rider_team_ids,
                    rider_final_points,
                    rider_final_breakdowns,
                    teammate_bonus_rules,
                    access_token,
                ): participant
                for participant in participants
            }

            scores: list[dict] = []
            for future in concurrent.futures.as_completed(futures):
                scores.append(future.result())

        scores.sort(
            key=lambda item: (
                -item["total_projected_final_points"],
                -item["individual_final_points"],
                -item["teammate_winner_points"],
                item["participant"].get("Username", "").lower(),
                item["participant"].get("FullName", "").lower(),
            )
        )
        for index, item in enumerate(scores, start=1):
            item["rank"] = index
        return scores

    def _build_projected_final_scoring_snapshot(
        self,
        *,
        market_id: int,
        rider_team_ids: dict[int, int],
    ) -> tuple[dict[int, int], dict[int, list[dict]], list[dict]]:
        classifications_by_id = {
            int(item.get("Id") or 0): item for item in self.get_classifications(market_id)
        }
        rider_map = self.get_rider_map(market_id)
        rider_final_points: dict[int, int] = {}
        rider_final_breakdowns: dict[int, list[dict]] = {}
        teammate_bonus_rules: list[dict] = []

        for classification_result in self.get_classification_results(market_id):
            classification_id = int(classification_result.get("Id") or 0)
            classification = classifications_by_id.get(classification_id, {})
            classification_type = int(classification.get("Type") or 0)
            rank_points = self.final_classification_rank_points.get(classification_type)
            if not rank_points:
                continue
            classification_name = self._classification_meta(classification_type)["name"]

            ordered_results = sorted(
                classification_result.get("Results", []),
                key=lambda item: int(item.get("Rank") or 9999),
            )

            for result in ordered_results:
                rider_id = int(result.get("RiderId") or 0)
                rank = int(result.get("Rank") or 0)
                points = rank_points.get(rank, 0)
                if rider_id > 0 and points > 0:
                    rider_final_points[rider_id] = rider_final_points.get(rider_id, 0) + points
                    rider_final_breakdowns.setdefault(rider_id, []).append(
                        {
                            "classification_name": classification_name,
                            "rank": rank,
                            "points": points,
                        }
                    )

            winner = next(
                (
                    result
                    for result in ordered_results
                    if int(result.get("Rank") or 0) == 1
                ),
                None,
            )
            if not winner:
                continue

            winner_rider_id = int(winner.get("RiderId") or 0)
            winner_team_id = rider_team_ids.get(winner_rider_id, 0)
            winner_team_points = self.final_classification_winner_team_points.get(
                classification_type,
                0,
            )
            if winner_rider_id > 0 and winner_team_id > 0 and winner_team_points > 0:
                teammate_bonus_rules.append(
                    {
                        "winner_rider_id": winner_rider_id,
                        "winner_team_id": winner_team_id,
                        "winner_name": self._rider_name_short(
                            rider_map.get(winner_rider_id),
                            winner_rider_id,
                        ),
                        "classification_name": classification_name,
                        "points": winner_team_points,
                    }
                )

        return rider_final_points, rider_final_breakdowns, teammate_bonus_rules

    def _fetch_projected_final_classification_for_participant(
        self,
        participant: dict,
        market_id: int,
        rider_map: dict[int, dict],
        rider_team_ids: dict[int, int],
        rider_final_points: dict[int, int],
        rider_final_breakdowns: dict[int, list[dict]],
        teammate_bonus_rules: list[dict],
        access_token: str,
    ) -> dict:
        user_id = int(participant["UserId"])
        self._ensure_access_token_from_cached(access_token)
        team_selection_ids = list(dict.fromkeys(self.get_team_selection(market_id, user_id)))

        individual_breakdown_entries: list[tuple[int, str]] = []
        individual_final_points = 0
        for rider_id in team_selection_ids:
            rider_points = rider_final_points.get(rider_id, 0)
            if rider_points <= 0:
                continue
            rider_name = self._rider_name_short(rider_map.get(rider_id), rider_id)
            parts = rider_final_breakdowns.get(rider_id, [])
            details = ", ".join(
                f"{part['classification_name']} #{part['rank']} ({part['points']})"
                for part in parts
            )
            individual_breakdown_entries.append(
                (rider_points, f"{rider_name}: {rider_points} pts ({details})")
            )
            individual_final_points += rider_points

        teammate_winner_points = 0
        teammate_breakdown_entries: list[tuple[int, str]] = []
        for rider_id in team_selection_ids:
            rider_team_id = rider_team_ids.get(rider_id, 0)
            if rider_team_id <= 0:
                continue

            matching_rules = [
                rule
                for rule in teammate_bonus_rules
                if rider_team_id == rule["winner_team_id"]
                and rider_id != rule["winner_rider_id"]
            ]
            rider_bonus = sum(rule["points"] for rule in matching_rules)
            if rider_bonus <= 0:
                continue

            rider_name = self._rider_name_short(rider_map.get(rider_id), rider_id)
            details = ", ".join(
                f"{rule['classification_name']} winnaar {rule['winner_name']} ({rule['points']})"
                for rule in matching_rules
            )
            teammate_breakdown_entries.append(
                (rider_bonus, f"{rider_name}: {rider_bonus} pts ({details})")
            )
            teammate_winner_points += rider_bonus

        individual_breakdown_entries.sort(key=lambda item: (-item[0], item[1].lower()))
        teammate_breakdown_entries.sort(key=lambda item: (-item[0], item[1].lower()))

        return {
            "participant": participant,
            "individual_final_points": individual_final_points,
            "individual_final_points_tooltip": self._tooltip_lines(
                [entry[1] for entry in individual_breakdown_entries],
                empty_message="Er zijn momenteel geen renners die eindklassementpunten scoren.",
            ),
            "teammate_winner_points": teammate_winner_points,
            "teammate_winner_points_tooltip": self._tooltip_lines(
                [entry[1] for entry in teammate_breakdown_entries],
                empty_message="Er zijn momenteel geen ploeggenoten die winnaarbonussen scoren.",
            ),
            "total_projected_final_points": (
                individual_final_points + teammate_winner_points
            ),
            "is_current_user": user_id == self._current_user_id,
        }

    def build_stage_score_matrix(
        self,
        *,
        market_id: int,
        subleague_id: int,
        finished_market_round_ids: list[int],
        finished_round_stage_orders: dict[int, int],
    ) -> dict:
        cache_key = (
            "stage_score_matrix",
            market_id,
            subleague_id,
            tuple(finished_market_round_ids),
            tuple(sorted(finished_round_stage_orders.items())),
        )
        return self._cached_value(
            cache_key,
            ttl_seconds=180,
            loader=lambda: self._build_stage_score_matrix_uncached(
                market_id=market_id,
                subleague_id=subleague_id,
                finished_market_round_ids=finished_market_round_ids,
                finished_round_stage_orders=finished_round_stage_orders,
            ),
        )

    def _build_stage_score_matrix_uncached(
        self,
        *,
        market_id: int,
        subleague_id: int,
        finished_market_round_ids: list[int],
        finished_round_stage_orders: dict[int, int],
    ) -> dict:
        participants = self.get_subleague_participants(subleague_id)
        if not participants or not finished_market_round_ids:
            return {"stages": [], "rows": []}

        points_by_round = self.get_market_round_points(market_id)
        captain_factor = int(self.get_market_enriched(market_id).get("CaptainFactor") or 2)
        access_token = self._ensure_access_token()

        worker_count = max(1, min(8, len(participants)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._fetch_stage_score_matrix_row,
                    participant,
                    finished_market_round_ids,
                    points_by_round,
                    captain_factor,
                    access_token,
                ): participant
                for participant in participants
            }

            rows: list[dict] = []
            for future in concurrent.futures.as_completed(futures):
                rows.append(future.result())

        rows.sort(
            key=lambda item: (
                -item["total_points"],
                item["participant"].get("Username", "").lower(),
                item["participant"].get("FullName", "").lower(),
            )
        )
        for index, item in enumerate(rows, start=1):
            item["rank"] = index

        winner_scores = {
            market_round_id: max(
                (row["stage_points_by_round"].get(market_round_id, 0) for row in rows),
                default=0,
            )
            for market_round_id in finished_market_round_ids
        }
        ordered_stage_ids = sorted(
            finished_market_round_ids,
            key=lambda market_round_id: finished_round_stage_orders.get(
                market_round_id,
                market_round_id,
            ),
        )

        stage_columns = [
            {
                "market_round_id": market_round_id,
                "stage_order": finished_round_stage_orders.get(market_round_id, market_round_id),
                "winner_score": winner_scores.get(market_round_id, 0),
            }
            for market_round_id in ordered_stage_ids
        ]

        leader_scores = {}
        for row in rows:
            cumulative_points = 0
            cumulative_points_by_round: dict[int, int] = {}
            for market_round_id in ordered_stage_ids:
                cumulative_points += row["stage_points_by_round"].get(market_round_id, 0)
                cumulative_points_by_round[market_round_id] = cumulative_points
            row["cumulative_points_by_round"] = cumulative_points_by_round

        for market_round_id in ordered_stage_ids:
            leader_scores[market_round_id] = max(
                (row["cumulative_points_by_round"].get(market_round_id, 0) for row in rows),
                default=0,
            )

        for row in rows:
            row["stage_points"] = [
                {
                    "market_round_id": column["market_round_id"],
                    "stage_order": column["stage_order"],
                    "points": row["stage_points_by_round"].get(column["market_round_id"], 0),
                    "is_stage_winner": (
                        row["stage_points_by_round"].get(column["market_round_id"], 0)
                        == column["winner_score"]
                        and column["winner_score"] > 0
                    ),
                    "is_subleague_leader": (
                        row["cumulative_points_by_round"].get(column["market_round_id"], 0)
                        == leader_scores.get(column["market_round_id"], 0)
                    ),
                }
                for column in stage_columns
            ]
            row["stage_win_count"] = sum(
                1 for stage_point in row["stage_points"] if stage_point["is_stage_winner"]
            )
            row["leader_count"] = sum(
                1 for stage_point in row["stage_points"] if stage_point["is_subleague_leader"]
            )

        return {"stages": stage_columns, "rows": rows}

    def _fetch_stage_score_matrix_row(
        self,
        participant: dict,
        finished_market_round_ids: list[int],
        points_by_round: dict[int, dict[int, list[dict]]],
        captain_factor: int,
        access_token: str,
    ) -> dict:
        user_id = int(participant["UserId"])
        self._ensure_access_token_from_cached(access_token)

        stage_points_by_round: dict[int, int] = {}
        total_points = 0

        for market_round_id in finished_market_round_ids:
            stage_selection = self.get_stage_selection(market_round_id, user_id)
            captain_id = int(stage_selection.get("CaptainId") or 0)
            selected_rider_ids = [int(rider_id) for rider_id in stage_selection.get("RiderIds", [])]
            points_for_round = points_by_round.get(market_round_id, {})
            stage_points = sum(
                self._calculate_points(
                    points_for_round.get(rider_id, []),
                    factor=captain_factor if rider_id == captain_id else 1,
                    factor_types=self.captain_factor_point_types,
                )
                for rider_id in selected_rider_ids
            )
            stage_points_by_round[market_round_id] = stage_points
            total_points += stage_points

        return {
            "participant": participant,
            "stage_points_by_round": stage_points_by_round,
            "total_points": total_points,
            "is_current_user": user_id == self._current_user_id,
        }

    def build_subleague_standings(
        self,
        *,
        market_id: int,
        subleague_id: int,
        finished_market_round_ids: list[int],
        finished_round_stage_orders: dict[int, int],
    ) -> list[dict]:
        cache_key = (
            "subleague_standings",
            market_id,
            subleague_id,
            tuple(finished_market_round_ids),
            tuple(sorted(finished_round_stage_orders.items())),
        )
        cached = self._cached_value(
            cache_key,
            ttl_seconds=180,
            loader=lambda: self._build_subleague_standings_uncached(
                market_id=market_id,
                subleague_id=subleague_id,
                finished_market_round_ids=finished_market_round_ids,
                finished_round_stage_orders=finished_round_stage_orders,
            ),
        )
        return cached

    def _build_subleague_standings_uncached(
        self,
        *,
        market_id: int,
        subleague_id: int,
        finished_market_round_ids: list[int],
        finished_round_stage_orders: dict[int, int],
    ) -> list[dict]:
        participants = self.get_subleague_participants(subleague_id)
        if not participants or not finished_market_round_ids:
            return []

        points_by_round = self.get_market_round_points(market_id)
        rider_map = self.get_rider_map(market_id)
        captain_factor = int(self.get_market_enriched(market_id).get("CaptainFactor") or 2)
        access_token = self._ensure_access_token()

        worker_count = max(1, min(8, len(participants)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._fetch_subleague_standing_for_participant,
                    participant,
                    market_id,
                    finished_market_round_ids,
                    finished_round_stage_orders,
                    rider_map,
                    points_by_round,
                    captain_factor,
                    access_token,
                ): participant
                for participant in participants
            }

            standings: list[dict] = []
            for future in concurrent.futures.as_completed(futures):
                standings.append(future.result())

        standings.sort(
            key=lambda item: (
                -item["total_points"],
                item["participant"].get("Username", "").lower(),
                item["participant"].get("FullName", "").lower(),
            )
        )
        for index, item in enumerate(standings, start=1):
            item["rank"] = index

        return standings

    def _load_market_round_points(self, market_id: int) -> dict[int, dict[int, list[dict]]]:
        payload = self._api_get(
            f"{self._config['cyclingApi']}/cyclingmanager/v1.0/points/totalpoints/{market_id}"
        )
        points_by_round: dict[int, dict[int, list[dict]]] = {}
        for item in payload:
            round_id = int(item.get("MarketRoundId") or 0)
            rider_points: dict[int, list[dict]] = {}
            collection = (
                item.get("RiderPointsCollection", {}).get("RiderPointsCollection", [])
            )
            for rider_entry in collection:
                rider_id = int(rider_entry.get("RiderId") or 0)
                rider_points[rider_id] = rider_entry.get("PointsCollection", [])
            if round_id > 0:
                points_by_round[round_id] = rider_points
        return points_by_round

    def _cached_value(
        self,
        key: tuple,
        *,
        ttl_seconds: int,
        loader,
    ):
        now = time.time()
        with self._cache_lock:
            cached_entry = self._cache.get(key)
        if cached_entry and cached_entry[0] > now:
            return copy.deepcopy(cached_entry[1])

        value = loader()
        expires_at = time.time() + ttl_seconds
        with self._cache_lock:
            self._cache[key] = (expires_at, copy.deepcopy(value))
        return value

    def _ensure_access_token_from_cached(self, access_token: str) -> str:
        now = time.time()
        with self._token_lock:
            if (
                self._access_token == access_token
                and self._access_token
                and now < self._access_token_expires_at
            ):
                return self._access_token
        return self._ensure_access_token()

    def _fetch_archive_standing_for_participant(
        self,
        participant: dict,
        market_id: int,
        access_token: str,
    ) -> dict:
        user_id = int(participant["UserId"])
        self._ensure_access_token_from_cached(access_token)
        return {
            "participant": participant,
            "total_points": self.get_total_user_score(market_id, user_id),
            "market_percentage": self.get_user_market_percentage(user_id, market_id),
            "is_current_user": user_id == self._current_user_id,
        }

    def _fetch_subleague_standing_for_participant(
        self,
        participant: dict,
        market_id: int,
        finished_market_round_ids: list[int],
        finished_round_stage_orders: dict[int, int],
        rider_map: dict[int, dict],
        points_by_round: dict[int, dict[int, list[dict]]],
        captain_factor: int,
        access_token: str,
    ) -> dict:
        user_id = int(participant["UserId"])
        self._ensure_access_token_from_cached(access_token)
        team_selection_ids = self.get_team_selection(market_id, user_id)

        total_points = 0
        total_bench_points = 0
        total_captain_missed_points = 0
        bench_breakdown_lines: list[str] = []
        captain_breakdown_lines: list[str] = []

        for market_round_id in finished_market_round_ids:
            stage_selection = self.get_stage_selection(market_round_id, user_id)
            captain_id = int(stage_selection.get("CaptainId") or 0)
            selected_rider_ids = [int(rider_id) for rider_id in stage_selection.get("RiderIds", [])]
            points_for_round = points_by_round.get(market_round_id, {})
            stage_order = finished_round_stage_orders.get(market_round_id, market_round_id)
            stage_points_by_rider = {
                rider_id: self._calculate_points(points_for_round.get(rider_id, []))
                for rider_id in team_selection_ids
            }

            total_points += sum(
                self._calculate_points(
                    points_for_round.get(rider_id, []),
                    factor=captain_factor if rider_id == captain_id else 1,
                    factor_types=self.captain_factor_point_types,
                )
                for rider_id in selected_rider_ids
            )

            selected_captain_eligible_points = [
                self._calculate_points(
                    points_for_round.get(rider_id, []),
                    include_types=self.captain_factor_point_types,
                )
                for rider_id in selected_rider_ids
            ]
            chosen_captain_base_points = self._calculate_points(
                points_for_round.get(captain_id, []),
                include_types=self.captain_factor_point_types,
            )
            ideal_captain_base_points = max(selected_captain_eligible_points, default=0)
            captain_bonus_factor = max(0, captain_factor - 1)
            captain_missed_points = max(
                0,
                (ideal_captain_base_points - chosen_captain_base_points) * captain_bonus_factor,
            )
            total_captain_missed_points += captain_missed_points
            if captain_missed_points > 0 and selected_rider_ids:
                chosen_captain_name = self._rider_name_short(rider_map.get(captain_id), captain_id)
                ideal_captain_id = max(
                    selected_rider_ids,
                    key=lambda rider_id: (
                        self._calculate_points(
                            points_for_round.get(rider_id, []),
                            include_types=self.captain_factor_point_types,
                        ),
                        self._rider_name_short(rider_map.get(rider_id), rider_id).lower(),
                    ),
                )
                ideal_captain_name = self._rider_name_short(
                    rider_map.get(ideal_captain_id),
                    ideal_captain_id,
                )
                captain_breakdown_lines.append(
                    f"Etappe {stage_order}: {chosen_captain_name} ({chosen_captain_base_points}) -> "
                    f"{ideal_captain_name} ({ideal_captain_base_points}) [+{captain_missed_points}]"
                )

            selected_base_total = sum(
                stage_points_by_rider.get(rider_id, 0) for rider_id in selected_rider_ids
            )
            best_nine_ids = sorted(
                team_selection_ids,
                key=lambda rider_id: (
                    -stage_points_by_rider.get(rider_id, 0),
                    self._rider_name_short(rider_map.get(rider_id), rider_id).lower(),
                ),
            )[:9]
            best_nine_total = sum(
                stage_points_by_rider.get(rider_id, 0)
                for rider_id in best_nine_ids
            )
            bench_points = max(0, best_nine_total - selected_base_total)
            total_bench_points += bench_points
            if bench_points > 0:
                selected_rider_id_set = set(selected_rider_ids)
                best_nine_id_set = set(best_nine_ids)
                incoming_ids = [
                    rider_id for rider_id in best_nine_ids if rider_id not in selected_rider_id_set
                ]
                outgoing_ids = sorted(
                    [
                        rider_id
                        for rider_id in selected_rider_ids
                        if rider_id not in best_nine_id_set
                    ],
                    key=lambda rider_id: (
                        stage_points_by_rider.get(rider_id, 0),
                        self._rider_name_short(rider_map.get(rider_id), rider_id).lower(),
                    ),
                )
                swap_parts: list[str] = []
                for outgoing_id, incoming_id in zip(outgoing_ids, incoming_ids):
                    outgoing_name = self._rider_name_short(rider_map.get(outgoing_id), outgoing_id)
                    incoming_name = self._rider_name_short(rider_map.get(incoming_id), incoming_id)
                    outgoing_points = stage_points_by_rider.get(outgoing_id, 0)
                    incoming_points = stage_points_by_rider.get(incoming_id, 0)
                    swap_parts.append(
                        f"{outgoing_name} ({outgoing_points}) -> {incoming_name} ({incoming_points}) "
                        f"[+{incoming_points - outgoing_points}]"
                    )
                bench_breakdown_lines.append(
                    f"Etappe {stage_order}: " + "; ".join(swap_parts) + f" [+{bench_points}]"
                )

        return {
            "participant": participant,
            "total_points": total_points,
            "total_bench_points": total_bench_points,
            "total_bench_points_tooltip": self._tooltip_lines(
                bench_breakdown_lines,
                empty_message="Er zijn geen bankpunten misgelopen.",
            ),
            "total_captain_missed_points": total_captain_missed_points,
            "total_captain_missed_points_tooltip": self._tooltip_lines(
                captain_breakdown_lines,
                empty_message="Er zijn geen captainpunten misgelopen.",
            ),
            "total_with_bench_and_captain": (
                total_points + total_bench_points + total_captain_missed_points
            ),
            "is_current_user": user_id == self._current_user_id,
        }

    def _to_rider_summary(
        self,
        *,
        rider: dict | None,
        team: dict | None,
        rider_id: int,
        captain_id: int,
        points_collection: list[dict],
        captain_factor: int,
        points_mode: str,
    ) -> RiderSummary:
        rider = rider or {}
        team = team or {}
        team_id = int(rider.get("TeamId") or 0)
        base_points = self._calculate_points(
            points_collection,
            include_types=self._display_point_types(points_mode),
        )
        rider_points = self._calculate_points(
            points_collection,
            include_types=self._display_point_types(points_mode),
            factor=captain_factor if rider_id == captain_id else 1,
            factor_types=(
                self.captain_factor_point_types
                if points_mode == "all"
                else set()
            ),
        )
        return RiderSummary(
            rider_id=rider_id,
            name_short=rider.get("NameShort") or f"Rider {rider_id}",
            first_name=rider.get("FirstName", ""),
            last_name=rider.get("LastName", ""),
            initials=self._rider_initials(
                rider.get("FirstName", ""),
                rider.get("LastName", ""),
                rider.get("NameShort", ""),
            ),
            team_id=team_id,
            team_name=team.get("Name", ""),
            team_abbreviation=team.get("Abbreviation", ""),
            team_image_url=team.get("ImageUrl", ""),
            jersey_url=self._team_jersey_url(team_id),
            is_captain=rider_id == captain_id,
            display_points=rider_points,
            display_base_points=base_points,
            price=int(rider.get("Price") or 0),
        )

    @classmethod
    def _calculate_points(
        cls,
        points_collection: list[dict],
        *,
        include_types: set[int] | None = None,
        factor: int = 1,
        factor_types: set[int] | None = None,
    ) -> int:
        total = 0
        for entry in points_collection:
            points_type = int(entry.get("PointsType") or 0)
            if include_types is not None and points_type not in include_types:
                continue
            points = int(entry.get("Points") or 0)
            if factor_types and points_type in factor_types:
                total += factor * points
            else:
                total += points
        return total

    @classmethod
    def _display_point_types(cls, points_mode: str) -> set[int] | None:
        if points_mode == "classification_team":
            return cls.classification_team_point_types
        return None

    @staticmethod
    def _rider_name_short(rider: dict | None, rider_id: int) -> str:
        rider = rider or {}
        return rider.get("NameShort") or f"Rider {rider_id}"

    def _ranking_api_url_for_user(self, user_id: int, path: str) -> str:
        shard = f"{str(user_id)[-1]}/" if user_id > 0 else ""
        normalized_path = path.strip("/")
        return (
            f"{self._config['rankingApi'].rstrip('/')}/"
            f"{shard}ranking/v2.0/{normalized_path}"
        )

    @staticmethod
    def _tooltip_lines(lines: list[str], *, empty_message: str) -> list[str]:
        return lines if lines else [empty_message]

    @staticmethod
    def _rider_initials(first_name: str, last_name: str, name_short: str) -> str:
        initials = "".join(
            part[:1].upper()
            for part in (first_name.strip(), last_name.strip())
            if part
        )
        if initials:
            return initials[:2]

        cleaned_short_name = re.sub(r"[^A-Za-z]", "", name_short or "")
        return (cleaned_short_name[:2] or "RD").upper()

    def _team_jersey_url(self, team_id: int) -> str:
        if team_id <= 0:
            return ""
        sports_cdn_url = self._config.get("sportsCdnUrl", "").rstrip("/")
        if not sports_cdn_url:
            return ""
        return f"{sports_cdn_url}/cycling/team/jerseys/Jersey_{team_id}.png"

    @staticmethod
    def _classification_meta(classification_type: int) -> dict[str, str]:
        return {
            1: {"name": "Algemeen", "jersey_name": "Gele trui", "theme": "general"},
            2: {"name": "Punten", "jersey_name": "Groene trui", "theme": "points"},
            3: {"name": "Berg", "jersey_name": "Bolletjestrui", "theme": "mountain"},
            4: {"name": "Jongeren", "jersey_name": "Witte trui", "theme": "youth"},
        }.get(
            classification_type,
            {"name": "Klassement", "jersey_name": "Stand", "theme": "default"},
        )

    @classmethod
    def _format_classification_metric(
        cls,
        *,
        result_type: int,
        points: int,
        time_ms: int,
        leader_time_ms: int,
    ) -> str:
        if result_type == 2:
            return f"{points} pts"

        if leader_time_ms <= 0 or time_ms <= 0:
            return cls._format_duration(time_ms)
        if time_ms == leader_time_ms:
            return cls._format_duration(time_ms)
        return f"+{cls._format_duration(time_ms - leader_time_ms)}"

    @staticmethod
    def _format_duration(milliseconds: int) -> str:
        total_seconds = max(0, int(round(milliseconds / 1000)))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def _ensure_access_token(self) -> str:
        with self._token_lock:
            now = time.time()
            if self._access_token and now < self._access_token_expires_at:
                return self._access_token

            token_payload = self._login()
            self._access_token = token_payload["access_token"]
            expires_in = int(token_payload.get("expires_in", 300))
            self._access_token_expires_at = (
                time.time() + expires_in - self.token_safety_margin_seconds
            )

            id_token = token_payload.get("id_token")
            self._current_user_id = self._extract_user_id(id_token)

            return self._access_token

    def _login(self) -> dict:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        verifier, challenge = self._pkce_pair()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)

        identity = self._config["identityServer"]
        authorize_query = urllib.parse.urlencode(
            {
                "client_id": identity["clientId"],
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(identity["scopes"]),
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        authorize_url = f"{identity['authority'].rstrip('/')}/connect/authorize?{authorize_query}"

        login_response_html, login_url = self._open_text(
            self._request(
                authorize_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Referer": "https://www.scorito.com/",
                },
            ),
            opener=opener,
        )

        return_url = self._extract_input_value(login_response_html, "ReturnUrl")
        request_verification_token = self._extract_input_value(
            login_response_html,
            "__RequestVerificationToken",
        )
        if not return_url or not request_verification_token:
            raise ScoritoAuthError("Het Scorito-inlogformulier kon niet worden verwerkt.")

        post_body = urllib.parse.urlencode(
            {
                "ReturnUrl": html.unescape(return_url),
                "Username": self.email,
                "Password": self.password,
                "__RequestVerificationToken": request_verification_token,
                "button": "login",
            }
        ).encode("utf-8")

        _, final_url = self._open_text(
            self._request(
                login_url,
                data=post_body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://idsrv.scorito.com",
                    "Referer": login_url,
                },
            ),
            opener=opener,
        )

        parsed_final_url = urllib.parse.urlparse(final_url)
        query_values = urllib.parse.parse_qs(parsed_final_url.query)
        code = query_values.get("code", [None])[0]
        returned_state = query_values.get("state", [None])[0]
        if not code or returned_state != state:
            raise ScoritoAuthError(
                "Inloggen bij Scorito is mislukt. Controleer het ingestelde e-mailadres en wachtwoord."
            )

        token_body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": identity["clientId"],
                "redirect_uri": self.redirect_uri,
                "code": code,
                "code_verifier": verifier,
            }
        ).encode("utf-8")

        token_response = self._open_json(
            self._request(
                f"{identity['authority'].rstrip('/')}/connect/token",
                data=token_body,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://www.scorito.com",
                    "Referer": "https://www.scorito.com/",
                },
            ),
            opener=opener,
        )
        if "access_token" not in token_response:
            raise ScoritoAuthError("Scorito gaf geen toegangstoken terug.")

        return token_response

    def _api_get(self, url: str) -> list | dict:
        access_token = self._ensure_access_token()
        return self._authorized_get(url, access_token)

    def _authorized_get(self, url: str, access_token: str) -> list | dict:
        try:
            payload = self._open_json(
                self._request(
                    url,
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Authorization": f"Bearer {access_token}",
                        "Origin": "https://www.scorito.com",
                        "Referer": "https://www.scorito.com/",
                    },
                )
            )
        except ScoritoApiError as exc:
            if exc.status_code == 401:
                with self._token_lock:
                    self._access_token = None
                    self._access_token_expires_at = 0
                fresh_token = self._ensure_access_token()
                payload = self._open_json(
                    self._request(
                        url,
                        headers={
                            "Accept": "application/json, text/plain, */*",
                            "Authorization": f"Bearer {fresh_token}",
                            "Origin": "https://www.scorito.com",
                            "Referer": "https://www.scorito.com/",
                        },
                    )
                )
            else:
                raise

        if isinstance(payload, dict) and "ResultCode" in payload:
            if int(payload.get("ResultCode") or 0) != 0:
                raise ScoritoApiError(
                    payload.get("ErrorMessage") or "Scorito gaf een onbekende fout terug."
                )
            return payload.get("Content", [])

        return payload

    def _load_config(self) -> dict:
        config_request = self._request(
            self.config_url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.scorito.com/",
            },
        )
        try:
            config = self._open_json(config_request)
        except ScoritoApiError as exc:
            if exc.status_code in {401, 403, 404} or exc.status_code is None:
                config = copy.deepcopy(self.default_config_fallback)
            else:
                raise

        fallback_config = copy.deepcopy(self.default_config_fallback)
        if not isinstance(config.get("identityServer"), dict):
            config["identityServer"] = fallback_config["identityServer"]
        else:
            for key, value in fallback_config["identityServer"].items():
                config["identityServer"].setdefault(key, copy.deepcopy(value))

        for key, value in fallback_config.items():
            if key == "identityServer":
                continue
            config.setdefault(key, value)

        missing_keys = [key for key in self.config_required_keys if key not in config]
        if missing_keys:
            raise ScoritoApiError(
                f"In de Scorito-config ontbreken verplichte sleutels: {', '.join(missing_keys)}"
            )
        return config

    def _open_text(
        self,
        request: urllib.request.Request,
        *,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> tuple[str, str]:
        try:
            if opener is None:
                response_context = urllib.request.urlopen(
                    request,
                    timeout=self.request_timeout_seconds,
                )
            else:
                response_context = opener.open(
                    request,
                    timeout=self.request_timeout_seconds,
                )

            with response_context as response:
                return response.read().decode("utf-8", errors="replace"), response.geturl()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ScoritoApiError(
                f"HTTP {exc.code} tijdens het laden van {request.full_url}",
                status_code=exc.code,
                body=body,
            ) from exc
        except urllib.error.URLError as exc:
            raise ScoritoApiError(f"Netwerkfout tijdens het laden van {request.full_url}: {exc}") from exc

    def _open_json(
        self,
        request: urllib.request.Request,
        *,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> dict:
        raw_text, _ = self._open_text(request, opener=opener)
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ScoritoApiError(
                f"Scorito returned invalid JSON from {request.full_url}",
                body=raw_text[:1000],
            ) from exc

    @staticmethod
    def _request(
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> urllib.request.Request:
        request_headers = {"User-Agent": DEFAULT_USER_AGENT}
        if headers:
            request_headers.update(headers)
        return urllib.request.Request(url, data=data, headers=request_headers)

    @staticmethod
    def _extract_input_value(html_text: str, name: str) -> str | None:
        pattern = rf'name="{re.escape(name)}"[^>]*value="([^"]*)"'
        match = re.search(pattern, html_text, re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _pkce_pair() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("utf-8")).digest()
        ).decode("utf-8")
        return verifier, challenge.rstrip("=")

    @staticmethod
    def _extract_user_id(id_token: str | None) -> int | None:
        if not id_token:
            return None

        parts = id_token.split(".")
        if len(parts) < 2:
            return None

        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
            parsed = json.loads(decoded)
            sub = parsed.get("sub")
            return int(sub) if sub is not None else None
        except (ValueError, json.JSONDecodeError):
            return None
