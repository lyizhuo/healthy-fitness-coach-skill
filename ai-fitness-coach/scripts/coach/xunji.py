"""Xunji Open API client (training, plans, food)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from .config import Config
from .http import ApiError, RateLimiter, bearer, post_json

TRAIN_BASE = "https://trains.xunjiapp.cn"
PLAN_BASE = "https://api.xunjiapp.cn"
FOOD_BASE = "https://eatings.xunjiapp.cn"
FOOD_SEARCH_BASE = "https://api.xunjiapp.cn"


def daterange(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _res(payload: Any) -> Any:
    if isinstance(payload, dict) and "res" in payload:
        return payload["res"]
    return payload


class XunjiClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.train_limiter = RateLimiter(config.read_delay_seconds)
        self.full_limiter = RateLimiter(config.full_read_delay_seconds)
        self.write_limiter = RateLimiter(config.write_delay_seconds)
        self.food_limiter = RateLimiter(config.read_delay_seconds)

    def _post(self, url: str, key: str, payload: dict[str, Any], limiter: RateLimiter | None, delay: bool) -> Any:
        if not key:
            raise ApiError("missing xunji API key", code="missing_key")
        if delay and limiter:
            limiter.wait()
        try:
            response = post_json(
                url,
                payload,
                headers=bearer(key),
                timeout=self.config.request_timeout,
            )
        except ApiError as exc:
            if limiter:
                limiter.handle_error(exc)
            raise
        return response

    # Training -----------------------------------------------------------------

    def fetch_train_day(self, datestr: str, *, full: bool = False, delay: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": "train_open_api_v2",
            "datestr": datestr,
            "include_full_data": full,
        }
        response = self._post(
            f"{TRAIN_BASE}/api_trains_for_llm_v2",
            self.config.xunji_train_key,
            payload,
            self.full_limiter if full else self.train_limiter,
            delay,
        )
        res = _res(response)
        if isinstance(res, list):
            return {"trains": res, "raw": response}
        if isinstance(res, dict):
            trains = res.get("trains") or res.get("records") or []
            return {"trains": trains, "raw": response}
        return {"trains": [], "raw": response}

    def fetch_train_range(self, start: date, end: date, *, full: bool = False, delay: bool = True) -> list[dict[str, Any]]:
        days: list[dict[str, Any]] = []
        for current in daterange(start, end):
            days.append(
                {
                    "date": current.isoformat(),
                    **self.fetch_train_day(current.isoformat(), full=full, delay=delay),
                }
            )
        return days

    def fetch_plan_list(self) -> dict[str, Any]:
        payload = {"schema_version": "plan_open_api_v1", "action": "list"}
        response = self._post(
            f"{PLAN_BASE}/open/plan/query_gzip",
            self.config.xunji_train_key,
            payload,
            self.train_limiter,
            True,
        )
        return _res(response)

    def fetch_plan(
        self,
        plan_ref: str,
        start_date: str | None = None,
        end_date: str | None = None,
        *,
        include_movements: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "plan_open_api_v1",
            "action": "get",
            "plan_ref": plan_ref,
            "include_movements": include_movements,
        }
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date
        response = self._post(
            f"{PLAN_BASE}/open/plan/query_gzip",
            self.config.xunji_train_key,
            payload,
            self.train_limiter,
            True,
        )
        return _res(response)

    def upsert_trains(
        self,
        trains: list[dict[str, Any]],
        *,
        client_request_id: str,
        dry_run: bool = False,
        include_full_data: bool = False,
    ) -> Any:
        payload = {
            "schema_version": "train_open_api_v2",
            "client_request_id": client_request_id,
            "dry_run": dry_run,
            "include_full_data": include_full_data,
            "res": trains,
        }
        response = self._post(
            f"{TRAIN_BASE}/api_upsert_trains_for_llm_v2",
            self.config.xunji_train_key,
            payload,
            self.write_limiter,
            True,
        )
        return _res(response)

    # Food ---------------------------------------------------------------------

    def fetch_food_range(self, start_date: str, end_date: str, *, include_detail: bool = True, delay: bool = True) -> dict[str, Any]:
        payload = {
            "start_date": start_date,
            "end_date": end_date,
            "include_detail": include_detail,
        }
        response = self._post(
            f"{FOOD_BASE}/open/food/query_gzip",
            self.config.xunji_food_key,
            payload,
            self.food_limiter,
            delay,
        )
        res = _res(response)
        return {"data": res, "raw": response}

    def fetch_food_day(self, datestr: str, *, include_detail: bool = True, delay: bool = True) -> dict[str, Any]:
        return self.fetch_food_range(datestr, datestr, include_detail=include_detail, delay=delay)

    def search_food(self, keyword: str, *, limit: int = 8, delay: bool = True) -> dict[str, Any]:
        payload = {"keyword": keyword, "limit": limit}
        response = self._post(
            f"{FOOD_SEARCH_BASE}/open_agent/food/search_gzip",
            self.config.xunji_food_search_key,
            payload,
            self.food_limiter,
            delay,
        )
        res = _res(response)
        return res if isinstance(res, dict) else {"foods": res}

    def upsert_foods(
        self,
        foods: list[dict[str, Any]],
        *,
        client_request_id: str,
        dry_run: bool = False,
    ) -> Any:
        payload = {
            "client_request_id": client_request_id,
            "dry_run": dry_run,
            "foods": foods,
        }
        response = self._post(
            f"{FOOD_BASE}/open/food/upsert_gzip",
            self.config.xunji_food_key,
            payload,
            self.write_limiter,
            True,
        )
        return _res(response)

    def create_custom_food(
        self,
        food: dict[str, Any],
        *,
        client_request_id: str,
        dry_run: bool = False,
    ) -> Any:
        payload = {
            "client_request_id": client_request_id,
            "dry_run": dry_run,
            "food": food,
        }
        response = self._post(
            f"{FOOD_BASE}/open/food/custom/upsert_gzip",
            self.config.xunji_food_key,
            payload,
            self.write_limiter,
            True,
        )
        return _res(response)
