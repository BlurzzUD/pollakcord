# PollákCord

A Discord-style communication platform built for one school. Students prove they belong to the school through **E-Kréta**, then get a private platform account (username, display name, profile, friends, direct messages, servers with channels and roles, voice, moderation) without their real name ever becoming public.

- Default language **Hungarian**, plus **English** and **German** (whole UI, errors, validation, tooltips, accessibility labels).
- Original branding: a squared school notebook (cool paper, faint blue grid, red margin line) with a chalkboard dark theme. No third-party chat-platform assets.
- The source code contains **no comments** (enforced by tests). This README is the documentation.
- The supplied E-Kréta login script is used **exactly as provided**. It is never edited, rewritten or replaced (see [section 9](#9-e-kréta-integration-setup)).

## Table of contents

1. [Project overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Technology stack](#3-technology-stack)
4. [Requirements](#4-requirements)
5. [Installation](#5-installation)
6. [Environment variables](#6-environment-variables)
7. [Database setup](#7-database-setup)
8. [Database migrations](#8-database-migrations)
9. [E-Kréta integration setup](#9-e-kréta-integration-setup)
10. [How to provide the supplied authentication script](#10-how-to-provide-the-supplied-authentication-script)
11. [Development commands](#11-development-commands)
12. [Production deployment](#12-production-deployment)
13. [HTTPS configuration](#13-https-configuration)
14. [WebSocket configuration](#14-websocket-configuration)
15. [WebRTC configuration](#15-webrtc-configuration)
16. [TOTP configuration](#16-totp-configuration)
17. [Internationalization](#17-internationalization)
18. [Theme customization](#18-theme-customization)
19. [Custom CSS security](#19-custom-css-security)
20. [Moderation system](#20-moderation-system)
21. [Encryption architecture](#21-encryption-architecture)
22. [Backup considerations](#22-backup-considerations)
23. [Security considerations](#23-security-considerations)
24. [Testing](#24-testing)
25. [Troubleshooting](#25-troubleshooting)

---

## 1. Project overview

### What users get

| Area | Features |
| --- | --- |
| Registration | E-Kréta verification (with E-Kréta 2FA if requested) → "Te vagy *Teljes Név*?" (Igen/Nem) → username + display name → password **or** TOTP → one-time recovery codes → "Szeretnéd megjeleníteni az osztályodat a profilodon?" |
| Login | Username, then password or TOTP code depending on the account. E-Kréta credentials are **not** needed again. Greeting: "Üdv, *név*!" / "Hello, *name*!" / "Hallo, *Name*!" |
| Profiles | Avatar, banner, display name, username, bio, join date, class (only if the user chose to show it), presence, mutual friends, shared servers, user ID (developer mode) |
| Friends | Requests, accept/decline/cancel, remove, block, presence per privacy, class-based suggestions (only between users who both opted in) |
| Direct messages | Text, replies, reactions, delete own, timestamps, read/unread, report, block, voice calls |
| Servers | Create/join/leave, invites (`/invite/<code>`), categories, text and voice channels, roles (Owner, Administrator, Moderator, Member + custom), 18 permissions, per-category and per-channel overwrites, pins, slowmode, timeouts, kick/ban, audit log, server reports |
| Voice | WebRTC peer-to-peer mesh, end-to-end encrypted (DTLS-SRTP), speaking indicators, mute/deafen, server-side mute/deafen requests, DM calls with ringing, call security code |
| Search | Friends, users, servers, channels and messages (permission-filtered, accent-insensitive whole-word message search over encrypted data) |
| Privacy | Friend requests, DMs, class visibility, online status, profile visibility, activity visibility, voice calls, all with privacy-preserving defaults |
| Customization | Light, dark, system and custom themes, chat density/font size/timestamps, sandboxed custom CSS |
| Moderation | Reports with encrypted snapshots, school moderators/admins, audited identity reveal, account suspension, audit logs |
| Developer mode | Shows user/server/channel/message IDs with copy buttons (never secrets) |

### Privacy of the real name

The full name that E-Kréta returns is **identity information**:

- stored encrypted (AES-256-GCM) in its own table, separate from profiles;
- never returned by any normal API response, never in URLs, never in `localStorage`, never in developer mode, not searchable;
- visible only to school moderators/admins through an explicit, reasoned and audited action (see [section 20](#20-moderation-system));
- the E-Kréta username is **not stored**; only a keyed HMAC of it is kept to stop one person registering twice;
- the text in parentheses that E-Kréta appends to the name (a guardian's name in the sample) is discarded by the adapter and never stored.

### Honest scope

Things deliberately **not** claimed or not built are listed in [section 23](#known-limitations). The most important: ordinary text messages are **encrypted at rest, not end-to-end encrypted** (the server must be able to decrypt reported messages), while voice **is** end-to-end encrypted.

---

## 2. Architecture

### Plan in one screen

1. **Python backend (FastAPI)** because the supplied E-Kréta script is Python; it runs in an isolated subprocess per attempt behind an adapter.
2. **React SPA** served by the same process in production (or by a reverse proxy).
3. **REST** under `/api/v1` for state changes and reads, **one WebSocket** (`/api/v1/ws`) for push events, typing, presence and WebRTC signaling.
4. **Server-side authorization everywhere**: one permission engine used by REST and WebSocket handlers; the frontend only hides things.
5. **Envelope encryption** for message bodies, identity, TOTP secrets and report snapshots; keys derived from a master key that lives outside the database.
6. **Browser-to-browser audio** (WebRTC mesh), signaling relayed only between members of the same room.

### Diagram

```
 Browser (React SPA)
   │  HTTPS  REST  /api/v1/*        cookies: __Host-pc_session (HttpOnly), __Host-pc_csrf
   │  WSS    /api/v1/ws             same cookie + Origin check
   │  WebRTC audio (DTLS-SRTP) ◄──────────────► other browsers  (TURN relay only if needed)
   ▼
 Reverse proxy (Caddy)  ──►  uvicorn (single process)
                              ├─ middleware: request id, CSRF + Origin, security headers, JSON logs
                              ├─ routers: auth, me, users, friends, dms, servers, channels, invites,
                              │           search, notifications, uploads, rtc, moderation, meta
                              ├─ services: permissions, privacy, messages (crypto), servers, uploads,
                              │            css_sanitizer, notifications, audit
                              ├─ realtime: hub (topics), voice rooms, calls, outbox (post-commit events)
                              ├─ crypto: keyring (HKDF), AES-GCM vault, blind index
                              └─ integrations/kreta: adapter ─► subprocess ─► supplied script (unmodified)
                                                                           └─► E-Kréta
                              PostgreSQL (SQLite for dev/tests)      uploads on disk
```

### Registration flow (server side)

```
POST /auth/kreta/start        adapter spawns the script, feeds username+password on stdin, waits for
                              either the 2FA prompt or the final result. Credentials are dropped.
POST /auth/kreta/two-factor   (only if requested) code is written to the same live process
POST /auth/kreta/confirm      {confirmed: true|false}; "false" kills the flow and forgets the name
POST /auth/register           username + display name; real name encrypted; account = pending_security;
                              a short-lived "setup" session cookie is issued
POST /auth/security/password  or  /auth/security/totp/begin + /confirm   → account becomes active,
                              recovery codes are returned once, all sessions rotate
PUT  /me/class                optional class + visibility
```

The verified name lives only in server memory (flow store, 15 minute TTL) until registration consumes it. The browser holds it in React state for the confirmation screen only.

### Repository layout

```
pollakcord/
├── README.md
├── Dockerfile  docker-compose.yml  .env.example  .dockerignore  .gitignore
├── deploy/Caddyfile
├── backend/
│   ├── alembic.ini  pytest.ini  requirements.txt  requirements-dev.txt
│   ├── docker/entrypoint.sh
│   ├── migrations/                 env.py, script.py.mako, versions/0001_initial_schema.py
│   ├── app/
│   │   ├── main.py  config.py  cli.py  seed.py  spa.py  ids.py  i18n.py  errors.py  logging_config.py
│   │   ├── locales/                hu.json  en.json  de.json     (API error messages, server defaults)
│   │   ├── api/                    deps.py, v1/{auth,me,users,friends,dms,servers,channels,invites,
│   │   │                           search,notifications,uploads,rtc,moderation,meta,messaging,router}.py
│   │   ├── crypto/                 keyring.py  envelope.py  blind_index.py
│   │   ├── db/                     base.py  session.py  types.py
│   │   ├── integrations/kreta/     adapter.py  flows.py  script.sha256  script/kreta_login_from_dumps.py
│   │   ├── models/                 users, auth, social, servers, messages, audit/notifications, enums
│   │   ├── realtime/               hub.py  voice.py  ws.py  outbox.py
│   │   ├── security/               passwords  totp  recovery  sessions  middleware  ratelimit  deps_ip  audit_helpers
│   │   └── services/               permissions  privacy  messages  servers  accounts  people
│   │                               notifications  uploads  css_sanitizer  audit  serializers
│   └── tests/                      ~250 tests, incl. tests/kreta_fake/ (HTTP stand-in for E-Kréta)
└── frontend/
    ├── index.html  vite.config.ts  tsconfig.json  package.json  public/favicon.svg
    ├── scripts/check-no-comments.mjs
    └── src/
        ├── api/        client (CSRF, errors, language header), types, hooks
        ├── components/ Avatar, Modal, Field, Toasts, chat/*, layout/*
        ├── i18n/       index.ts, locales/{hu,en,de}.json
        ├── pages/      auth/*, settings/*, server/*, Home, Friends, Dm, Invite, Moderation
        ├── realtime/   socket.ts (reconnect, resubscribe), useRealtimeEvent.ts
        ├── store/      auth, ui, live (zustand)
        ├── styles/     tokens, base, layout, components, chat, pages (.css)
        ├── theme/      ThemeProvider, tokens
        ├── voice/      VoiceManager (WebRTC mesh), useVoice, securityCode
        └── test/       vitest suites
```

---

## 3. Technology stack

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, uvicorn | The supplied script is Python; async I/O and native WebSockets |
| ORM / migrations | SQLAlchemy 2 (async), Alembic | Typed models, versioned schema |
| Database | PostgreSQL 16 (production), SQLite (development/tests) | Relational model with constraints |
| Passwords | Argon2id (`argon2-cffi`) | Memory-hard hashing |
| TOTP | `pyotp`, QR via `segno` (SVG) | RFC 6238, no external QR service |
| Crypto | `cryptography` (AES-256-GCM, HKDF-SHA256, HMAC-SHA256) | Authenticated encryption, key separation |
| Uploads | Pillow | Decode, validate, re-encode to WebP |
| CSS sandbox | `tinycss2` | Real CSS parser, allowlist re-serialization |
| Frontend | React 18, TypeScript 5.9, Vite, React Router 6, TanStack Query 5, Zustand 5 | Small, typed, fast |
| i18n | i18next + react-i18next (frontend), JSON catalogs (backend) | Hungarian default, plural forms |
| Fonts | Bricolage Grotesque (display), Atkinson Hyperlegible (body), self-hosted via Fontsource | Distinct identity, legibility, no third-party font requests |
| Voice | Browser WebRTC (mesh), coturn for TURN | End-to-end DTLS-SRTP |
| Deployment | Docker Compose, Caddy (automatic HTTPS) | Simple, repeatable |

---

## 4. Requirements

| Need | Version |
| --- | --- |
| Python | 3.12 recommended (the supplied script needs **3.10+**) |
| Python packages | `backend/requirements.txt` (includes `requests`, needed by the E-Kréta script) |
| Node.js | 20 or newer (22 used for the build image) |
| PostgreSQL | 16 for production (SQLite is fine for development) |
| Docker + Compose | Optional but recommended for production |
| TURN server | coturn, recommended for reliable voice across school and mobile networks |
| Browser | Current Chrome, Edge, Firefox, Safari. Microphone access requires HTTPS (or `localhost`) |

---

## 5. Installation

### Quick start (development)

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
printf 'POLLAKCORD_ENVIRONMENT=development\nPOLLAKCORD_PUBLIC_ORIGIN=http://localhost:5173\nPOLLAKCORD_COOKIE_SECURE=false\n' > .env
alembic upgrade head
uvicorn app.main:build_default_app --factory --reload --port 8000 --ws-max-size 65536
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` (including WebSocket) and `/media` to port 8000.

In development, missing encryption keys are generated into `backend/data/dev-secrets.json` (mode `0600`). Production refuses to start without real keys.

The bundled E-Kréta script is already in place (`backend/app/integrations/kreta/script/`). Registration in development talks to the **real** E-Kréta, so use real credentials or follow [section 24](#24-testing) to see how the tests stand in for E-Kréta.

### Production

See [section 12](#12-production-deployment) (Docker Compose, about five commands).

---

## 6. Environment variables

All variables use the prefix `POLLAKCORD_`. They can be set in the environment or in `backend/.env`. In Docker Compose they come from the project-root `.env` (copy `.env.example`).

### Core

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development`, `production` or `test`. Production requires keys and hides API docs, enables HSTS |
| `PUBLIC_ORIGIN` | `http://localhost:5173` | The exact browser origin (scheme + host + port). Used for CSRF/WebSocket Origin checks and the CSP `connect-src` |
| `EXTRA_ORIGINS` | empty | Comma-separated additional allowed origins |
| `COOKIE_SECURE` | `true` | Must be `true` behind HTTPS. Switches cookie names to the `__Host-` prefix. Set `false` only for plain-HTTP development |
| `TRUSTED_PROXY_HOPS` | `0` | Number of reverse proxies in front (Caddy = `1`). Only then is `X-Forwarded-For` honored for rate limiting |
| `APP_NAME` | `PollákCord` | Shown in the TOTP issuer |
| `LOG_LEVEL` | `INFO` | JSON logs to stdout |
| `SERVE_FRONTEND` | `true` | Serve the built SPA from `FRONTEND_DIST` |
| `FRONTEND_DIST` | `<repo>/frontend/dist` | Built SPA location |

### Database

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/pollakcord.db` | Production: `postgresql+asyncpg://user:password@host:5432/pollakcord` |
| `DATABASE_POOL_SIZE` | `10` | Connection pool size (non-SQLite) |
| `AUTO_CREATE_SCHEMA` | `false` | Creates tables at startup. For tests only; use Alembic otherwise |

### Secrets and keys

| Variable | Default | Meaning |
| --- | --- | --- |
| `MASTER_KEY` | none | 32 random bytes, URL-safe base64. Root of all encryption. **Required in production** |
| `MASTER_KEY_FILE` | none | Read the master key from a file (Docker/Kubernetes secrets) |
| `MASTER_KEY_ID` | `k1` | Identifier stored next to ciphertext, enabling rotation |
| `PREVIOUS_MASTER_KEYS` | none | Retired keys still needed for decryption: `k1:<key>,k0:<key>` |
| `PEPPER` / `PEPPER_FILE` | none | Separate 32-byte secret for keyed hashes (identity hash, recovery codes, search index). **Required in production** |

Generate a key: `python -m app generate-key` (from `backend/`).

### Authentication and sessions

| Variable | Default | Meaning |
| --- | --- | --- |
| `SESSION_TTL_HOURS` | `336` | Absolute session lifetime (14 days) |
| `SESSION_IDLE_HOURS` | `120` | Idle expiry (5 days) |
| `SETUP_SESSION_TTL_MINUTES` | `30` | Lifetime of the registration/recovery "setup" session |
| `ARGON2_TIME_COST` / `ARGON2_MEMORY_KIB` / `ARGON2_PARALLELISM` | `3` / `65536` / `2` | Argon2id parameters |
| `LOCKOUT_THRESHOLD` | `5` | Failures before progressive lockout |
| `LOCKOUT_BASE_SECONDS` / `LOCKOUT_MAX_SECONDS` | `30` / `900` | Lockout doubles from base up to max |
| `RATE_LIMIT_ENABLED` | `true` | Master switch for the in-memory rate limiter |

### E-Kréta integration

| Variable | Default | Meaning |
| --- | --- | --- |
| `KRETA_SCRIPT_PATH` | bundled copy | Path to the supplied script |
| `KRETA_SCRIPT_SHA256` | unset | **Pin** the script digest. The app refuses to start if the file differs |
| `KRETA_PYTHON` | current interpreter | Interpreter used to run the script (needs `requests`, Python 3.10+) |
| `KRETA_FLOW_TTL_SECONDS` | `180` | How long a login waits for the 2FA code |
| `KRETA_PROCESS_TIMEOUT_SECONDS` | `75` | Hard limit for one script run |
| `KRETA_MAX_CONCURRENT` | `6` | Maximum simultaneous live script processes |
| `KRETA_IDENTITY_NAMESPACE` | `kreta` | Mixed into the identity hash. Do not change after launch |

### Messaging, uploads, realtime

| Variable | Default | Meaning |
| --- | --- | --- |
| `MESSAGE_MAX_LENGTH` | `4000` | Characters per message |
| `DATA_KEY_ROTATION_MESSAGES` | `500000` | New data key per conversation/channel after this many messages |
| `UPLOAD_DIR` | `<backend>/data/uploads` | Image storage |
| `AVATAR_MAX_BYTES` / `BANNER_MAX_BYTES` / `ICON_MAX_BYTES` | 2 MiB / 6 MiB / 2 MiB | Upload size limits |
| `MAX_IMAGE_PIXELS` | `25000000` | Decompression-bomb guard |
| `WS_MAX_CONNECTIONS_PER_USER` | `6` | Open sockets per user (tabs/devices) |
| `VOICE_MAX_PARTICIPANTS` | `8` | Mesh size cap per voice room |
| `CALL_RING_SECONDS` | `45` | Ring time before a DM call counts as missed |
| `STUN_URLS` | `stun:stun.l.google.com:19302` | Comma-separated STUN servers |
| `TURN_URLS` / `TURN_SECRET` / `TURN_TTL_SECONDS` | empty / none / `3600` | coturn REST credentials (`use-auth-secret`) |

### Compose-only

`POSTGRES_PASSWORD`, `POLLAKCORD_DOMAIN` (public host name for Caddy and coturn).

---

## 7. Database setup

**Development:** nothing to do. The default SQLite file is created under `backend/data/`.

**Production (PostgreSQL):**

```sql
CREATE USER pollakcord WITH PASSWORD 'change-me';
CREATE DATABASE pollakcord OWNER pollakcord ENCODING 'UTF8';
```

Set `POLLAKCORD_DATABASE_URL=postgresql+asyncpg://pollakcord:change-me@db-host:5432/pollakcord`, then run the migrations ([section 8](#8-database-migrations)). Docker Compose does all of this for you.

### Schema overview (33 tables)

| Group | Tables |
| --- | --- |
| Accounts | `users`, `user_identities` (encrypted real name + identity hash), `profiles`, `user_settings`, `themes`, `school_classes` |
| Authentication | `auth_methods` (password hash, lockout counters), `totp_configs` (encrypted secret), `recovery_codes` (hashed), `sessions` (hashed tokens) |
| Social | `friendships`, `friend_requests`, `blocks` |
| Servers | `servers`, `roles`, `server_members`, `member_roles`, `categories`, `channels`, `permission_overwrites`, `invites`, `bans` |
| Messaging | `conversations`, `data_keys`, `messages` (metadata), `message_contents` (ciphertext), `message_reactions`, `read_states`, `message_mentions`, `message_search_tokens` |
| Moderation | `reports` (encrypted snapshots), `audit_logs`, `notifications` |

IDs are time-ordered 63-bit snowflakes, returned to clients as strings. Invite codes are 10 random base-62 characters (about 60 bits).

---

## 8. Database migrations

```bash
cd backend
alembic upgrade head        # apply
alembic downgrade base      # revert everything (destroys data)
alembic revision --autogenerate -m "describe change"
alembic current
```

- `migrations/versions/0001_initial_schema.py` creates every table and **seeds the 12 classes**: 9A, 9B, 10A, 10B, 11A, 11B, 12A, 12B, 13A, 13B, 14A, 14B.
- A test asserts that the migrated schema is exactly what the models describe.

### Changing the classes later

Classes are rows in `school_classes` (`code`, `grade`, `section`, `sort_order`, `is_active`). To add one:

```sql
INSERT INTO school_classes (id, code, grade, section, sort_order, is_active)
VALUES (2000, '9C', 9, 'C', 12, true);
```

Set `is_active = false` to retire a class without losing the users who chose it. `python -m app seed` re-adds any of the default classes that are missing.

---

## 9. E-Kréta integration setup

### How the adapter treats the supplied script

The script is an interactive command-line program: it reads the E-Kréta username, the password and (only if asked) the TOTP code from stdin, prints a long log, and ends with the student's name. It also keeps a module-level `requests.Session`, prints the password it was given, prints parts of cookies, writes debug HTML to its working directory and calls `sys.exit`. None of that is safe to call from inside a multi-user server, and none of it may be edited. So `integrations/kreta/adapter.py` **wraps it from the outside**:

| Concern | What the adapter does |
| --- | --- |
| Isolation | One **new subprocess per login attempt**, own `requests.Session`, own process group, killed on timeout/abort |
| Working directory | A fresh temp directory per attempt, deleted afterwards (the script's debug HTML files land there) |
| Environment | Scrubbed: the child gets `PATH`, UTF-8 settings and proxy/CA variables only. It never sees `MASTER_KEY`, `PEPPER`, database URLs or any other secret |
| Resource limits | Launcher applies CPU (60 s), file size (2 MiB), core dump (0) and address space (1 GiB) limits, then `exec`s the script |
| Credentials | Sent only through stdin pipes (not argv, not env), rejected if they contain control characters or newlines (prevents stdin injection) |
| Output | Read into a bounded in-memory buffer (256 KiB), **never logged, never stored, never returned**. Only a tiny result object (`outcome`, `full_name`) leaves the adapter |
| Result parsing | Accepts the name only if the process exited with code 0 **and** the name line appears after the script's `=== Done ===` marker, so forged lines in earlier output are ignored |
| Name hygiene | Parenthetical suffix removed; only letters, marks, spaces and `.,'’-` allowed; 2–120 characters |
| Identity key | `HMAC-SHA256(pepper-derived key, "kreta\|<username lowercased>")` is stored (unique) to prevent duplicate registrations. The username itself is not stored |

### Outcomes and user-facing errors

| Script behaviour (detected from its own output) | Outcome | HTTP | Error code |
| --- | --- | --- | --- |
| Asks for the TOTP code (`enter current TOTP`) | `two_factor_required` | 200 | none |
| Prints the student name after `=== Done ===` | `identified` | 200 | none |
| `password login likely failed` | `invalid_credentials` | 401 | `kreta_invalid_credentials` |
| `code may be wrong/expired` | `invalid_two_factor` | 401 | `kreta_invalid_two_factor` |
| `EXPIRED LICENSE` page, timeout, crash | `service_unavailable` / `failed` | 503 / 502 | `kreta_unavailable` / `kreta_failed` |
| Too many live processes | n/a | 503 | `kreta_busy` |

A wrong 2FA code ends the script, so the user restarts the login (the UI says so).

### Flow state

Live flows are held **in process memory**, keyed by the SHA-256 of a random token kept in an HttpOnly `Strict` cookie. A flow expires after 180 s while waiting for 2FA and 15 minutes after identification. Answering "Nem" or cancelling kills the process and wipes the name. This is why the app must run as **one process** (see [section 12](#12-production-deployment)).

### Rate limits around E-Kréta

8 starts per IP and 6 per E-Kréta identity per 10 minutes, 10 two-factor attempts per 10 minutes, at most `KRETA_MAX_CONCURRENT` live processes.

### Account recovery uses the same integration

If someone loses their password/device, they can re-verify through E-Kréta (same flow, `intent: recover`), which opens a short "setup" session to choose new credentials and revokes all other sessions. Alternatively they can use one of their recovery codes.

### Authorization and data protection note

You stated you are authorized to use this integration for the school. Before launch it is still worth confirming in writing with the school and the E-Kréta operator that students may be asked to type E-Kréta credentials into this site. Asking for school credentials on any third-party site trains users to do the same on look-alike sites; host this only on school-controlled infrastructure, keep the pinned script digest enabled, and prefer an official SSO/OAuth integration if one becomes available. Minors' data is involved, so also review GDPR duties (see [known limitations](#known-limitations)).

---

## 10. How to provide the supplied authentication script

The project already contains your file, **byte-for-byte**, at:

```
backend/app/integrations/kreta/script/kreta_login_from_dumps.py
```

(its digest is recorded in `backend/app/integrations/kreta/script.sha256`).

To use a different copy, or after you receive an updated script:

1. Copy it to any path readable by the app, e.g. `/etc/pollakcord/kreta_login_from_dumps.py`.
2. Compute its digest: `sha256sum /etc/pollakcord/kreta_login_from_dumps.py`.
3. Set `POLLAKCORD_KRETA_SCRIPT_PATH` and `POLLAKCORD_KRETA_SCRIPT_SHA256` to the path and digest.
4. Make sure the interpreter has `requests` (`pip install requests`) and is Python 3.10+; set `POLLAKCORD_KRETA_PYTHON` if it is a different interpreter.
5. Restart. On startup the app verifies the digest and refuses to run the integration on a mismatch.

The adapter depends on these strings printed by the script (it never changes them): the prompt text `enter current TOTP`, `=== Done ===`, `Student name returned by API: `, `password login likely failed`, `code may be wrong/expired`, `EXPIRED LICENSE`. A test fails if an updated script stops printing any of them, so a breaking change is caught before deployment.

The script has the institute code `hszc-pollak` hard-coded and mimics a browser session. If E-Kréta changes its web login, the script (not this project) must be updated.

---

## 11. Development commands

### Backend (run from `backend/`)

| Command | Purpose |
| --- | --- |
| `pip install -r requirements-dev.txt` | Install runtime + test dependencies |
| `alembic upgrade head` | Create/upgrade the schema |
| `uvicorn app.main:build_default_app --factory --reload --port 8000 --ws-max-size 65536` | Run the API |
| `python -m app generate-key` | Print a new random key (for `MASTER_KEY` / `PEPPER`) |
| `python -m app seed` | Ensure the default classes exist |
| `python -m app grant-role <username> <role>` | Set a platform role: `user`, `school_moderator`, `school_admin` |
| `pytest` | Run the backend test suite |

Interactive API docs (not in production): <http://localhost:8000/api/docs>.

### Frontend (run from `frontend/`)

| Command | Purpose |
| --- | --- |
| `npm install` | Install dependencies |
| `npm run dev` | Dev server on port 5173 (proxy to the API) |
| `npm run build` | Type-check and produce `dist/` |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest suite |
| `npm run check:comments` | Fail if any source file contains a comment |

Set `POLLAKCORD_BACKEND=http://host:port` to point the dev proxy elsewhere.

### First moderator

Register normally, then promote the account:

```bash
python -m app grant-role your_username school_admin
```

---

## 12. Production deployment

### Docker Compose (recommended)

```bash
cp .env.example .env
python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))"
```

Run the last command three times and paste the values into `.env` as `POLLAKCORD_MASTER_KEY`, `POLLAKCORD_PEPPER` and `POLLAKCORD_TURN_SECRET`. Also set `POSTGRES_PASSWORD`, `POLLAKCORD_DOMAIN` and `POLLAKCORD_PUBLIC_ORIGIN` (for example `https://chat.example.hu`). Point the DNS name at the server, open ports 80 and 443, then:

```bash
docker compose up -d --build
docker compose --profile turn up -d
docker compose exec api python -m app grant-role your_username school_admin
```

What starts:

| Service | Role |
| --- | --- |
| `db` | PostgreSQL 16 with a persistent volume |
| `api` | Builds the SPA, runs `alembic upgrade head`, then uvicorn (non-root user, health check) |
| `caddy` | TLS (automatic certificates), compression, reverse proxy incl. WebSockets |
| `coturn` | Optional TURN server (`--profile turn`), host networking, relay ports 49160-49200/UDP |

### Without Docker

```bash
cd frontend && npm ci && npm run build
cd ../backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export POLLAKCORD_ENVIRONMENT=production POLLAKCORD_DATABASE_URL=... POLLAKCORD_MASTER_KEY=... POLLAKCORD_PEPPER=... POLLAKCORD_PUBLIC_ORIGIN=https://chat.example.hu POLLAKCORD_TRUSTED_PROXY_HOPS=1
alembic upgrade head
uvicorn app.main:build_default_app --factory --host 127.0.0.1 --port 8000 --ws-max-size 65536 --workers 1
```

Run it under systemd and put a TLS-terminating reverse proxy in front.

### Run exactly one worker

The WebSocket hub, voice rooms, E-Kréta flow store and rate limiter live in process memory. Use a single uvicorn process (it handles many concurrent connections). Running several workers or replicas would split users across separate hubs, and a registration could land on a worker that does not hold its login flow. Horizontal scaling would need a shared pub/sub and flow store (not included).

### Pre-launch checklist

- [ ] `ENVIRONMENT=production`, real `MASTER_KEY` and `PEPPER` stored outside the repository.
- [ ] `KRETA_SCRIPT_SHA256` pinned.
- [ ] HTTPS working, `COOKIE_SECURE=true`, `PUBLIC_ORIGIN` matches the address in the browser.
- [ ] `TRUSTED_PROXY_HOPS` equals the number of proxies in front.
- [ ] TURN configured and tested from a mobile network.
- [ ] First `school_admin` created, moderation policy agreed with the school.
- [ ] Backups of database, uploads **and keys** scheduled ([section 22](#22-backup-considerations)).

---

## 13. HTTPS configuration

Everything security-relevant assumes HTTPS: cookies are `Secure`, `__Host-` prefixed (so they cannot be set from sibling sub-domains), and microphone access requires a secure context.

**Caddy (included, `deploy/Caddyfile`)** obtains and renews certificates automatically:

```
{$POLLAKCORD_DOMAIN} {
	encode zstd gzip
	header -Server
	reverse_proxy api:8000
}
```

**nginx alternative:**

```nginx
server {
    listen 443 ssl http2;
    server_name chat.example.hu;
    ssl_certificate     /etc/letsencrypt/live/chat.example.hu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/chat.example.hu/privkey.pem;
    client_max_body_size 8m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    location /api/v1/ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

Headers the app itself sends in production: `Strict-Transport-Security`, a strict `Content-Security-Policy` (`script-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`, `connect-src 'self'` plus the exact `wss://` origin), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Permissions-Policy` (microphone for self only), `Cache-Control: no-store` on API responses.

Do not enable HTTP compression for API responses that mix secrets with attacker-controlled input at the proxy level unless you understand BREACH; the included Caddy configuration compresses static assets and JSON, which is acceptable here because CSRF tokens are rotated per browser and responses carry no reflected user input.

---

## 14. WebSocket configuration

- Endpoint: `wss://<host>/api/v1/ws`. Authentication uses the same HttpOnly session cookie; the `Origin` header must match `PUBLIC_ORIGIN`/`EXTRA_ORIGINS`.
- The proxy must pass `Upgrade`/`Connection` headers (Caddy does automatically; see the nginx block above).
- Start uvicorn with `--ws-max-size 65536` (the included entrypoint does).
- Limits: frame size 32 768 characters, 80 frames per 10 s, `WS_MAX_CONNECTIONS_PER_USER` sockets per user, 60 channel subscriptions per socket.
- Heartbeat: the client pings every 25 s; the server closes idle sockets after 75 s and re-validates the session every 60 s.
- Close codes: `4401` not authenticated / session ended / bad origin, `4408` idle timeout, `4413` frame too large, `4429` rate or connection limit.
- Authorization: a client may subscribe only to channels it can read. Permission, role, membership or ban changes drop live subscriptions and eject people from voice immediately.

Client operations: `ping`, `subscribe`, `unsubscribe`, `typing`, `voice.join`, `voice.leave`, `voice.signal`, `voice.state`, `voice.moderate`, `call.invite`, `call.accept`, `call.decline`, `call.cancel`.

Server events (envelope `{ "t": <event>, "d": <data> }`): `ready`, `message.create`, `message.delete`, `reaction.update`, `message.pin`, `typing`, `presence.update`, `friend.request|added|removed`, `notification.create`, `server.joined|removed|updated`, `structure.changed`, `member.joined|left|updated`, `role.changed`, `channel.activity`, `read.update`, `voice.*`, `call.*`, `error`.

Events are published only after the database transaction commits.

---

## 15. WebRTC configuration

### Topology and encryption

Voice uses a **full mesh**: every participant has a direct `RTCPeerConnection` to every other participant. Audio is protected by DTLS-SRTP between the browsers, so the server never sees or records audio. That is genuine end-to-end encryption. The server only relays signaling (offers, answers, ICE candidates) and only between members of the same room (checked on every message).

Because a signaling server could in theory substitute DTLS fingerprints, the UI shows a **security code** (a SHA-256 digest of both DTLS fingerprints, 12 digits). Both people compute the same code; if the server tampered, the codes differ. Users can compare them out loud.

Mesh does not scale: each person uploads to everyone else. `VOICE_MAX_PARTICIPANTS` (default 8) caps room size. A larger deployment would need an SFU with SFrame end-to-end encryption.

### STUN/TURN

```
POLLAKCORD_STUN_URLS=stun:chat.example.hu:3478
POLLAKCORD_TURN_URLS=turn:chat.example.hu:3478?transport=udp,turn:chat.example.hu:3478?transport=tcp
POLLAKCORD_TURN_SECRET=<same value coturn uses as static-auth-secret>
```

The API hands each signed-in user short-lived TURN credentials (`username = <expiry>:<user id>`, `credential = base64(HMAC-SHA1(secret, username))`), valid for `TURN_TTL_SECONDS`.

The default STUN server is a public one, which reveals participants' IP addresses to that operator. For a school with minors prefer your own coturn for both STUN and TURN, as the Compose profile provides.

Firewall for coturn: `3478/udp+tcp` and the relay range `49160-49200/udp` (matching `--min-port/--max-port`). Add TLS (`5349`) if you need TURN over TLS through strict proxies.

### Calls

- **Voice channels:** click a voice channel to join. Presence per channel is shown in the sidebar.
- **DM calls:** the phone button rings the other person (45 s). Requires the callee to be a friend with calls allowed, online and not already in a call. An unanswered call becomes a missed-call notification.
- **Server mute/deafen:** members with the right permissions can request it. In a mesh this is **cooperative** (honest clients obey it, a modified client could ignore it); the action is audited. Use kick/ban or role permissions for hard enforcement.

---

## 16. TOTP configuration

Users choose either a platform password **or** an authenticator app. This is separate from E-Kréta's own 2FA.

- **Setup:** the server generates a 160-bit random secret, shows a QR code (SVG generated locally, no external service) and the manual key. Setup completes only after the user enters a valid code.
- **Parameters:** SHA-1, 6 digits, 30 seconds, accepting one step of clock drift either way (RFC 6238, compatible with Google Authenticator, Microsoft Authenticator, Authy and others).
- **Replay protection:** the last accepted time step is stored; a code can be used once.
- **Storage:** the secret is AES-256-GCM encrypted (purpose `totp`, bound to the user id). Secrets, codes and QR data are never logged.
- **Brute force:** per-IP and per-username rate limits plus progressive account lockout (30 s, 60 s, 120 s ... up to 15 min after 5 failures).
- **Recovery:** 8 single-use recovery codes (80 bits each) are shown once at setup. Only keyed HMACs are stored. Codes can be regenerated after re-authentication. Users can also recover through E-Kréta.
- **Changing method:** requires entering the current password/code; the change runs in a short setup session and revokes all other sessions.

---

## 17. Internationalization

- **Languages:** Hungarian (default), English, German. Both the frontend (`src/i18n/locales/*.json`, about 760 keys each) and the backend (`app/locales/*.json`, API errors and default server/role/channel names) are fully translated.
- **No hard-coded UI strings.** Components call `t("namespace.key")`. Plurals use i18next `_one`/`_other`. Dates and times use `Intl` with the active language.
- **Choosing the language:** language selector on public pages (stored in the browser), and `Settings → Appearance` (stored in the account, applied after login).
- **Errors:** the API returns a stable `code`; the frontend translates `errors.<code>` itself and the backend also returns a localized message based on `Accept-Language` for non-browser clients. Validation errors return field codes, never echo input, stack traces or internals.
- **Accessibility labels, tooltips, empty states, confirmation dialogs** are translated like everything else.
- **New servers** get default role/category/channel names in the creator's language.

### Adding a language

1. Copy `frontend/src/i18n/locales/en.json` to `xx.json`, translate, import it in `src/i18n/index.ts`, and add it to `LANGUAGES`.
2. Copy `backend/app/locales/en.json` to `xx.json` and add the code to `SUPPORTED_LANGUAGES` in `app/i18n.py` and to the `Literal` of `language` in `api/v1/me.py`.
3. Run both test suites: they fail if any key, placeholder or error code is missing.

---

## 18. Theme customization

`Settings → Appearance`:

- **Theme mode:** system, dark ("chalkboard"), light ("notebook") or custom.
- **Custom themes:** up to 12 saved per user. Tokens: background, secondary/deep background, text, muted text, accent, text on accent, danger, mention highlight, border, corner radius, and an optional two-colour gradient background. Presets: Notebook, Chalkboard, Highlighter, Midnight. The editor warns when contrast drops below WCAG 4.5:1.
- **Chat appearance:** cozy/compact density, font scale 80-140 %, show/hide timestamps.
- Themes are validated on the server (hex colours, a strict gradient pattern, radius 0-24); anything else is rejected.
- Backgrounds are colours or gradients only, so no remote images are ever loaded.

Design tokens live in `frontend/src/styles/tokens.css`; custom themes override the same CSS variables.

---

## 19. Custom CSS security

Custom CSS is useful and dangerous: pasted themes can exfiltrate data, spoof UI or phish. Defenses:

1. **Server-side parsing and re-serialization** with a real CSS parser (`tinycss2`). Only the re-generated, allowlisted output is stored and ever sent to the browser.
2. **Scoping:** every selector is prefixed with `.user-css-scope`. That wrapper contains the chat shell only. **Login, registration, recovery, all Settings pages (including security) and every dialog render outside it**, so custom CSS cannot restyle credential or security UI. `:root`, `html` and `body` map to the wrapper itself (so themes can set CSS variables).
3. **Blocked:** `@import`, `@font-face`, `@keyframes` and all other at-rules except a restricted `@media`; `url()`, `image-set()`, `src()`, `element()`, `attr()`, `env()` and every function that can fetch or leak; backslash escapes (obfuscation); `expression`, `behavior`, `-moz-binding`; `position: fixed|sticky` (overlays); `content` other than empty/`none`/`normal` (text spoofing); `z-index` above 100; strings containing `javascript:`/`data:text`; nested blocks; files over 32 KB.
4. **CSP backs it up:** `img-src 'self' data: blob:`, `font-src 'self'`, `connect-src` limited to the app, so even a missed rule cannot beam data to another host.
5. **Applied as text** into a `<style>` element (`textContent`), never as HTML. CSS cannot execute JavaScript.
6. The Settings page warns users never to paste CSS from untrusted sources, and shows which rule was rejected.

---

## 20. Moderation system

### Roles

| Level | Who | Can |
| --- | --- | --- |
| **Server** Owner | Creator (transferable) | Everything on that server |
| **Server** Administrator | Role with the `administrator` permission | Everything except owner-only actions; bypasses channel overwrites |
| **Server** Moderator | Built-in role | Delete messages, pin, kick, time out, mute/deafen, view the server audit log, review server reports |
| **Server** Member | Default role | Read, write, react, connect, speak, create invites |
| **Platform** `school_moderator` | School staff (set with the CLI) | Review **escalated** reports, view message context, **reveal real identity** (audited) |
| **Platform** `school_admin` | School staff | Everything above, plus all reports, platform audit log, suspend/restore accounts |

Server permissions (18): view channel, send messages, read history, add reactions, connect, speak, mute members, deafen members, create invites, kick, ban, manage messages, manage channels, manage roles, manage members, manage server, view audit log, administrator. Role hierarchy applies: you can only act on people and roles below your highest role, and never grant a permission you do not hold. Every check runs on the server.

### Reports

Any member can report a message (reason, optional details). The server decrypts the message and a few surrounding ones and stores an **encrypted snapshot** with the report, so evidence survives later deletion.

- **Direct-message reports** and reports with a severe reason (harassment, hate, sexual content, self-harm, violence) are **escalated** to school moderators automatically. Reporters may also escalate manually, and servers can turn member reports off (then everything escalates).
- **Server moderators** see their server's reports with message context but **never real names**.
- **School moderators** see escalated reports; admins see all.

### Real-identity reveal

The only way to see a real name: `POST /moderation/users/{id}/identity` with a written reason (at least 10 characters). It is rate limited (30 per hour per moderator) and recorded in the platform audit log with moderator, target, reason and linked report. Message lookups outside a report also need a reason and are audited. Normal users get a plain 404 on all moderation endpoints.

### Audit logs

Server log: kicks, bans/unbans, timeouts, role and permission changes, channel/category create/update/delete, server settings, pins, moderator message deletions, invites created/revoked, voice moderation, report resolutions. Platform log: identity reveals, report views, message views, account status changes, recoveries. Entries never contain passwords, secrets, codes or message text. Moderator deletions notify the author.

### Suspension

`school_admin` can suspend an account (sessions revoked, WebSockets closed, login refused) and restore it, always with a recorded reason.

---

## 21. Encryption architecture

### Ordinary text messages: encrypted at rest, **not** end-to-end

Messages are encrypted before they reach the database, but the server holds the keys because it must read reported messages and decrypt for permitted users. Anyone who controls the running server (or both the database **and** the master key) can read messages. This is **not** E2EE and the product never describes it as such. It does protect against database leaks, stolen backups and curious database administrators.

### Key hierarchy

```
MASTER_KEY (env / secret file, id k1)         PEPPER (separate secret)
   │  HKDF-SHA256 with purpose labels            │  HKDF-SHA256 with purpose labels
   ├─ "enc/dek-wrap"        wraps data keys      ├─ "mac/kreta-identity"   duplicate-registration hash
   ├─ "enc/identity"        real names           ├─ "mac/recovery-code"    recovery-code hashes
   ├─ "enc/totp"            TOTP secrets         ├─ "mac/search-index"     message search tokens
   └─ "enc/report-snapshot" report evidence      └─ "mac/login-method"     decoy answers for unknown users
        │
        └─ per-conversation / per-channel data key (DEK, 32 random bytes), stored wrapped in `data_keys`
              │  AES-256-GCM, random 96-bit nonce, AAD = "msg|<message id>|<scope>|<scope id>|<author id>"
              └─ ciphertext in `message_contents`
```

- Every ciphertext is `nonce || ciphertext || tag`. The AAD binds a message to its id, conversation and author, so ciphertext moved to another row fails authentication (a test swaps rows and checks nothing leaks).
- Wrapped DEKs carry the id of the master key that wrapped them (`kek_id`), which enables rotation.
- A DEK is replaced after `DATA_KEY_ROTATION_MESSAGES` messages, keeping GCM nonce usage far below safe limits.
- Plaintext is never logged. The log formatter also redacts anything whose key looks sensitive.

### Searchable without plaintext

A blind index stores keyed 16-byte HMACs of normalized words (case- and accent-folded, scoped per channel/conversation). Searches match **whole words**, and an attacker with only the database sees opaque hashes. The cost: equal words in one conversation produce equal hashes, and substring search is impossible.

### Deleting

Deleting a message removes its ciphertext, search tokens, reactions and mentions and leaves a tombstone (so replies still make sense). Report snapshots are separate encrypted copies kept for moderation.

### Voice

Not stored, not recorded, never routed through the server (see [section 15](#15-webrtc-configuration)).

### Key rotation

1. Generate a new key.
2. Set `POLLAKCORD_MASTER_KEY_ID=k2`, `POLLAKCORD_MASTER_KEY=<new>` and `POLLAKCORD_PREVIOUS_MASTER_KEYS=k1:<old>`.
3. Restart. New data is written under `k2`; old data stays readable through `k1`.

A bulk re-wrap tool is **not** included, so keep old keys as long as old data exists. Rotating `PEPPER` invalidates identity hashes, recovery codes and the search index; do not rotate it without a migration plan.

---

## 22. Backup considerations

Back up three things, **separately**:

1. **Database:** `pg_dump -Fc pollakcord` on a schedule (and WAL archiving if you need point-in-time recovery).
2. **Uploads:** the `uploads` volume / `POLLAKCORD_UPLOAD_DIR` (avatars, banners, server icons).
3. **Secrets:** `MASTER_KEY`, `PREVIOUS_MASTER_KEYS`, `PEPPER` in a password manager or secret store, **not** next to the database backup.

Remember:

- Without the master key the encrypted data (messages, real names, TOTP secrets, report snapshots) is **unrecoverable**. Without the pepper, duplicate-registration checks, recovery codes and message search stop working.
- A database backup alone reveals no message text or real names; that is intended. Keep it that way by never storing keys beside it.
- Test a restore regularly: restore the DB, supply the keys, sign in, open an old conversation.
- Backups contain personal data about minors. Encrypt them, restrict access, and define a retention period.
- Aborted E-Kréta logins leave nothing on disk: temp directories are deleted and flow state is only in memory.

---

## 23. Security considerations

### Controls in place

| Area | Implementation |
| --- | --- |
| Transport | HTTPS/WSS, HSTS in production, `__Host-` `Secure` cookies |
| Sessions | 256-bit random opaque tokens, only SHA-256 stored, absolute and idle expiry, rotation on login/credential change, device list with revoke, logout kills sockets, IP stored masked (/24) |
| CSRF | Double-submit token header **plus** strict `Origin`/`Referer` allow-list on every state-changing request; SameSite cookies; WebSocket Origin check |
| XSS | React escapes all content; messages are rendered as text with only `http(s)` links (`rel="noopener noreferrer nofollow"`); strict CSP without inline script or `eval`; sanitized, scoped custom CSS |
| SQL injection | SQLAlchemy parameterized queries only; LIKE wildcards escaped |
| Passwords | Argon2id, 10-128 characters, common-password and username checks, transparent rehash |
| Brute force | Per-IP and per-user rate limits, progressive lockout, identical errors and timing for unknown users, TOTP replay protection, decoy login-method answers |
| Authorization | One permission engine (roles, hierarchy, category/channel overwrites, timeouts), enforced in REST and WebSocket handlers; resources you cannot see return 404; a sweep test verifies every non-public endpoint rejects anonymous callers |
| Enumeration | Friend requests answer generically; profile/DM/server lookups return the same 404 for hidden and non-existent; invite codes are random |
| Uploads | Content sniffed with Pillow (client MIME ignored), extension must match the format, size/dimension/pixel caps, metadata stripped, always re-encoded to WebP, random filenames, served with `nosniff` and a sandbox CSP |
| WebSocket / signaling | Cookie auth + Origin, per-connection rate limits, frame size cap, room-membership check on each signal, payload size cap, kinds allow-list |
| Logging | Structured JSON, request ids, no bodies; secrets, tokens, codes, cookies, message content and names are redacted by key and by pattern |
| Errors | No stack traces, SQL or paths reach clients; unexpected errors return a generic localized message |
| Supply chain | Pinned Python and JS dependencies, E-Kréta script digest pin |
| Code hygiene | No comments anywhere (enforced), small modules, typed frontend |

### Known limitations

- **Text messages are not end-to-end encrypted** (by design, for moderation). See [section 21](#21-encryption-architecture).
- **E-Kréta login depends on the supplied scripted web flow.** E-Kréta changes can break it; the adapter fails closed and tests detect marker drift. The script's own plaintext logging is neutralized by isolation, not by editing it.
- **Typing school credentials into a third-party site is inherently risky** (phishing precedent, possible terms-of-service issues). See the note in [section 9](#authorization-and-data-protection-note).
- **Class is self-declared**, not verified. The script only returns a name.
- **One process only** (in-memory hub, flow store, limiter). No Redis adapter yet.
- **Mesh voice** is limited to 8 people and server mute is cooperative.
- **Message search is whole-word only.**
- **Automated tests run on SQLite.** PostgreSQL is the production target and the schema is portable, but verify it in a staging environment before launch.
- **No account deletion or data export yet.** For GDPR (minors!) you need a process for erasure and access requests; today they require database operations. Plan this before going live.
- **Not included:** message editing, group DMs, push/email notifications, animated avatars, native mobile apps (the web app is responsive), bulk master-key re-wrap.
- Rate limiting is per process; use your proxy/firewall for volumetric protection.

---

## 24. Testing

### Backend (`cd backend && pytest`)

About 250 tests, all against a throw-away SQLite database. Highlights:

| Area | What is covered |
| --- | --- |
| E-Kréta integration | The **unmodified script** is run end-to-end through the adapter against an in-process fake of E-Kréta (a `sitecustomize` hook swaps only the HTTP transport; see `tests/kreta_fake/`): no 2FA, 2FA ok/bad, wrong password, expired licence, hang/timeout. Also: SHA-256 of the script, marker drift detection, no credential in logs/results, scratch dir deleted, process gone, secrets not inherited by the child, stdin-injection rejection, forged-output rejection, flow store TTL/limits |
| Registration and login | Full flow with "Nem" restart, duplicates, resume, username rules, password policy, TOTP setup/replay, lockout, enumeration, recovery codes and E-Kréta recovery, session handling, CSRF, cookie flags, real name never in responses or plaintext in the database |
| Authorization / permissions | Pure unit tests of the permission engine (owner, admin, hierarchy, overwrites, category inheritance, timeouts) plus API tests; non-members get 404 everywhere; every non-public endpoint rejects anonymous users |
| Friends and privacy | Requests, blocks, privacy defaults, class suggestions only between opted-in users, hidden class never leaked, real names unsearchable |
| Servers and channels | Defaults, roles, grants, hierarchy, kick/ban/timeout, invites (limits, expiry, revoke), overwrites, audit log |
| Messages | Encryption at rest, per-scope keys, key rotation, tamper/swap detection, replies, reactions, read state, pins, slowmode, mentions, reports and snapshots, moderation reveal with audit trail, blind-index search with permissions |
| WebSocket | Authentication, subscription authorization, live permission revocation, presence privacy, typing, voice signaling limited to room members, mute moderation, calls, limits, disconnect behaviour |
| Uploads | Valid images, SVG/polyglot/EXIF, wrong extension, size/dimension/pixel limits, path traversal, headers |
| i18n | Every error code used in the source exists in all three catalogs with matching placeholders; language negotiation |
| Security | Headers, CSP, HSTS, rate limiting, trusted-proxy handling, log redaction, error masking, invite/ID randomness, Argon2id, no comments or docstrings in Python sources |
| Migrations | Migrated schema equals the models, seed data present, downgrade works |

### Frontend (`cd frontend && npm test`)

56 tests: translation key/placeholder parity and coverage of every used key, API client (CSRF, retry, errors, uploads), realtime client (reconnect, resubscribe, expired session), E-Kréta confirmation ("Te vagy ...?" Igen/Nem and 2FA), login, composer mentions, inert message rendering, accessibility primitives, theme provider and custom CSS injection, call security code, and a no-comments check.

### Static checks

`npm run typecheck`, `npm run build`, `npm run check:comments`.

### Status at packaging time

The complete backend suite passed at its last full run (248 tests; one further test was added afterwards and passed on its own), the frontend suite passed (56 tests), and the production frontend build succeeded. No automated tests exercise PostgreSQL, a real TURN server, real browsers' WebRTC stacks or the live E-Kréta service; test those in staging.

---

## 25. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Cannot sign in over plain HTTP, session not kept | `COOKIE_SECURE=true` makes browsers drop `Secure` cookies on HTTP. Use HTTPS, or set `POLLAKCORD_COOKIE_SECURE=false` for local development only |
| Every POST returns 403 `origin_not_allowed` or `csrf_failed` | `POLLAKCORD_PUBLIC_ORIGIN` must equal the browser address exactly (scheme, host, port). Add other addresses to `EXTRA_ORIGINS`. Reload so the CSRF cookie is re-issued |
| WebSocket closes immediately with code 4401 | Not signed in, session ended, or Origin mismatch (same fix as above) |
| WebSocket works locally but not behind the proxy | Proxy must forward `Upgrade`/`Connection` headers and allow long reads (see section 14) |
| Rate limits hit everyone at once | `TRUSTED_PROXY_HOPS` is `0` behind a proxy, so all users share the proxy's IP. Set it to the number of proxies |
| App exits at start: "required in production" | Set `POLLAKCORD_MASTER_KEY` and `POLLAKCORD_PEPPER` (`python -m app generate-key`) |
| App exits at start: script digest mismatch | The E-Kréta script differs from `POLLAKCORD_KRETA_SCRIPT_SHA256`. Restore the original, or update the pin after verifying the new file |
| `kreta_unavailable` / `kreta_failed` for everyone | E-Kréta is down, its login changed (script needs an update), or `requests` is missing for `KRETA_PYTHON`. Try the script manually with the same interpreter |
| `kreta_busy` | More than `KRETA_MAX_CONCURRENT` logins at once; retry, or raise the limit |
| Registration says the flow expired | The 2FA window (180 s) or the 15-minute confirmation window passed, or the app restarted. Start again |
| Microphone does not work | Needs HTTPS (or `localhost`) and browser permission; check the lock icon in the address bar |
| Voice connects locally but not across networks | Configure TURN (section 15) and open the UDP relay range |
| `database is locked` | SQLite with several writers. Use PostgreSQL for anything beyond local development |
| Alembic cannot find the database | Run commands from `backend/` and set `POLLAKCORD_DATABASE_URL` (the sync `sqlite://` form is not used; keep `+aiosqlite` / `+asyncpg`) |
| Uploaded image rejected | Must be real PNG/JPEG/WebP/GIF with a matching extension, within the size and dimension limits |
| Custom CSS rejected | Read the reason shown under the editor; `url()`, `@import`, `position: fixed` and similar are intentionally blocked |
| Moderation menu missing | The account needs `school_moderator` or `school_admin`: `python -m app grant-role <username> school_admin` |
| Some characters (for example ő, ű) look like a different font | Fonts are self-hosted; any glyph a subset lacks falls back to the system font, which is cosmetic only |
| Locked out after failed logins | Wait for the delay shown, or recover through E-Kréta or a recovery code |

Logs are JSON on stdout (`docker compose logs -f api`). Each request has an `X-Request-ID`; search for it to follow one request. Raise detail with `POLLAKCORD_LOG_LEVEL=DEBUG` (secrets stay redacted).
