import json
import sqlite3
import time
from contextlib import contextmanager
from app.core.config import DATA, Settings

DB = DATA / 'state.sqlite3'


@contextmanager
def connection():
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    with connection() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, fingerprint TEXT NOT NULL, path TEXT NOT NULL,
          status TEXT NOT NULL, total INTEGER NOT NULL, settings TEXT NOT NULL,
          created REAL NOT NULL, updated REAL NOT NULL, elapsed REAL NOT NULL DEFAULT 0,
          stage TEXT NOT NULL DEFAULT 'Ready', error TEXT, device TEXT NOT NULL DEFAULT 'CPU',
          warnings TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS pages (
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, number INTEGER NOT NULL,
          width REAL NOT NULL, height REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          error TEXT, seconds REAL NOT NULL DEFAULT 0, PRIMARY KEY(job_id,number));
        CREATE TABLE IF NOT EXISTS regions (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          page INTEGER NOT NULL, ordinal INTEGER NOT NULL, status TEXT NOT NULL,
          manual INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS regions_job_page ON regions(job_id,page);
        CREATE TABLE IF NOT EXISTS history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          before_json TEXT NOT NULL, after_json TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS exports (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), status TEXT NOT NULL,
          completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
          path TEXT, error TEXT, created REAL NOT NULL);
        ''')
        if 'engines' not in {row[1] for row in c.execute('PRAGMA table_info(jobs)')}:
            c.execute("ALTER TABLE jobs ADD COLUMN engines TEXT NOT NULL DEFAULT '[]'")
        c.execute("UPDATE jobs SET status='paused',stage='Interrupted · ready to resume' WHERE status IN ('running','queued')")
        c.execute("UPDATE pages SET status='pending' WHERE status='running'")
        c.execute("UPDATE exports SET status='failed',error='Interrupted export; retry to create a new folder' WHERE status IN ('running','queued')")


def settings() -> Settings:
    with connection() as c:
        row = c.execute('SELECT value FROM settings WHERE id=1').fetchone()
    return Settings.model_validate_json(row[0]) if row else Settings()


def save_settings(value: Settings):
    with connection() as c:
        c.execute('INSERT OR REPLACE INTO settings VALUES(1,?)', (value.model_dump_json(),))


def job(job_id: str):
    with connection() as c:
        row = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise KeyError('Document not found')
        result = dict(row)
        counts = dict(c.execute('SELECT status,count(*) FROM regions WHERE job_id=? GROUP BY status', (job_id,)))
        pc = dict(c.execute('SELECT status,count(*) FROM pages WHERE job_id=? GROUP BY status', (job_id,)))
    result['settings'] = json.loads(result['settings'])
    result['warnings'] = json.loads(result['warnings'])
    result['engines'] = json.loads(result['engines'])
    if not result['engines']:
        result['engines']=['Native PDF'] + ([] if result['settings']['mode']=='native' else ['OpenCV'])
    result.update(counts=counts, processed=pc.get('done', 0)+pc.get('failed', 0), failed=pc.get('failed', 0), photographs=sum(counts.values()))
    completed = pc.get('done', 0)
    result['speed'] = completed / max(result['elapsed'], 0.001)
    result['eta'] = (result['total']-result['processed']) / result['speed'] if completed >= 3 and result['speed'] else None
    result.pop('path')
    return result


def raw_job(job_id: str):
    with connection() as c:
        row = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not row:
        raise KeyError('Document not found')
    return dict(row)


def regions(job_id: str, page: int | None = None):
    with connection() as c:
        rows = c.execute('SELECT data FROM regions WHERE job_id=?' + (' AND page=?' if page else '') + ' ORDER BY page,ordinal,id', (job_id, page) if page else (job_id,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def put_region(c, region):
    c.execute('INSERT OR REPLACE INTO regions VALUES(?,?,?,?,?,?,?)', (region['id'], region['job_id'], region['page'], region['ordinal'], region['status'], int(region.get('manual', False)), json.dumps(region)))


def update_job(job_id: str, **fields):
    allowed = {'status', 'stage', 'error', 'device', 'warnings', 'elapsed', 'engines'}
    assert set(fields) <= allowed
    fields['updated'] = time.time()
    with connection() as c:
        c.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), job_id))
