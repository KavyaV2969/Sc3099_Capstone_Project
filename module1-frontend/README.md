# Module 1: Frontend PWA

Student check-in interface — Next.js 14 (App Router) + TypeScript + Tailwind.

## Prerequisites

- Node.js 18+ and npm
- Backend running locally (see `module2-backend/README.md`)

## Run locally

1. Install dependencies:
```powershell
   npm install
```
2. Create `.env.local` in `module1-frontend/`:
```
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```
4. Make sure the Backend API is running locally (see
   `module2-backend/README.md`) at `http://localhost:8000`.
5. Start the dev server:
```powershell
   npm run dev
```
5. Open `http://localhost:3000/login` to open login page.
