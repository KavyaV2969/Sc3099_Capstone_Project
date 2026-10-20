# Module 1 — Frontend PWA

Student check-in app for SAIV, built with Next.js 14 (App Router), TypeScript
and Tailwind CSS. Students register, give consent, enroll a face, check in to
sessions with a photo and their location, and review or appeal results. The
app installs as a PWA and its read-only pages work offline.

## Implemented pages

| Route | Purpose |
|---|---|
| `/login`, `/register` | Authentication (registration requires an `@e.ntu.edu.sg` email and a strong password) |
| `/consent` | Camera and location consent after registration |
| `/enroll-face` | Live camera preview, capture and face enrollment |
| `/` | Current and upcoming sessions, face-enrollment gate, "Checked in" state |
| `/checkin?session=<id>` | Photo (when the session requires one), location, submit, result with risk score |
| `/courses` | Enrolled courses |
| `/courses/[courseId]` | Check-ins for a course |
| `/courses/[courseId]/checkins/[checkinId]` | Check-in result, appeal form |
| `/privacy` | Camera and location switches, registered devices (list and remove) |
| `/help` | FAQ |
| `/permission-denied` | Explains why camera or location is needed and lets the user change consent |

## API used

Base path: `/api/v1`

| Method | Path | Used for |
|---|---|---|
| POST | `/auth/register`, `/auth/login`, `/auth/refresh` | Accounts and token refresh |
| GET, PUT | `/users/me` | Profile and consent flags |
| POST | `/users/me/face/enroll` | Face enrollment |
| GET | `/sessions/my-sessions`, `/sessions/{id}` | Session list and details |
| GET | `/enrollments/my-enrollments` | Courses |
| GET | `/checkins/my-checkins`, `/checkins/{id}` | Check-in history and detail |
| POST | `/checkins/` | Check in |
| POST | `/checkins/{id}/appeal` | Appeal a flagged or rejected check-in |
| POST | `/devices/register` | Register this browser and its public key |
| POST | `/devices/{id}/challenge` | Get a one-time challenge to sign |
| GET, DELETE | `/devices/my-devices`, `/devices/{id}` | List and remove devices |

## Run locally

1. Install dependencies:
```bash
   npm install
```
2. Create `.env.local` in this folder (Next.js only reads it from the project root):
```
   NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```
3. Make sure the backend is running at `http://localhost:8000`
   (see `module2-backend/README.md`).
4. Start the dev server:
```bash
   npm run dev
```
5. Open `http://localhost:3000/login`.

Env changes need a dev server restart. Camera, location and the device key
only work on `http://localhost` or HTTPS.

## Run with Docker

From the repository root:

```bash
docker compose up -d --build frontend backend face-recognition
```

- The image uses Next.js standalone output.
- `NEXT_PUBLIC_API_URL` is baked in at build time through the `PUBLIC_BACKEND_URL`
  build argument (default `http://localhost:8000/api/v1`).
- Open `http://localhost:3000`, not `127.0.0.1`, because the backend only allows
  the `localhost` origin.
- Code changes need a rebuild. Clear site data in the browser afterwards, so
  the service worker doesn't serve old files.

## Offline and PWA

- `public/manifest.json` and the icons make the app installable.
- `public/sw.js` saves page shells and their scripts at install and as pages are
  visited. Pages are fetched network-first, so they are never stale, and the
  saved copy is only the offline fallback. Backend calls always go to the network.
- Courses, course check-ins, check-in details, Privacy and Home save their last
  response in IndexedDB (localForage) and show it with an "offline" banner when
  the server can't be reached. Saved data is cleared on logout.
- Anything that sends data (check-in, appeals, consent switches, removing a
  device) needs a connection and says so.
- Check-ins are never cached or queued. They must be real-time, and the signed
  challenge expires after 120 seconds.

To test offline, use the Docker build, not `npm run dev`, and warm the cache
while online first. Dev mode renames its files on every save, so the saved
copies don't match. Stopping the backend and frontend containers is a more
realistic test than switching off WiFi, because the backend runs locally.

## Device binding

- Each browser has one random device ID (64 hex characters) and one ECDSA P-256
  key pair. The private key is non-extractable and kept in IndexedDB.
- The public key is registered as PEM through `/devices/register`.
- At check-in the app requests a challenge for the exact request body, signs it
  with the private key, and sends `device_challenge_id` and `device_signature`.
  A challenge works once and expires after 120 seconds.
- An administrator marks a device trusted. A device used by a second account is
  rejected at registration with a clear message.
- The key is stable per device on purpose. The backend resets trust when a
  device's key changes, so rotating it at every login would defeat trusted
  devices.

## Security and privacy

- Access and refresh tokens are kept in `sessionStorage` and cleared on logout.
  The backend returns them in the response body, so HttpOnly cookies aren't used.
- `lib/api.ts` adds the access token to each request and refreshes it once on a
  401, then retries.
- Camera and location need consent saved on the account before the browser
  prompt is requested.
- Photos are captured in memory, sent once, and not kept by the app. The camera
  is released as soon as a photo is taken or the page is left.

## Known limitations

- The device ID is a per-browser identifier, not a hardware fingerprint.
  Clearing site data creates a new device.
- Offline mode is read-only by design.

## Project structure

```
app/          pages and layouts (App Router)
components/   AppShell, sidebar and shared UI
lib/          api client, token storage, device key, geolocation, offline helpers
public/       manifest.json, icons, sw.js
```