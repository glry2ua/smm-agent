# smm-agent

`smm-agent` is an automated social media marketing agent for real estate. It
runs on Cloudflare Workers and publishes three fresh, on-brand posts to every
connected social channel every week — no manual writing, image sourcing, or
scheduling required.

## What it does

Each week, a cron trigger runs the pipeline:

1. **Selects topics.** Picks unused topics from a D1 database, so nothing is
   repeated.
2. **Writes the posts.** An LLM agent drafts the copy and a structured image
   prompt, choosing relevant reference photos (headshots, property shots,
   logo) from R2.
3. **Generates a custom graphic** for each post and uploads it to R2.
4. **Schedules drafts in Buffer** for Monday, Wednesday, and Friday on every
   connected channel (LinkedIn, Instagram, Facebook). A human reviews each
   draft and clicks Schedule Post to publish it.
5. **Learns from results.** A performance-analyst agent reads the last 30 days
   of Buffer engagement metrics and feeds writing recommendations back into
   future drafts.

It also serves a protected web board at its origin for reviewing, editing,
scheduling, and deleting drafts (with AI image and text edits), backed by
Cloudflare Access.

## Architecture

The weekly job moves data between these services:

```mermaid
flowchart TD
    classDef external fill:#e8f0fe,stroke:#1a73e8,color:#0b57d0
    classDef cf fill:#fef7e0,stroke:#f9ab00,color:#b06000
    classDef agent fill:#e6f4ea,stroke:#188038,color:#0d652d

    Cron(["Cron trigger<br/>0 14 * * MON"]):::external --> Worker
    subgraph cf ["Cloudflare"]
        Worker["smm-agent Worker<br/>(Python)"]:::cf
        D1[("D1<br/>smm-agent-db<br/>topics table")]:::cf
        R2[("R2<br/>smm-agent-assets<br/>references + generated graphics")]:::cf
        Worker -->|pick unused topic| D1
        D1 -->|topic| Worker
        Worker -->|list reference images| R2
        R2 -->|headshot / outdoor / logo| Worker
        Worker -->|upload generated graphic| R2
    end
    subgraph ai ["OpenAI"]
        Editor["social-post-editor agent<br/>drafts post + image prompt"]:::agent
        Image["GPT Image 2<br/>generates the graphic"]:::agent
        Analyst["performance-analyst agent<br/>reads 30-day Buffer metrics"]:::agent
    end
    Worker -->|topic + references| Editor
    Editor -->|structured draft| Worker
    Worker -->|image prompt| Image
    Image -->|PNG| Worker
    subgraph buf ["Buffer"]
        BufferAPI["Buffer GraphQL API"]:::external
        Channels["LinkedIn · Instagram · Facebook<br/>scheduled drafts"]:::external
    end
    Analyst -->|writing recommendations| Editor
    BufferAPI -->|sent-post metrics| Analyst
    Worker -->|create scheduled draft| BufferAPI
    BufferAPI --> Channels
    Channels -.->|manual review & publish| Social(["Social networks"]):::external
```

## Install

Prerequisites:

- [uv](https://docs.astral.sh/uv/) 0.12+
- [Node.js](https://nodejs.org/) 22
- A Cloudflare account on the Workers Paid plan
- A Buffer account with a connected channel and an API key
- An OpenAI API key with access to the image model

Setup:

```bash
# clone the repo, then:
cp .env.example .env          # fill in OPENAI_API_KEY, BUFFER_API_KEY,
                              # BUFFER_ORGANIZATION_ID, ASSET_PUBLIC_BASE_URL
uv sync                       # install Python dependencies
npx wrangler d1 list          # find your database_id
sed 's/<your-database-id>/<the-id-from-d1-list>/' \
  wrangler.example.jsonc > wrangler.jsonc
uv run pywrangler sync        # one-time: vendor Python deps for wrangler
npm run build                 # build the web frontend + vendor deps
npx wrangler d1 migrations apply smm-agent-db --remote
```

Local dev:

```bash
npm run dev        # Worker (localhost:8787) + Vite hot reload (localhost:5173)
npm run web-mock   # UI-only, mock data, no backend or API keys
```

Local dev runs against the real production D1 and R2 bindings and the same
`.env` values as production — board actions mutate live Buffer posts, so treat
it like a production console.

The same pipeline runs locally via the CLI (same D1/R2, no deploy needed):

```bash
uv run python src/cli.py dry-run --n=1      # generate posts + images, no Buffer writes
uv run python src/cli.py end-to-end --n=1   # full run: creates Buffer drafts
uv run python src/cli.py buffer_state       # list configured Buffer channels
```

## Deploy

1. Set every value from `.env` as a production secret:

   ```bash
   node -e "const o={};for(const l of require('fs').readFileSync('.env','utf8').split(/\r?\n/)){if(!l||l.startsWith('#'))continue;const i=l.indexOf('=');o[l.slice(0,i)]=l.slice(i+1)}console.log(JSON.stringify(o))" \
     | npx wrangler secret bulk -
   ```

   (`ASSET_PUBLIC_BASE_URL` must be the deployed Worker origin, e.g.
   `https://smm-agent.<subdomain>.workers.dev`, with no trailing path.)

2. Build and deploy:

   ```bash
   npm run build
   npx wrangler deploy
   ```

The cron trigger runs every Monday at 14:00 UTC (`0 14 * * MON`). CI runs lint
and type checks (`npm run check`) before deploying.

## Configuration

`.env` is the single source of truth for all Worker environment values. In
production every value is set with `wrangler secret put <NAME>` (write-only;
re-run the command to change it).

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Authenticates OpenAI Agents and image generation |
| `BUFFER_API_KEY` | Authenticates the Buffer GraphQL API |
| `BUFFER_ORGANIZATION_ID` | Targets the Buffer organization |
| `ASSET_PUBLIC_BASE_URL` | Public origin of the Worker, used to build image URLs for Buffer |
| `OPENAI_IMAGE_MODEL` | Image generation model name |
| `OPENAI_IMAGE_WIDTH` / `OPENAI_IMAGE_HEIGHT` | Image dimensions in pixels (multiples of 16) |
| `OPENAI_IMAGE_QUALITY` | One of `low`, `medium`, `high`, `auto` |
| `BUFFER_API_URL` | Buffer GraphQL endpoint |
| `MIN_SCHEDULE_LEAD_MINUTES` | Minimum minutes between now and a post's due time |
| `SCHEDULE_HORIZON_DAYS` | Maximum days between now and a post's due time |
| `MAX_POST_CHARS` | Maximum characters in the Buffer post text |
| `RETRY_MAX_ATTEMPTS` | Retry attempts for transient Buffer and image errors |
| `RETRY_BACKOFF_SECONDS` | Initial exponential backoff in seconds |
