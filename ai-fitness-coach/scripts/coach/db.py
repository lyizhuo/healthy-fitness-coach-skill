"""SQLite storage for normalized coach data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS trains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  localid TEXT NOT NULL DEFAULT '',
  title TEXT,
  start_ms INTEGER,
  end_ms INTEGER,
  note_json TEXT,
  volume_kg REAL,
  sets_total INTEGER,
  sets_completed INTEGER,
  body_parts_json TEXT,
  heart_rate_json TEXT,
  warnings_json TEXT,
  raw_json TEXT,
  fetched_at TEXT,
  UNIQUE(date, localid)
);

CREATE TABLE IF NOT EXISTS movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  train_id INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
  movement_index INTEGER,
  name TEXT,
  type TEXT,
  exetype TEXT,
  rest_time REAL,
  warn_rest_time REAL,
  difficulty TEXT,
  cardio INTEGER,
  aerobic INTEGER,
  metrics_json TEXT,
  body_parts_json TEXT,
  volume_kg REAL
);

CREATE TABLE IF NOT EXISTS sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  train_id INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
  movement_id INTEGER NOT NULL REFERENCES movements(id) ON DELETE CASCADE,
  movement_index INTEGER,
  set_index INTEGER,
  done INTEGER,
  weight REAL,
  unit TEXT,
  reps REAL,
  time_s REAL,
  rpe TEXT,
  set_type TEXT,
  self_weight INTEGER,
  note TEXT,
  comment TEXT,
  rest_seconds REAL,
  volume_kg REAL,
  items_json TEXT
);

CREATE TABLE IF NOT EXISTS food_days (
  date TEXT PRIMARY KEY,
  raw_json TEXT,
  fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS food_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  record_id TEXT NOT NULL DEFAULT '',
  meal_type TEXT,
  name TEXT,
  amount REAL,
  unit TEXT,
  uniquekey TEXT,
  ntr_json TEXT,
  macros_json TEXT,
  macro_known INTEGER,
  macro_basis TEXT,
  raw_json TEXT,
  UNIQUE(date, record_id, name, amount, unit)
);

CREATE TABLE IF NOT EXISTS plans (
  plan_ref TEXT NOT NULL,
  date TEXT NOT NULL,
  day_json TEXT,
  fetched_at TEXT,
  PRIMARY KEY (plan_ref, date)
);

CREATE TABLE IF NOT EXISTS readiness (
  date TEXT PRIMARY KEY,
  tier TEXT,
  score REAL,
  components_json TEXT,
  confidence REAL,
  inputs_json TEXT,
  safety_flag INTEGER,
  reasons_json TEXT,
  generated_at TEXT
);

CREATE TABLE IF NOT EXISTS weights (
  date TEXT PRIMARY KEY,
  weight_kg REAL NOT NULL,
  source TEXT,
  note TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT,
  date TEXT,
  kind TEXT,
  summary TEXT,
  evidence_json TEXT,
  action TEXT,
  verification TEXT
);

CREATE TABLE IF NOT EXISTS dna_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  generated_at TEXT,
  window_start TEXT,
  window_end TEXT,
  payload_json TEXT,
  confidence TEXT
);

CREATE TABLE IF NOT EXISTS operations (
  client_request_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT,
  payload_hash TEXT,
  created_at TEXT,
  updated_at TEXT,
  response_json TEXT
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA)
    for table, columns in (
        ("readiness", (("safety_flag", "INTEGER"), ("reasons_json", "TEXT"))),
        ("food_records", (("macro_basis", "TEXT"),)),
    ):
        for column, ddl in columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass
    conn.commit()
    return conn


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()


def _localid(value: Any) -> str:
    return "" if value is None else str(value)


def save_train_day(conn: sqlite3.Connection, date_value: str, trains: Iterable[dict[str, Any]], raw: Any) -> int:
    conn.execute("DELETE FROM trains WHERE date = ?", (date_value,))
    count = 0
    for train_index, train in enumerate(trains):
        localid = _localid(train.get("localid")) or f"auto:{train_index}"
        cursor = conn.execute(
            """
            INSERT INTO trains (date, localid, title, start_ms, end_ms, note_json, volume_kg,
              sets_total, sets_completed, body_parts_json, heart_rate_json, warnings_json, raw_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date_value,
                localid,
                train.get("title"),
                train.get("start_ms"),
                train.get("end_ms"),
                json_dumps(train.get("note")),
                train.get("volume_kg"),
                train.get("sets_total"),
                train.get("sets_completed"),
                json_dumps(train.get("body_parts") or {}),
                json_dumps(train.get("heart_rate")),
                json_dumps(train.get("warnings") or []),
                json_dumps(train.get("raw")),
                now_iso(),
            ),
        )
        train_id = cursor.lastrowid
        for movement_pos, movement in enumerate(train.get("movements") or []):
            movement_cursor = conn.execute(
                """
                INSERT INTO movements (train_id, movement_index, name, type, exetype, rest_time,
                  warn_rest_time, difficulty, cardio, aerobic, metrics_json, body_parts_json, volume_kg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    train_id,
                    movement.get("index") if movement.get("index") is not None else movement_pos,
                    movement.get("name"),
                    movement.get("type"),
                    movement.get("exetype"),
                    movement.get("rest_time"),
                    movement.get("warn_rest_time"),
                    movement.get("difficulty"),
                    int(bool(movement.get("cardio"))),
                    int(bool(movement.get("aerobic"))),
                    json_dumps(movement.get("metrics") or {}),
                    json_dumps(movement.get("body_parts") or []),
                    movement.get("volume_kg"),
                ),
            )
            movement_id = movement_cursor.lastrowid
            for set_pos, item in enumerate(movement.get("sets") or []):
                conn.execute(
                    """
                    INSERT INTO sets (train_id, movement_id, movement_index, set_index, done, weight,
                      unit, reps, time_s, rpe, set_type, self_weight, note, comment, rest_seconds, volume_kg, items_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        train_id,
                        movement_id,
                        movement.get("index") if movement.get("index") is not None else movement_pos,
                        item.get("index") if item.get("index") is not None else set_pos,
                        int(bool(item.get("done", True))),
                        item.get("weight"),
                        item.get("unit"),
                        item.get("reps"),
                        item.get("time_s"),
                        item.get("rpe"),
                        item.get("set_type"),
                        int(bool(item.get("self_weight"))),
                        item.get("note"),
                        item.get("comment"),
                        item.get("rest_seconds"),
                        item.get("volume_kg"),
                        json_dumps(item.get("items") or []),
                    ),
                )
        count += 1
    conn.commit()
    return count


def save_food_day(conn: sqlite3.Connection, date_value: str, records: Iterable[dict[str, Any]], raw: Any) -> int:
    conn.execute("DELETE FROM food_records WHERE date = ?", (date_value,))
    conn.execute(
        "INSERT OR REPLACE INTO food_days (date, raw_json, fetched_at) VALUES (?, ?, ?)",
        (date_value, json_dumps(raw), now_iso()),
    )
    count = 0
    for record in records:
        conn.execute(
            """
            INSERT OR REPLACE INTO food_records (date, record_id, meal_type, name, amount, unit,
              uniquekey, ntr_json, macros_json, macro_known, macro_basis, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date_value,
                _localid(record.get("record_id")),
                record.get("meal_type"),
                record.get("name"),
                record.get("amount"),
                record.get("unit"),
                record.get("uniquekey"),
                json_dumps(record.get("ntr") or {}),
                json_dumps(record.get("macros") or {}),
                int(bool(record.get("macro_known"))),
                record.get("macro_basis"),
                json_dumps(record.get("raw")),
            ),
        )
        count += 1
    conn.commit()
    return count


def save_plan(conn: sqlite3.Connection, plan_ref: str, days: Iterable[dict[str, Any]]) -> int:
    count = 0
    for day in days:
        date_value = day.get("date") or day.get("datestr")
        if not date_value:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO plans (plan_ref, date, day_json, fetched_at) VALUES (?, ?, ?, ?)",
            (plan_ref, date_value, json_dumps(day), now_iso()),
        )
        count += 1
    conn.commit()
    return count


def save_readiness(conn: sqlite3.Connection, date_value: str, result: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO readiness (date, tier, score, components_json, confidence, inputs_json, safety_flag, reasons_json, generated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            date_value,
            result.get("tier"),
            result.get("score"),
            json_dumps(result.get("components") or {}),
            result.get("confidence"),
            json_dumps(result.get("inputs") or {}),
            int(bool(result.get("safety_flag"))),
            json_dumps(result.get("reasons") or []),
            now_iso(),
        ),
    )
    conn.commit()


def save_weight(conn: sqlite3.Connection, date_value: str, weight_kg: float, source: str = "manual", note: str | None = None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO weights (date, weight_kg, source, note) VALUES (?, ?, ?, ?)",
        (date_value, weight_kg, source, note),
    )
    conn.commit()


def _append_decision(
    decisions_path: Path,
    *,
    date_value: str | None,
    kind: str,
    summary: str,
    evidence: Any,
    action: str | None,
    verification: str | None,
) -> None:
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = now_iso()
    lines = [f"## {date_value or stamp[:10]} · {kind}", f"- 记录时间：{stamp}"]
    if evidence not in (None, "", {}, []):
        rendered = evidence if isinstance(evidence, str) else json_dumps(evidence)
        lines.append(f"- 证据：{rendered}")
    lines.extend(
        [
            f"- 判断：{summary}",
            f"- 行动：{action or '未记录'}",
            f"- 验证：{verification or '未记录'}",
        ]
    )
    with decisions_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n\n")


def add_decision(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
    kind: str,
    summary: str,
    evidence: Any = None,
    action: str | None = None,
    verification: str | None = None,
    decisions_path: Path | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO decisions (created_at, date, kind, summary, evidence_json, action, verification) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now_iso(), date_value, kind, summary, json_dumps(evidence), action, verification),
    )
    conn.commit()
    if decisions_path is not None:
        _append_decision(
            decisions_path,
            date_value=date_value,
            kind=kind,
            summary=summary,
            evidence=evidence,
            action=action,
            verification=verification,
        )
    return int(cursor.lastrowid)


def save_dna(conn: sqlite3.Connection, dna: dict[str, Any]) -> int:
    cursor = conn.execute(
        "INSERT INTO dna_versions (generated_at, window_start, window_end, payload_json, confidence) VALUES (?, ?, ?, ?, ?)",
        (
            now_iso(),
            dna.get("window", {}).get("start"),
            dna.get("window", {}).get("end"),
            json_dumps(dna),
            dna.get("confidence"),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def create_operation(conn: sqlite3.Connection, client_request_id: str, kind: str, payload: Any, status: str = "preview") -> None:
    conn.execute(
        "INSERT OR REPLACE INTO operations (client_request_id, kind, status, payload_json, payload_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (client_request_id, kind, status, json_dumps(payload), payload_hash(payload), now_iso(), now_iso()),
    )
    conn.commit()


def update_operation(conn: sqlite3.Connection, client_request_id: str, status: str, response: Any = None) -> None:
    conn.execute(
        "UPDATE operations SET status = ?, response_json = ?, updated_at = ? WHERE client_request_id = ?",
        (status, json_dumps(response), now_iso(), client_request_id),
    )
    conn.commit()


def get_operation(conn: sqlite3.Connection, client_request_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM operations WHERE client_request_id = ?", (client_request_id,)).fetchone()
    return dict(row) if row else None


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def get_train_day(conn: sqlite3.Connection, date_value: str) -> list[dict[str, Any]]:
    trains = [dict(row) for row in conn.execute("SELECT * FROM trains WHERE date = ? ORDER BY start_ms", (date_value,))]
    for train in trains:
        movements = [dict(row) for row in conn.execute("SELECT * FROM movements WHERE train_id = ? ORDER BY movement_index", (train["id"],))]
        for movement in movements:
            movement["body_parts"] = _json(movement.get("body_parts_json"), [])
            movement["metrics"] = _json(movement.get("metrics_json"), {})
            movement["sets"] = [
                dict(row) for row in conn.execute(
                    "SELECT * FROM sets WHERE movement_id = ? ORDER BY set_index", (movement["id"],)
                )
            ]
            for item in movement["sets"]:
                item["items"] = _json(item.get("items_json"), [])
        train["movements"] = movements
        train["body_parts"] = _json(train.get("body_parts_json"), {})
        train["warnings"] = _json(train.get("warnings_json"), [])
        train["heart_rate"] = _json(train.get("heart_rate_json"), None)
    return trains


def get_train_range(conn: sqlite3.Connection, start: str, end: str) -> list[dict[str, Any]]:
    dates = [row["date"] for row in conn.execute("SELECT DISTINCT date FROM trains WHERE date BETWEEN ? AND ? ORDER BY date", (start, end))]
    return [dict(train, date=date_value) for date_value in dates for train in get_train_day(conn, date_value)]


def get_plan_day(conn: sqlite3.Connection, date_value: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM plans WHERE date = ? ORDER BY fetched_at DESC LIMIT 1", (date_value,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["day"] = _json(item.get("day_json"), {})
    return item


def get_food_day(conn: sqlite3.Connection, date_value: str) -> list[dict[str, Any]]:
    return get_food_range(conn, date_value, date_value)


def get_food_range(conn: sqlite3.Connection, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM food_records WHERE date BETWEEN ? AND ? ORDER BY date, meal_type", (start, end))
    result = []
    for row in rows:
        item = dict(row)
        item["ntr"] = _json(item.get("ntr_json"), {})
        item["macros"] = _json(item.get("macros_json"), {})
        item["macro_known"] = bool(item.get("macro_known"))
        result.append(item)
    return result


def get_readiness(conn: sqlite3.Connection, date_value: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM readiness WHERE date = ?", (date_value,)).fetchone()
    return dict(row) if row else None


def get_readiness_range(conn: sqlite3.Connection, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM readiness WHERE date BETWEEN ? AND ? ORDER BY date", (start, end))
    return [dict(row) for row in rows]


def get_weights(conn: sqlite3.Connection, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM weights WHERE date BETWEEN ? AND ? ORDER BY date", (start, end))
    return [dict(row) for row in rows]


def get_decisions(conn: sqlite3.Connection, start: str | None = None, end: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if start and end:
        rows = conn.execute("SELECT * FROM decisions WHERE date BETWEEN ? AND ? ORDER BY id DESC LIMIT ?", (start, end, limit))
    else:
        rows = conn.execute("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(row) for row in rows]


def latest_dna(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM dna_versions ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    item = dict(row)
    item["payload"] = _json(item.get("payload_json"), {})
    return item


def training_load(conn: sqlite3.Connection, date_value: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT COUNT(DISTINCT t.id) AS sessions, COALESCE(SUM(t.volume_kg),0) AS volume_kg, "
        "COALESCE(SUM(t.sets_completed),0) AS sets_completed FROM trains t WHERE t.date = ?",
        (date_value,),
    ).fetchone()
    return dict(row) if row else {"sessions": 0, "volume_kg": 0, "sets_completed": 0}
