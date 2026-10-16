# PollákCord media and links change set

## Review map

| Area | Files and behavior |
| --- | --- |
| Schema | `models/attachment.py`, nullable media fields on chat/DÖK/class-space messages, additive Alembic `0005_message_media.py` |
| Uploads | `services/attachments.py`, `services/media_access.py`, `api/v1/uploads.py`: streamed scope-bound storage, role limits, safe authenticated downloads, atomic claims, pending cleanup |
| Messaging | `services/messages.py`, `services/dok.py`, `services/class_spaces.py`, channel/DM send schemas: encrypted media metadata and cached link embeds |
| Fetching | `services/link_embeds.py`: bounded HTTP(S), DNS/IP validation and pinning, redirect checks, metadata parsing and thumbnail sanitization |
| Client | shared `SafeLink`, `MessageMedia`, `GiphyPicker`, `useComposerMedia`, composer/timeline integration, narrow progress-upload extension to the existing CSRF client |
| Configuration | settings, conditional GIPHY CSP allowances, `.env.example`, hu/en/de UI and error catalogs, CLI cleanup command |
| Validation | `backend/tests/test_media.py`, `frontend/src/test/media.test.tsx`, existing messaging, permissions, migrations, i18n and no-comments suites; build helper type declaration added for the existing `.mjs` hygiene checker |



## Behavior and operations

Server chat and direct messages support up to ten attachments and one GIPHY GIF per message, including messages with no text. DÖK and class-space composers remain text-only; their links use the same warning and preview layer. Form text remains inert text, as before.

| Human platform role | Maximum per attachment |
| --- | --- |
| `user` | 20,000,000 bytes (20 MB) |
| `dok_representative`, `dok_president` | 250,000,000 bytes (250 MB) |
| `school_moderator`, `school_admin` | 250,000,000 bytes (250 MB) |

These limits apply to message attachments; the existing avatar, banner, and server-icon image limits remain in place. Authentication, active/full sessions, CSRF, channel visibility/send permissions, timeouts, and DM privacy/block checks apply before reading an attachment body. Downloads recheck current conversation membership or channel view/history permissions. Elevated platform roles do not bypass these permissions.

All variables below use the `POLLAKCORD_` prefix and appear in `.env.example`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GIPHY_API_KEY` | empty | Enables GIPHY in server/DM composers; absent key hides the picker |
| `ATTACHMENT_MAX_BYTES` | `20000000` | Normal human per-file limit |
| `ATTACHMENT_ELEVATED_MAX_BYTES` | `250000000` | Staff and DÖK per-file limit |
| `ATTACHMENT_HOURLY_BYTES` | `200000000` | Normal user's aggregate uploaded file bytes per hour |
| `ATTACHMENT_ELEVATED_HOURLY_BYTES` | `1000000000` | Elevated user's aggregate uploaded file bytes per hour |
| `LINK_EMBEDS_ENABLED` | `true` | Enables bounded server-side link metadata fetches |
| `LINK_EMBED_TIMEOUT_SECONDS` | `4` | Total preview-fetch budget per message, including images and redirects |

Run `cd backend && alembic upgrade head` before starting this version. Migration `0005` adds the attachments table and nullable encrypted media fields; existing message bodies and metadata remain readable without a data migration.

**Endpoints and storage.** `GET /api/v1/uploads/config` supplies the signed-in user's effective size limit, canonical origin, and optional browser GIPHY key. `POST /api/v1/uploads/attachments?scope=channel|dm&scope_id=...` accepts exactly one multipart `file`. The message send endpoints accept `attachment_ids` and an optional `giphy_id`; attachment IDs must belong to the author and the same scope, be less than 24 hours old, and be unused. Claims are atomic and rolled back with failed sends. `GET /api/v1/uploads/attachments/{id}` requires an active authenticated session and current scope access. `DELETE` at the same path discards only the owner's unattached draft. Deleting a message revokes its attachments.

Files use the existing uploads volume under `attachments/`; this directory is never mounted as static/public content. Bytes are opaque files on disk, consistent with the current media storage policy; filenames and per-message link/GIF metadata are encrypted with the existing vault and row-bound AAD. Image uploads are re-encoded to WebP, with existing pixel/dimension guards and metadata stripping; animated uploaded images use their first frame. Recognized MP4/WebM files may play inline with authenticated HTTP range requests, without transcoding. Other files, including HTML, SVG, and JavaScript, are forced to `application/octet-stream` with attachment disposition even if inline display is requested. Upload responses use `nosniff`, a sandbox CSP, and `no-store`. There is no antivirus scanner in this change.

The per-user request cap is 60 attachment uploads/hour (30 for the elevated tier), plus the byte budgets above. Failed transfers count for bandwidth already received. Limits use the existing in-process limiter; run a shared/distributed limiter before using multiple API workers when a strict cross-worker quota is required. Schedule `cd backend && python -m app.cli cleanup-media` daily to remove expired draft rows and orphaned files older than 24 hours, including files orphaned by account/channel deletion. The frontend also aborts in-flight uploads and discards drafts when leaving a conversation. Back up the entire uploads volume alongside the database and encryption keys.

**Proxy and tunnel configuration.** Every proxy and tunnel on the upload path must accept more than 250,000,000 bytes to leave room for multipart overhead (for example a 260 MB request-body ceiling), with read/write timeouts suitable for slow uploads and enough spool/disk capacity. The bundled Caddyfile does not impose a smaller body ceiling; if you add a [Caddy request_body limit](https://caddyserver.com/docs/caddyfile/directives/request_body), raise `max_size` accordingly. For Nginx, raise `client_max_body_size` (the README example uses `260m`). A larger origin limit cannot override an upstream provider's ceiling. Cloudflare Free/Pro normally impose a 100 MB upload ceiling, so do not assume a 250 MB upload will pass through a Cloudflare proxy or Tunnel; verify the [current plan and zone limits](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/) and arrange a supported configuration before enabling the elevated tier for users.

**GIPHY.** Use a browser API key and obtain the appropriate GIPHY production approval. The authenticated config endpoint intentionally exposes this key to the browser; do not use a privileged server credential. Search and saved-ID lookup call the official GIPHY API directly with `rating=pg`, omit app cookies, and load the original returned media URLs. Only a validated alphanumeric GIF ID is stored with the encrypted message metadata. Recipients resolve the ID again with the PG filter, so removed/restricted GIFs are not replayed from a server cache. The picker and displayed GIF include Powered by GIPHY and creator attribution. The CSP permits only the GIPHY API connection and GIPHY-hosted images in addition to existing sources. This follows [GIPHY's direct-request and no-media-caching guidance](https://developers.giphy.com/docs/api/). If GIPHY, the API key, the school network, or a media URL is unavailable, the message stays readable and a GIF-unavailable label is shown. GIPHY receives the browser's API/media requests; arbitrary link-preview images are handled differently, as below.

**External links and unfurls.** Activating user-supplied HTTP(S) links in chat, DMs, DÖK, class spaces, GIF attribution, or preview cards first opens the same accessible Hungarian/English/German warning dialog. Cancel, Escape, focus trapping, keyboard activation, modifier clicks, and middle clicks are handled. Continue opens a new tab with `noopener noreferrer`; canonical `PUBLIC_ORIGIN` links open normally. Plain form text remains non-clickable.

For new message links, the server fetches at most two previews with a shared four-request concurrency gate and a four-second overall budget. Only HTTP/HTTPS on standard ports is accepted. Local/private/link-local/multicast/metadata addresses, mixed public/private DNS answers, IPv6 transition addresses, credentials in URLs, local names, the app's own origins, and obvious admin/auth routes are rejected. Every redirect is validated again (maximum three); connections are pinned to a validated IP while TLS verification/SNI and Host use the original hostname. Requests carry no cookies, credentials, or browser headers. Documents are limited to 512 KiB, response headers to 16 KiB, and each image to 1 MB; compressed documents are refused. Open Graph/standard title, description, site name, and available image/favicon metadata are saved encrypted with the message. Preview images are fetched through the same SSRF checks, re-encoded, and stored as small WebP data images, so recipients never fetch arbitrary metadata URLs. Failed fetches produce no card or a hostname-only chip; sending still succeeds. Existing messages are not fetched retroactively. Network egress rules blocking internal ranges remain useful defense in depth.

**Bots.** Bot attachment limits, bot message attachment rules, bot API surfaces, and bot UX are deliberately deferred until the bot merge. This change adds only human role/channel/DM policy. The shared size, storage, and metadata helpers are separate from human scope authorization so future bot integration can reuse the storage layer.


## Validation (2026-10-15)

| Check | Result |
| --- | --- |
| Full frontend suite | 193 passed |
| Final media/client regression | 27 passed after the final upload-client guard |
| Production frontend build | Passed (`tsc --noEmit` and Vite) |
| Frontend comment scan | Passed |
| Full backend suite | 370 passed; 1 environment-dependent failure |
| Final backend media regression | 157 passed |
| Migration/schema agreement and reversible upgrade/downgrade | Passed |
| Whitespace/error checks | `git diff --check` passed |

Commands:

```sh
cd frontend
npm ci
npm test
npm run typecheck
npm run build
npm run check:comments
cd ../backend
python -m pytest tests -q
python -m pytest tests/test_media.py tests/test_messages.py tests/test_dok.py tests/test_class_spaces.py tests/test_migrations.py tests/test_i18n.py tests/test_security.py -q
```

The full backend suite's only failure is the pre-existing `tests/test_kreta_integration.py::test_child_process_does_not_inherit_server_secrets`, which reads `/proc/<child pid>/environ`. This sandbox has no procfs entries, so it raises `FileNotFoundError` before its assertion. The same isolated test reproduces the environment failure. No E-Kréta/authentication code or existing tests were changed or disabled. Rerun that test on a Linux host with procfs. The additional teardown warning in the full run follows that interrupted child-process test; the media regression run has no application failures.

No live GIPHY credentials were used: official API behavior and failure paths are mocked in tests. Real production network policy, reverse-proxy upload ceilings, PostgreSQL deployment, and browser video codec support still need deployment validation.
