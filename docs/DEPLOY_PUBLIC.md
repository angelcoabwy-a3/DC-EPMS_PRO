# Public deployment (release R1)

How to run DC-EPMS PRO on a public URL for testing: full dashboard,
mandatory login, no PostgreSQL, no RAG, no local LLM. Verified
2026-11-13 on a clean Linux virtualenv (Python 3.13); the Render
dashboard settings themselves were NOT inspected, so check them
against this page.

All facility data is simulated. This is a test deployment, not a
production control system.

## 1. Build and start commands

| Setting | Value |
|---|---|
| Build command | `pip install -r requirements-minimal.txt` |
| Start command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/api/health` |
| Python | 3.12 (see `.python-version`) |

`requirements-minimal.txt` is CPU-only and torch-free (about 250 MB
installed). Do not use `requirements.txt` on a small instance: it
pulls sentence-transformers and torch.

## 2. Environment variables

Required for a public URL:

| Variable | Value | Why |
|---|---|---|
| `DC_EPMS_REQUIRE_AUTH` | `1` | Turns on the session gate: every API route, the SSE stream and the WebSocket need a login. Without it the login form is cosmetic. |
| `DC_EPMS_JWT_SECRET` | 32+ random characters | Signs sessions. If unset, a new secret is generated at each boot and every restart logs everyone out. |
| `DC_EPMS_PWD_MANAGER` | a private passphrase | Password of user `manager` (FACILITY_MANAGER). |

Optional users. On a gated deployment a user with no password
variable is NOT created, because the default passwords are published
in this repository:

| Variable | User | Role |
|---|---|---|
| `DC_EPMS_PWD_OPERATOR` | `operator` | L1_OPERATOR |
| `DC_EPMS_PWD_TECHNICIAN` | `technician` | L2_TECHNICIAN |
| `DC_EPMS_PWD_SAFETY_A` | `safety_a` | SAFETY_OFFICER |
| `DC_EPMS_PWD_SAFETY_B` | `safety_b` | SAFETY_OFFICER (second signer, Maker-Checker) |

Recommended:

| Variable | Value | Why |
|---|---|---|
| `DC_EPMS_LEDGER_HMAC_KEY` | **hex** string, at least 64 hex digits (32 bytes) | Otherwise ledger entries cannot be verified after a restart. A non-hex or shorter value makes the ledger fail to start. |

Already-existing variables that keep their meaning: `META_API_KEY`
(MOP Verification), `DC_EPMS_OPTIMIZER_ENABLED`, `DC_EPMS_USE_SIMULATOR`.

Optional: `DC_EPMS_SKIP_WARMUP=1` skips the GraphRAG and LOTO warmup at
boot (DC-EPMS-069). On a host without the embedding stack it only saves
a failed import; on AMD + Windows it avoids a native crash in pyarrow.

Do NOT set `DC_EPMS_SITE_MODEL` on the public host. Unset means the
legacy model; `v2` is a migration preview (DC-EPMS-068) and several
views still use the retired ids. Any value other than `legacy` or `v2`
stops the site routes from mounting (fail closed). `GET
/api/site/model` reports which model the process runs on.

Generate the values locally. The ledger key MUST be hex; the JWT
secret and the passwords can be any private string:

```
python -c "import secrets; print(secrets.token_hex(32))"       # DC_EPMS_LEDGER_HMAC_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"   # DC_EPMS_JWT_SECRET
```

Set secrets in the hosting dashboard. Never commit them.

## 3. What stays public without a login

`/`, `/favicon.ico`, `/assets/*`, `/api/health`, `/api/auth/login`
and `/api/copilot/mop/*`.

The last one is the Meta-hackathon MOP Verification demo. It keeps
its own limits (10 Meta-backed requests per visitor per hour, 50 per
day in total). The hackathon view is still reachable without a login
at:

```
https://<your-host>/?demo=1
```

`frontend/assets/demo_config.json` now ships `demo_mode: false`, so
the bare URL shows the full application behind the login.

## 4. What "no database" means

| Surface | Behaviour |
|---|---|
| CMMS (Maintenance, Rack Heatmap, Mission Control) | In-memory. 113 assets seeded from `config/site_model.yml`. Work orders are lost on restart. The Maintenance view shows an IN-MEMORY badge. |
| Overview KPI cards | Derived from the in-process simulator and the Phase 1 PUE model, labelled on the page. |
| Forensic ledger | In-memory. Entries are lost on restart. |
| Incidents | Empty (they are stored in PostgreSQL only). |
| RAG / Tech Assist library / Co-Pilot LLM answers | Not available. The views say so. |
| Sessions | 1 hour. After expiry, reload the page and sign in again. |

Set `DC_EPMS_CMMS_FALLBACK=off` to get the old behaviour (CMMS
routes not mounted without PostgreSQL).

## 5. Smoke test after each deploy

```
curl -s https://<host>/api/health                 # 200, version
curl -s -o /dev/null -w "%{http_code}\n" https://<host>/api/site/components   # 401
curl -s -o /dev/null -w "%{http_code}\n" https://<host>/lm/v1/models          # 401
```

Then in a browser: sign in as `manager`, open Overview, Power & UPS,
Maintenance, Optimizer, Procedure Architect, Mission Control and
OT Security. On a correctly configured host the OT Security view
shows OT-AUTH-01, -02, -03 and OT-AUD-02 as PASS; if any of them
fails, an environment variable from section 2 is missing. Open
`/?demo=1` in a private window and confirm MOP Verification loads
without a login.

## 6. Known limits of this release

- Sessions are not refreshed; there is no sign-out button.
- The JWT is also kept in `localStorage` (Epic 10 design), so the
  XSS discipline of S-SEC-01 remains the mitigation.
- Per-IP limits rely on `X-Forwarded-For` from the hosting proxy.
- The ANOMALIES (60M) counter saturates on a healthy plant
  (DC-EPMS-043, open).
