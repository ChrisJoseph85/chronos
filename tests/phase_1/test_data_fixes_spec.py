"""WAVE-2 data fixes (Chronos.md §4, §4.8, §7.2).

- §4.8: canonical FTS `fts5(title, notes, node_id UNINDEXED)` regular table,
  identical CREATE everywhere, join back on node_id match.
- §4: CLI schema single-source from chronos.db.bootstrap (node_links,
  triggers, CHECKs); db-upgrade path byte-identical to API path.
- §7.2: repo create_event snaps to minute grid.
- §4.8: create_node indexes with node_id, delete_node cleans FTS,
  absent FTS never breaks writes (narrow except OperationalError).
Real sqlite3 only, no mocks.
"""

import sqlite3

CANONICAL = "CREATE VIRTUAL TABLE IF NOT EXISTS node_fts USING fts5(title, notes, node_id UNINDEXED)"


def _fresh_mem():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _nodes_ddl():
    from chronos.db.bootstrap import DDL_STATEMENTS

    for s in DDL_STATEMENTS:
        if s.strip().upper().startswith("CREATE TABLE") and "nodes (" in s:
            return s
    raise AssertionError("nodes DDL missing (§4)")


def test_canonical_fts_identical_across_writers():
    """§4.8: bootstrap/search/repo/CLI share one identical CREATE string."""
    from chronos.db import bootstrap
    from chronos.db import repo
    from chronos.db import search

    assert bootstrap.FTS_DDL == CANONICAL
    assert search.FTS_DDL == CANONICAL
    assert getattr(search, "_CANONICAL_FTS_DDL", CANONICAL) == CANONICAL
    assert repo.FTS_DDL == CANONICAL
    # DDL_STATEMENTS embeds the canonical string verbatim (§4.8).
    assert CANONICAL in list(bootstrap.DDL_STATEMENTS)
    # CLI single-sources bootstrap (§4): embedded copy deleted.
    import chronos.cli as cli

    assert list(cli._SCHEMA_STATEMENTS) == list(bootstrap.DDL_STATEMENTS)
    fts_stmts = [s for s in cli._SCHEMA_STATEMENTS if "node_fts" in s]
    assert fts_stmts == [CANONICAL]
    for bad in ("content=''", "content=\"\"", "rowid", "sha", "SHA"):
        for stmt in [bootstrap.FTS_DDL, search.FTS_DDL, repo.FTS_DDL, *fts_stmts]:
            assert bad.lower() not in stmt.lower() or (bad == "rowid" and False), \
                "forbidden %r in FTS DDL (§4.8)" % bad


def test_canonical_create_executes_and_joins_back():
    """§4.8: each writer's CREATE executes; insert + node_id join works."""
    from chronos.db import bootstrap
    from chronos.db import repo
    from chronos.db import search
    import chronos.cli as cli

    writers = [
        bootstrap.FTS_DDL,
        search.FTS_DDL,
        repo.FTS_DDL,
        [s for s in cli._SCHEMA_STATEMENTS if "node_fts" in s][0],
    ]
    assert all(w == CANONICAL for w in writers)
    for ddl in writers:
        conn = _fresh_mem()
        try:
            conn.execute(_nodes_ddl())
            conn.execute(ddl)
            conn.execute(
                "INSERT INTO nodes (id, parent_id, kind, title, notes, status,"
                " created_at, updated_at, done_at)"
                " VALUES ('n1', NULL, 'task', 'Buy database textbook', 'notes',"
                " 'active', 1, 1, NULL)"
            )
            conn.execute(
                "INSERT INTO node_fts (title, notes, node_id) VALUES (?, ?, ?)",
                ("Buy database textbook", "notes", "n1"),
            )
            hits = conn.execute(
                "SELECT n.id FROM node_fts JOIN nodes n ON n.id = node_fts.node_id"
                " WHERE node_fts MATCH 'database'"
            ).fetchall()
            assert [r[0] for r in hits] == ["n1"]
        finally:
            conn.close()


def test_cli_schema_equals_bootstrap_schema():
    """§4: CLI db-upgrade schema == API bootstrap schema (tables/triggers/indexes)."""
    from chronos.db.bootstrap import DDL_STATEMENTS, init_db
    import chronos.cli as cli

    api = _fresh_mem()
    init_db(api)
    melt = _fresh_mem()
    for stmt in cli._SCHEMA_STATEMENTS:
        try:
            melt.execute(stmt)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "vec0" in msg or "no such module" in msg:
                continue
            raise
    melt.commit()

    def sets(conn, extra_vec=True):
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        triggers = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()}
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        if extra_vec:
            tables.discard("node_vec")
        return tables, triggers, indexes

    at, arg, aix = sets(api)
    ct, crg, cix = sets(melt)
    assert ct == at, "CLI tables != bootstrap tables (§4): %s vs %s" % (sorted(ct), sorted(at))
    assert crg == arg, "CLI triggers != bootstrap triggers (§4)"
    assert cix == aix, "CLI indexes != bootstrap indexes (§4)"
    # Must include node_links, triggers, CHECKs (§4.1, §4.4, §4.7).
    assert "node_links" in ct
    assert any("node_tags_no_project" in t for t in crg)
    assert any("timer_one_running" in t for t in crg)
    sql = melt.execute(
        "SELECT sql FROM sqlite_master WHERE name='review_series'").fetchone()[0]
    assert "CHECK" in sql
    api.close()
    melt.close()


def _repo_on_mem():
    from chronos.db.bootstrap import init_db
    from chronos.db.repo import Repo

    conn = _fresh_mem()
    init_db(conn)
    return Repo(conn), conn


def test_grid_snap_via_repo_direct():
    """§7.2: Repo.create_event snaps start/end to minute grid (ceil)."""
    repo, conn = _repo_on_mem()
    t0 = 1_700_000_000_000
    def ceil_ms(ms):
        return ((ms + 60_000 - 1) // 60_000) * 60_000
    out = repo.create_event("g", t0 + 30_500, t0 + 30_500 + 60_000)
    row = conn.execute("SELECT start_ms, end_ms FROM events WHERE id=?",
                       (out["id"],)).fetchone()
    assert row[0] == ceil_ms(t0 + 30_500)
    assert row[1] == ceil_ms(t0 + 30_500 + 60_000)
    assert row[0] % 60_000 == 0 and row[1] % 60_000 == 0
    out2 = repo.create_event("g2", ceil_ms(t0), ceil_ms(t0) + 60_000)
    row2 = conn.execute("SELECT start_ms, end_ms FROM events WHERE id=?",
                        (out2["id"],)).fetchone()
    assert (row2[0], row2[1]) == (ceil_ms(t0), ceil_ms(t0) + 60_000)
    conn.close()


def test_create_indexes_with_node_id_and_delete_cleans_fts():
    """§4.8: create_node indexes (title,notes,node_id); delete_node cleans FTS."""
    repo, conn = _repo_on_mem()
    created = repo.create_node("task", "unique alpha beta xyz", notes="some notes")
    nid = created["id"]
    rows = conn.execute("SELECT node_id FROM node_fts WHERE node_id=?", (nid,)).fetchall()
    assert len(rows) == 1
    hits = conn.execute(
        "SELECT n.id FROM node_fts JOIN nodes n ON n.id = node_fts.node_id"
        " WHERE node_fts MATCH 'alpha'"
    ).fetchall()
    assert [r[0] for r in hits] == [nid]
    repo.delete_node(nid)
    left = conn.execute("SELECT COUNT(*) FROM node_fts WHERE node_id=?", (nid,)).fetchone()[0]
    assert left == 0
    assert conn.execute("SELECT COUNT(*) FROM nodes WHERE id=?", (nid,)).fetchone()[0] == 0
    conn.close()


def test_absent_fts_never_breaks_write():
    """§4.8: absent node_fts never breaks core writes; FTS ops narrow except."""
    import inspect
    from chronos.db import repo as repo_mod
    from chronos.db import search as search_mod

    for mod in (repo_mod, search_mod):
        src = inspect.getsource(mod)
        assert "except OperationalError" in src or "except sqlite3.OperationalError" in src
    # No broad FTS swallow: FTS helpers must not use bare `except Exception`.
    for name in ("_index_node", "_remove_node_index", "_ensure_fts"):
        for mod in (repo_mod, search_mod):
            fn = getattr(mod, name, None)
            if fn is not None:
                assert "except Exception" not in inspect.getsource(fn)

    repo, conn = _repo_on_mem()
    conn.execute("DROP TABLE IF EXISTS node_fts")
    conn.commit()
    # search-side absent FTS never raises (§4.8).
    search_mod.index_node(conn, "ghost", "some title", "some notes")
    # repo-side writes survive absent FTS (§4.8).
    created = repo.create_node("task", "write survives", notes="n")
    assert conn.execute("SELECT title FROM nodes WHERE id=?",
                        (created["id"],)).fetchone()[0] == "write survives"
    t0 = 1_700_000_000_000
    eid = repo.create_event("e", t0, t0 + 60_000)["id"]
    assert conn.execute("SELECT id FROM events WHERE id=?", (eid,)).fetchone()[0] == eid
    repo.delete_node(created["id"])
    conn.close()


def test_seed_buckets_idempotent_counts():
    """§4.3: seed_buckets INSERT OR IGNORE, ~4300 rows / 10y, reseed no-op."""
    import inspect
    from chronos.db.bootstrap import init_db
    import chronos.db.buckets as buckets

    src = inspect.getsource(buckets.seed_buckets)
    assert "INSERT OR IGNORE" in src
    conn = _fresh_mem()
    init_db(conn)
    counts = buckets.seed_buckets(conn)
    assert counts["Y"] == 10
    assert counts["M"] == 120
    total = conn.execute("SELECT COUNT(*) FROM buckets").fetchone()[0]
    assert 4250 <= total <= 4400
    before = {k: conn.execute(
        "SELECT COUNT(*) FROM buckets WHERE level=?", (k,)).fetchone()[0]
        for k in ("Y", "M", "W", "D")}
    buckets.seed_buckets(conn)
    after = {k: conn.execute(
        "SELECT COUNT(*) FROM buckets WHERE level=?", (k,)).fetchone()[0]
        for k in ("Y", "M", "W", "D")}
    assert before == after
    conn.close()
