# Deploying QueryMind

This project is containerized (`./Dockerfile`) and CI-tested (`.github/workflows/ci.yml`),
so it's deploy-ready. **Actually creating and clicking through Render/Vercel
accounts requires credentials this environment doesn't have and isn't allowed
to create on your behalf** — no sandbox here has network access to
`render.com`/`vercel.com`, and even if it did, an account, a payment method
(for Render's persistent Postgres), and an `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`
are all things only you can provide. What follows is the exact sequence to
run yourself; each step should take a few minutes.

**Order matters:** database → backend → frontend, since the backend needs a
live `DATABASE_URL` before it will boot, and the frontend needs a live
backend URL before its `NEXT_PUBLIC_API_BASE` is worth setting.

---

## 0. Prerequisites

- A GitHub repo with this project pushed (Render and Vercel both deploy
  from a connected Git repo).
- An `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` — set `LLM_PROVIDER=mock` if
  you want to deploy first and add a real key later; the app runs fully
  end-to-end either way (see `eval/REPORT.md` for what `mock` does and
  doesn't prove about answer quality).
- Free-tier accounts are enough for a portfolio demo on both platforms.

---

## 1. Database — Render Postgres (or Railway Postgres)

QueryMind needs Postgres **with the `pgvector` extension**. Render's
managed Postgres supports `pgvector` directly; Railway's Postgres template
does too.

1. Render dashboard → **New → PostgreSQL**. Name it `querymind-db`, pick
   the free/starter plan, same region you'll deploy the backend to
   (reduces latency and avoids a cross-region egress surprise).
2. Once it's provisioned, copy the **Internal Database URL** (for the
   backend, same-region traffic, no extra cost) and the **External
   Database URL** (for running the one-time seed scripts from your own
   machine).
3. Connect with the external URL and enable the extension once:
   ```bash
   psql "$EXTERNAL_DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```
4. Run the Phase 1–2 setup scripts **locally, pointed at the remote DB**
   (there's no separate "run this on Render" step for one-time setup —
   these are idempotent scripts you run once from your laptop against the
   external URL):
   ```bash
   export DATABASE_URL="$EXTERNAL_DATABASE_URL"
   python data/seed/generate_data.py            # defaults: 2,000 users / 300 merchants / 50,000 transactions
   python data/seed/seed_db.py
   python backend/app/ingestion/introspect_schema.py
   python backend/app/ingestion/embed_documents.py
   psql "$EXTERNAL_DATABASE_URL" -f data/seed/create_readonly_role.sql
   ```
5. Note the `READONLY_DATABASE_URL` this prints/creates — the backend
   needs both this and `DATABASE_URL` as env vars in the next step.

---

## 2. Backend — Render Web Service (Docker)

1. Render dashboard → **New → Web Service** → connect your GitHub repo.
2. Render will detect the root `Dockerfile` automatically — choose
   **Docker** as the environment (not "native"/buildpack) so it builds
   from `./Dockerfile` as-is.
3. **Environment variables** (Render's dashboard, not a committed file —
   copy the shape from `.env.example`, but with real values):
   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the **Internal** Postgres URL from step 1 |
   | `READONLY_DATABASE_URL` | the read-only role's DSN from step 1.5 |
   | `LLM_PROVIDER` | `anthropic` (or `openai`, or `mock` to deploy without a key first) |
   | `ANTHROPIC_API_KEY` | your key (if `LLM_PROVIDER=anthropic`) |
   | `ANTHROPIC_MODEL` | `claude-sonnet-4-6` |
   | `EMBEDDING_PROVIDER` | `local` (matches what was embedded in step 1; see README's embedding-provider note before changing this) |
   | `FRONTEND_ORIGIN` | your Vercel URL, added **after** step 3 exists (e.g. `https://querymind.vercel.app`) — this is what makes CORS allow the deployed frontend, see `backend/app/api/main.py` |
   | `LOG_LEVEL` | `INFO` |
4. Render sets `PORT` automatically and the Dockerfile's `CMD` already
   reads `$PORT` (`uvicorn ... --port ${PORT}`), so no extra config is
   needed there.
5. Deploy. Render builds the image from `./Dockerfile` and runs the
   container's built-in `HEALTHCHECK` (`GET /health`) to know when it's live.
6. Verify:
   ```bash
   curl https://<your-service>.onrender.com/health
   # {"status":"ok","llm_provider":"anthropic"}
   curl -X POST https://<your-service>.onrender.com/chat \
     -H "Content-Type: application/json" \
     -d '{"question": "What was transaction volume last quarter by state?"}'
   ```

**Railway alternative:** same shape — "New Project → Deploy from GitHub
repo" detects the `Dockerfile` automatically, add the same env vars under
the service's **Variables** tab, and add a Postgres plugin from Railway's
template marketplace (`railway add postgres`) for step 1 instead of Render's.

---

## 3. Frontend — Vercel

1. Vercel dashboard → **Add New → Project** → import the same GitHub repo.
2. **Root Directory**: set this to `frontend/` (Vercel builds from repo
   root by default; QueryMind's Next.js app lives in the `frontend/`
   subfolder) — Vercel's "Root Directory" setting in the project's
   General settings handles this without needing a `vercel.json`.
3. Framework preset: Vercel auto-detects **Next.js** once the root
   directory is set correctly; build command (`next build`) and output
   are automatic.
4. **Environment variable** (Project Settings → Environment Variables):
   | Key | Value |
   |---|---|
   | `NEXT_PUBLIC_API_BASE` | your Render/Railway backend URL from step 2, e.g. `https://querymind-backend.onrender.com` |
5. Deploy. Vercel gives you a `*.vercel.app` URL immediately.
6. **Go back to step 2.3** and set the backend's `FRONTEND_ORIGIN` to this
   exact Vercel URL, then redeploy the backend — until that's set, the
   browser's CORS preflight from the deployed frontend will be rejected
   (this is intentional; see `backend/app/api/main.py`'s CORS config).
7. Open the Vercel URL, ask a question, and confirm you see SQL + a
   results table/chart + explanation render end-to-end against the live
   backend.

---

## 4. Post-deploy checklist

- [ ] `GET /health` on the backend returns `{"status":"ok", ...}`
- [ ] A question from the deployed frontend returns a real answer (not a
      CORS error in the browser console — see step 3.6 if it does)
- [ ] `LLM_PROVIDER` is `anthropic` or `openai`, not `mock`, if this is
      meant to demo real NL2SQL quality (mock is fine for demoing the
      guardrail/UI/multi-turn plumbing, but see `eval/REPORT.md`'s "what
      this does and doesn't prove")
- [ ] The guardrail-rejection UI state actually triggers — ask "delete all
      disputes" and confirm the clay-red rejected-query state renders
      (this is the single most resume-relevant behavior to have working
      live: it's the whole point of the SQL guardrail layer)
- [ ] `.env`/`.env.local` were never committed — confirm secrets only live
      in Render/Vercel's dashboards, not in git history

## 5. Cost note

Render's free web-service tier spins down after inactivity (a first
request after idle can take ~30–60s to cold-start — worth a line in your
demo/README so it doesn't look broken). Render's free Postgres tier
expires after 90 days; Railway's usage-based free tier doesn't have that
specific limit but does meter compute/storage. Vercel's hobby tier is free
indefinitely for a project at this traffic scale. None of this needs a
paid plan to demo for a job search, but don't leave a free Postgres
instance to silently expire before an interview.
