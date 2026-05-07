"""
DC-EPMS PRO - Infrastructure Diagnostics
==========================================
Runs connectivity checks for PostgreSQL, ChromaDB, LM Studio.
Prints actionable fixes when components fail.

Run:
    python scripts/diagnose.py
"""
import os
import sys
import pathlib
import asyncio

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

def _load_env():
    env_path = PROJECT_ROOT / "config" / ".env"
    if not env_path.exists():
        env_path = PROJECT_ROOT / "config" / ".env.example"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
_load_env()


def hdr(txt): print(f"\n{'='*60}\n  {txt}\n{'='*60}")
def ok(m):    print(f"  [OK]    {m}")
def warn(m):  print(f"  [WARN]  {m}")
def err(m):   print(f"  [ERROR] {m}")
def info(m):  print(f"  [INFO]  {m}")


async def check_postgres():
    hdr("PostgreSQL / TimescaleDB")
    host = os.environ.get("PG_HOST", "localhost")
    port = os.environ.get("PG_PORT", "5432")
    db   = os.environ.get("PG_DB", "epms")
    user = os.environ.get("PG_USER", "postgres")
    pwd  = os.environ.get("PG_PASSWORD", "epms2026")

    info(f"Host:     {host}:{port}")
    info(f"Database: {db}")
    info(f"User:     {user}")

    try:
        import asyncpg
    except ImportError:
        err("asyncpg not installed. Run: pip install asyncpg")
        return False

    dsn = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
    try:
        conn = await asyncpg.connect(dsn=dsn, timeout=5.0)
        version = await conn.fetchval("SELECT version()")
        info(f"Server:   {version[:60]}...")

        # Check TimescaleDB
        try:
            ts = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname='timescaledb'")
            if ts:
                ok(f"TimescaleDB v{ts} active")
            else:
                warn("TimescaleDB extension not installed")
        except Exception as e:
            warn(f"TimescaleDB check failed: {e}")

        # Check tables
        tables = await conn.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        table_names = [t["table_name"] for t in tables]
        if "telemetry" in table_names:
            count = await conn.fetchval("SELECT count(*) FROM telemetry")
            ok(f"Table 'telemetry' exists with {count} rows")
        else:
            warn("Table 'telemetry' does not exist - start backend once to create schema")

        if "incidents" in table_names:
            count = await conn.fetchval("SELECT count(*) FROM incidents")
            ok(f"Table 'incidents' exists with {count} rows")
        else:
            warn("Table 'incidents' does not exist")

        await conn.close()
        ok("PostgreSQL connection: SUCCESS")
        return True
    except asyncpg.InvalidPasswordError:
        err(f"Invalid password for user '{user}'. Check config/.env")
        return False
    except OSError as e:
        err(f"Cannot reach {host}:{port} - {e}")
        info("Fix: Check Docker: docker ps | Select-String epms-db")
        info("     docker start epms-db")
        return False
    except Exception as e:
        err(f"Connection failed: {type(e).__name__}: {e}")
        return False


def check_chromadb():
    hdr("ChromaDB (RAG)")
    chroma_path = PROJECT_ROOT / "data" / "chroma_db"
    info(f"Path: {chroma_path}")

    if not chroma_path.exists():
        warn(f"ChromaDB path does not exist: {chroma_path}")
        info("Fix: python scripts/seed_rag.py")
        return False

    try:
        import chromadb
    except ImportError:
        err("chromadb not installed. Run: pip install chromadb")
        return False

    try:
        client = chromadb.PersistentClient(path=str(chroma_path))
        # Use get_or_create to avoid API version issues
        try:
            coll = client.get_collection("epms_knowledge")
        except Exception:
            warn("Collection 'epms_knowledge' does not exist")
            info("Fix: python scripts/seed_rag.py")
            return False
        count = coll.count()
        info(f"Collection: epms_knowledge")

        if count == 0:
            warn("Collection 'epms_knowledge' is EMPTY")
            info("Fix: python scripts/seed_rag.py")
            return False

        ok(f"ChromaDB has {count} indexed documents")
        return True
    except Exception as e:
        err(f"ChromaDB error: {type(e).__name__}: {e}")
        return False


def check_lm_studio():
    hdr("LM Studio (Gemma 4)")
    url = os.environ.get("LM_STUDIO_URL", "http://127.0.0.1:1234")
    info(f"URL: {url}")

    try:
        import httpx
    except ImportError:
        err("httpx not installed")
        return False

    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{url}/v1/models")
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                ok(f"LM Studio responsive with {len(models)} models")
                for m in models:
                    info(f"  - {m}")
                return True
            else:
                err(f"LM Studio returned HTTP {resp.status_code}")
                return False
    except Exception as e:
        err(f"LM Studio unreachable at {url}: {e}")
        info("Fix: Open LM Studio, load gemma-4-e2b-it, Start Server")
        return False


def check_docker():
    hdr("Docker")
    import subprocess
    try:
        r = subprocess.run(["docker", "ps", "--filter", "name=epms-db", "--format", "{{.Names}} {{.Status}}"],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and "epms-db" in r.stdout:
            ok(f"epms-db container: {r.stdout.strip()}")
            return True
        else:
            warn("epms-db container not running")
            r2 = subprocess.run(["docker", "ps", "-a", "--filter", "name=epms-db", "--format", "{{.Names}} {{.Status}}"],
                              capture_output=True, text=True, timeout=5)
            if "epms-db" in r2.stdout:
                warn(f"Container exists but stopped: {r2.stdout.strip()}")
                info("Fix: docker start epms-db")
            else:
                warn("Container does not exist")
                info("Fix: .\\scripts\\start.ps1 -Install")
            return False
    except FileNotFoundError:
        err("Docker CLI not found")
        return False
    except Exception as e:
        err(f"Docker check failed: {e}")
        return False


async def main():
    print("\nDC-EPMS PRO - Infrastructure Diagnostics\n")
    print(f"Project root: {PROJECT_ROOT}")

    results = {}
    results["docker"]    = check_docker()
    results["postgres"]  = await check_postgres()
    results["chromadb"]  = check_chromadb()
    results["lm_studio"] = check_lm_studio()

    hdr("SUMMARY")
    for k, v in results.items():
        status = "OK   " if v else "FAIL "
        print(f"  [{status}] {k}")

    failed = [k for k, v in results.items() if not v]
    if failed:
        print(f"\n  Issues: {len(failed)}/{len(results)} components down")
        return 1
    print(f"\n  All systems operational")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
