# Launching the public instance

The order below is forced: each step needs the one before it. Clerk's production
instance cannot verify a domain that does not resolve yet, and the API refuses to
start in clerk mode without the keys that instance hands out. Work top to bottom and
run each step's check before moving on.

Two ways to reach the server are covered: **direct** (ports 80 and 443 open, Caddy
gets its own certificate) and **Cloudflare Tunnel** (no open ports, Cloudflare
terminates TLS). Where they differ, the step says so.

## 1. Domain and server

1. Pick the hostname people will use, for example `reader.example.com`.
2. **Direct:** point its DNS `A`/`AAAA` record at the server and open ports 80 and 443.
   **Tunnel:** in Cloudflare Zero Trust, create a tunnel and add a public hostname
   for your domain with service `http://caddy:80`. Put the tunnel's token in `.env`
   as `CLOUDFLARE_TUNNEL_TOKEN` now: `make tunnel-up` refuses to start without it.
3. On the server, copy `.env.example` to `.env` and set the values it lists as wrong
   for production:
   ```sh
   POSTGRES_PASSWORD=...          # "alo" is in this public repo
   APP_VERSION=1.0.0              # what /healthz reports
   AUTH_MODE=none                 # clerk comes in step 4; none boots without Clerk keys
   ```
   **Direct:** also `ALO_SITE_ADDRESS=reader.example.com`, which is what turns TLS on.
   **Tunnel:** leave `ALO_SITE_ADDRESS` alone; the tunnel overlay serves plain `:80`.

**Check.** Start it (`make up` direct, `make tunnel-up` tunnel) and run
`curl -s https://reader.example.com/api/v1/healthz`: it answers with your
`APP_VERSION`, over a valid certificate (Let's Encrypt direct, Cloudflare's through the
tunnel). Then **stop it** (`make down`, or `make tunnel-down`). `AUTH_MODE=none` has no
authentication at all, so it must not stay reachable from the internet while you set
up Clerk.

## 2. Clerk production instance and its DNS

1. In the Clerk dashboard, create the **production** instance of your application and
   give it your domain.
2. Add the five DNS records the dashboard lists: the Frontend API (`clerk.<domain>`),
   the Account Portal (`accounts.<domain>`) and three for email. **On Cloudflare, set
   them to "DNS only"**, not proxied: behind the proxy Clerk's DNS check fails.
3. Wait until the dashboard shows every record as verified. Propagation can take up
   to 48 hours.

**Check.** Every record verified in the dashboard, and the Frontend API answers:
`curl -s -o /dev/null -w '%{http_code}\n' https://clerk.<domain>/.well-known/jwks.json`
returns `200`.

## 3. Clerk production settings

In the production instance, not the development one:

1. **Sign-up mode: restricted or waitlist for the first weeks.** It is the cheapest
   abuse control there is, and opening sign-up later is one click.
2. **Bot sign-up protection: on** (Protect → Rules). Only the e2e test instance has it
   off.
3. **Account Portal → Redirects:** set *After sign-up fallback* and *After sign-in
   fallback* to `https://<domain>/app`. Sign-up and sign-in happen in the app's own
   page, but anyone who reaches Clerk's hosted pages another way lands here; the
   default is `/`, the landing page.
4. **Webhooks → Add endpoint:** `https://<domain>/api/v1/webhooks/clerk`, subscribed to
   `user.created`, `user.updated` and `user.deleted`. Copy this endpoint's signing
   secret (`whsec_...`); every endpoint has its own.

## 4. Switch the server to clerk mode

Set these in `.env`:

```sh
AUTH_MODE=clerk
CLERK_PUBLISHABLE_KEY=pk_live_...
CLERK_ISSUER=https://clerk.<domain>            # Configure → API keys → Frontend API URL
CLERK_WEBHOOK_SECRET=whsec_...                 # from step 3.4
CLOUDFLARE_TUNNEL_TOKEN=...                    # tunnel only
```

Leave `ALO_CLERK_ORIGIN` unset: it defaults to `CLERK_ISSUER`, which is right. Do not
add `CLERK_SECRET_KEY`; nothing in the app uses it.

Then `make up` (direct) or `make tunnel-up` (tunnel).

**Trap: the Clerk origin.** A `pk_live_` key loads Clerk from your own `clerk.<domain>`,
and the page's Content-Security-Policy allows exactly `ALO_CLERK_ORIGIN`. If that is
wrong (a leftover development value, a typo), sign-in fails with errors that only
show in the browser console, and nothing on the server logs a thing. That was #76.

**Trap: accounts do not move between Clerk instances.** A user of the development
instance is a different user in production, with a different id. `users.clerk_user_id`
is keyed on that id, so any rows created during development testing are orphans in
production. Launch on a fresh database, or accept that those rows will never sign in
again.

**Check.**
- `curl -s https://<domain>/api/v1/config` shows `"auth_mode":"clerk"` and a
  `pk_live_` key.
- `curl -s https://<domain>/api/v1/healthz` reports your `APP_VERSION`.
- In a browser, the browser console on `/app/` shows no Content-Security-Policy errors.

## 5. Legal page and the rest of `.env`

`/legal` states facts about this instance, read from `.env`. Set them before anyone
signs up:

```sh
ALO_CONTACT_EMAIL=...          # shown as the contact address
ALO_LEGAL_OPERATOR=...         # who runs the instance
ALO_LEGAL_HOSTING=...          # where it runs, e.g. "Hetzner, Germany"
```

Also decide these, whose defaults are stated on `/legal` or shape every new account:

- `RETENTION_HORIZON_DAYS`, `BACKUP_RETENTION_DAYS`, `LOKI_RETENTION`: what `/legal`
  says you keep, and for how long.
- `BACKUP_RCLONE_REMOTE` (and optionally `ALO_LEGAL_BACKUP_REMOTE` for its wording):
  off-box backups. `deploy/BACKUP.md` has the setup and the restore.
- `QUOTA_SUBS_DEFAULT` (300): the subscription cap each new account gets.
- `SENTRY_DSN`, optional: error reporting.

**Check.** `https://<domain>/legal` names you, your hosting and your contact address,
and its retention numbers match your `.env`.

## 6. Smoke test, with a real account

1. **Landing page.** `https://<domain>/` loads; `curl -s https://<domain>/ | grep og:image`
   shows `https://<domain>/og-card.png`, and that URL returns the card.
2. **Sign up** with a real address (allow it through the restriction from step 3.1, or
   invite it). You land in the app, not on the landing page.
3. **The webhook arrived.** In the Clerk dashboard, the endpoint's log shows the
   `user.created` delivery answered `204`. A `401` there means `CLERK_WEBHOOK_SECRET` is
   not this endpoint's secret.
4. **Use it.** Subscribe to a feed, open an article, sign out (you land on the landing
   page), sign back in (you are back in the same account).
5. **Delete that test account** from the account menu (Manage account → Security →
   Delete account; the production instance must allow users to delete their own
   accounts). The endpoint log shows `user.deleted` answered `204`: its local data is
   gone.
6. **Real visitor addresses (tunnel).** Caddy's log shows your own public IP as
   `client_ip`, not the tunnel's `172.31.254.2`. If it shows the tunnel's address, the
   per-IP rate limit is treating everyone as one visitor.

## 7. After launch

- **Backups:** confirm the first nightly dump exists (and reached the remote, if set)
  before anyone depends on the instance. Practise one restore (`scripts/restore.sh`).
- **Alerts:** with the observability overlay, `docs/ALERTS.md` covers where alerts go
  and what each one means.
- **Opening sign-up:** when you are ready, switch the Clerk sign-up mode from
  restricted or waitlist to public. Nothing on the server changes.
