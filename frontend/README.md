# QueryMind frontend

Next.js 14 (App Router) + React + Tailwind chat UI for QueryMind. Talks to
the Phase 3 FastAPI backend's `POST /chat` endpoint -- see the root
`PROGRESS.md` for the full picture of what this phase built and how the
pieces fit together.

## Run

```bash
# from this directory
npm install
cp .env.local.example .env.local   # optional -- only needed if the backend
                                    # isn't at the default http://localhost:8000
npm run dev
```

Then open http://localhost:3000. The backend (`uvicorn backend.app.api.main:app
--port 8000`, run from the repo root) must be running first -- see the root
README/PROGRESS.md for backend setup.

## Structure

```
app/
  layout.js        root layout, global styles
  page.js           the chat interface (client component: message state,
                     conversation_id, submit/reset handlers)
  globals.css        Tailwind entrypoint + a few global resets
components/
  ChatMessage.js     user bubble, assistant response (success + guardrail-
                     rejected states), pending/"running the query" state
  SqlBlock.js         collapsible generated-SQL code block with copy button
  ResultsTable.js     result rows as a table
  ResultsChart.js     picks bar vs. line vs. no-chart from the result shape
                     (see pickChart()), renders via recharts
lib/
  api.js              sendChatMessage() / resetConversation() -- the only
                     two calls the UI makes into the backend
```
