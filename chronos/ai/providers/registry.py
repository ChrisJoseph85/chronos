"""Provider registry: SQLite-backed CRUD + chain building + model discovery.

Chronos.md §5.1 + proposals B.3. Keys are WRITE-ONLY: values live in
SQLite (provider_keys.key_value) and are never returned by any public
method here. list/get return key_ids + key_count only.
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
from typing import Any

VALID_GROUPS = ("stt", "text", "embeddings")

SETUP_GROUPS = ["stt", "text", "embeddings"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _uid() -> str:
    return uuid.uuid4().hex


def _valid_url(url: str) -> bool:
    u = (url or "").strip()
    return u.startswith("http://") or u.startswith("https://")


def _default_model(group: str) -> str:
    try:
        if group == "stt":
            from chronos.ai.providers.adapter import DEFAULT_STT_MODEL

            return DEFAULT_STT_MODEL
        if group == "embeddings":
            from chronos.ai.providers.adapter import DEFAULT_EMBEDDING_MODEL

            return DEFAULT_EMBEDDING_MODEL
        from chronos.ai.providers.adapter import DEFAULT_TEXT_MODEL

        return DEFAULT_TEXT_MODEL
    except Exception:
        return ""


def discover_models(base_url: str, key: str | None = None, transport: Any = None) -> dict:
    """GET {base_url}/models -> {reachable, models:[ids]}.

    OpenAI shape {data:[{id}]}. Graceful on any error/timeout/
    non-OpenAI shape -> {reachable:false, models:[]}. No network in
    tests: pass a fake transport callable.
    """
    url = (base_url or "").rstrip("/") + "/models"
    headers: dict = {}
    if key:
        headers["Authorization"] = "Bearer %s" % key
    try:
        if transport is not None:
            try:
                raw = transport(url, dict(headers), None)
            except TypeError:
                try:
                    raw = transport(url, dict(headers))
                except TypeError:
                    raw = transport(url)
        else:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", "replace")
            try:
                raw = json.loads(body) if body.strip() else {}
            except (ValueError, AttributeError):
                return {"reachable": False, "models": []}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return {"reachable": False, "models": []}
        if not isinstance(raw, dict):
            return {"reachable": False, "models": []}
        data = raw.get("data")
        if not isinstance(data, list):
            return {"reachable": False, "models": []}
        models = [str(d.get("id")) for d in data if isinstance(d, dict) and d.get("id")]
        return {"reachable": True, "models": models}
    except Exception:
        return {"reachable": False, "models": []}


class ProviderRegistry:
    """CRUD over a sqlite3 connection. Never returns key values."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
        except Exception:
            pass
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS providers (
            id TEXT PRIMARY KEY, grp TEXT NOT NULL, name TEXT NOT NULL,
            base_url TEXT NOT NULL, model TEXT NOT NULL,
            position INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL)"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_providers_grp_pos ON providers(grp, position)"
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS provider_keys (
            id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
            key_value TEXT NOT NULL, created_at INTEGER NOT NULL)"""
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_provider_keys_provider ON provider_keys(provider_id)"
        )

    # -- internals ------------------------------------------------------
    def _row_to_entry(self, row) -> dict:
        pid = row["id"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
        try:
            krows = self._conn.execute(
                "SELECT id FROM provider_keys WHERE provider_id = ? ORDER BY created_at, rowid",
                (pid,),
            ).fetchall()
            key_ids = [str(r["id"] if hasattr(r, "keys") else r[0]) for r in krows]
        except Exception:
            key_ids = []
        grp = row["grp"] if hasattr(row, "keys") else row[1]
        return {
            "id": str(row["id"] if hasattr(row, "keys") else row[0]),
            "group": str(grp),
            "grp": str(grp),
            "name": str(row["name"] if hasattr(row, "keys") else row[2]),
            "base_url": str(row["base_url"] if hasattr(row, "keys") else row[3]),
            "model": str(row["model"] if hasattr(row, "keys") else row[4]),
            "position": int(row["position"] if hasattr(row, "keys") else row[5]),
            "active": int(row["active"] if hasattr(row, "keys") else row[6]),
            "created_at": int(row["created_at"] if hasattr(row, "keys") else row[7]),
            "key_ids": key_ids,
            "key_count": len(key_ids),
        }

    def _fetch(self, provider_id: str):
        return self._conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()

    def _max_position(self, group: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM providers WHERE grp = ?", (group,)
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else -1

    # -- CRUD -----------------------------------------------------------
    def create_provider(
        self,
        group: str,
        name: str,
        base_url: str,
        model: str | None = None,
        position: int | None = None,
    ) -> dict:
        grp = (group or "").strip()
        if grp not in VALID_GROUPS:
            raise ValueError("bad group")
        if not (name or "").strip():
            raise ValueError("name is required")
        if not _valid_url(base_url or ""):
            raise ValueError("bad base_url")
        mdl = (model or "").strip() or _default_model(grp)
        if position is None:
            pos = self._max_position(grp) + 1
        else:
            pos = max(0, int(position))
            self._conn.execute(
                "UPDATE providers SET position = position + 1 WHERE grp = ? AND position >= ?",
                (grp, pos),
            )
        pid = _uid()
        now = _now_ms()
        existing = self._conn.execute("SELECT COUNT(*) FROM providers WHERE grp = ?", (grp,)).fetchone()
        active = 1 if int(existing[0]) == 0 else 0
        self._conn.execute(
            "INSERT INTO providers (id, grp, name, base_url, model, position, active, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, grp, name.strip(), (base_url or "").strip(), mdl, pos, active, now),
        )
        row = self._fetch(pid)
        return self._row_to_entry(row)

    def list_providers(self, group: str | None = None) -> list:
        if group is not None:
            if group not in VALID_GROUPS:
                raise ValueError("bad group")
            rows = self._conn.execute(
                "SELECT * FROM providers WHERE grp = ? ORDER BY position, created_at, rowid",
                (group,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM providers ORDER BY grp, position, created_at, rowid"
            ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def list_grouped(self) -> dict:
        out: dict = {g: [] for g in VALID_GROUPS}
        for entry in self.list_providers():
            out[entry["group"]].append(entry)
        for g in out:
            out[g].sort(key=lambda e: (e["position"], e["created_at"]))
        return out

    def get_provider(self, provider_id: str) -> dict | None:
        row = self._fetch(provider_id)
        return self._row_to_entry(row) if row else None

    def update_provider(
        self,
        provider_id: str,
        name: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        position: int | None = None,
    ) -> dict | None:
        row = self._fetch(provider_id)
        if row is None:
            return None
        grp = row["grp"] if hasattr(row, "keys") else row[1]
        fields: dict = {}
        if name is not None:
            if not str(name).strip():
                raise ValueError("bad name")
            fields["name"] = str(name).strip()
        if base_url is not None:
            if not _valid_url(base_url):
                raise ValueError("bad base_url")
            fields["base_url"] = base_url.strip()
        if model is not None:
            fields["model"] = str(model)
        if fields:
            self._conn.execute(
                "UPDATE providers SET %s WHERE id = ?" % ", ".join("%s = ?" % k for k in fields),
                (*fields.values(), provider_id),
            )
        if position is not None:
            self._reorder(grp, provider_id, max(0, int(position)))
        self._conn.execute("SELECT 1")
        updated = self._fetch(provider_id)
        return self._row_to_entry(updated)

    def _reorder(self, group: str, provider_id: str, new_pos: int) -> None:
        rows = self._conn.execute(
            "SELECT id FROM providers WHERE grp = ? ORDER BY position, created_at, rowid",
            (group,),
        ).fetchall()
        ids = [str(r["id"] if hasattr(r, "keys") else r[0]) for r in rows if str(r["id"] if hasattr(r, "keys") else r[0]) != provider_id]
        new_pos = max(0, min(new_pos, len(ids)))
        ids.insert(new_pos, provider_id)
        for i, pid in enumerate(ids):
            self._conn.execute("UPDATE providers SET position = ? WHERE id = ?", (i, pid))

    def delete_provider(self, provider_id: str) -> bool:
        try:
            self._conn.execute("DELETE FROM provider_keys WHERE provider_id = ?", (provider_id,))
        except Exception:
            pass
        cur = self._conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
        return cur.rowcount > 0

    # -- keys (write-only) ----------------------------------------------
    def add_key(self, provider_id: str, value: str) -> dict:
        if not value or not str(value).strip():
            raise ValueError("key is required")
        if self._fetch(provider_id) is None:
            raise KeyError("provider not found")
        kid = _uid()
        self._conn.execute(
            "INSERT INTO provider_keys (id, provider_id, key_value, created_at) VALUES (?, ?, ?, ?)",
            (kid, provider_id, str(value), _now_ms()),
        )
        return {"key_id": kid}

    def delete_key(self, provider_id: str, key_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM provider_keys WHERE id = ? AND provider_id = ?", (key_id, provider_id)
        )
        return cur.rowcount > 0

    def key_values(self, provider_id: str) -> list:
        """Internal: values for outbound calls only. Never expose via API."""
        rows = self._conn.execute(
            "SELECT key_value FROM provider_keys WHERE provider_id = ? ORDER BY created_at, rowid",
            (provider_id,),
        ).fetchall()
        return [str(r["key_value"] if hasattr(r, "keys") else r[0]) for r in rows]

    def set_active(self, group: str, provider_id: str) -> dict | None:
        if group not in VALID_GROUPS:
            raise ValueError("bad group")
        row = self._fetch(provider_id)
        if row is None:
            return None
        row_grp = row["grp"] if hasattr(row, "keys") else row[1]
        if row_grp != group:
            raise ValueError("group mismatch")
        self._conn.execute("UPDATE providers SET active = 0 WHERE grp = ?", (group,))
        self._conn.execute("UPDATE providers SET active = 1 WHERE id = ?", (provider_id,))
        return self.get_provider(provider_id)

    # -- chain ----------------------------------------------------------
    def build_chain(self, group: str, transport: Any = None):
        from chronos.ai.providers.adapter import OpenAICompatibleAdapter
        from chronos.ai.providers.chain import ProviderChain

        if group not in VALID_GROUPS:
            raise ValueError("bad group")
        rows = self._conn.execute(
            "SELECT * FROM providers WHERE grp = ? ORDER BY position, created_at, rowid",
            (group,),
        ).fetchall()
        adapters = []
        for r in rows:
            pid = r["id"] if hasattr(r, "keys") else r[0]
            name = r["name"] if hasattr(r, "keys") else r[2]
            base_url = r["base_url"] if hasattr(r, "keys") else r[3]
            model = r["model"] if hasattr(r, "keys") else r[4]
            adapters.append(
                OpenAICompatibleAdapter(
                    base_url=base_url,
                    model=model,
                    api_keys=self.key_values(str(pid)),
                    name=name,
                    transport=transport,
                )
            )
        return ProviderChain(adapters)
