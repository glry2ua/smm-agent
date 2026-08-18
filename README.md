# smm-agent

`smm-agent` is a weekly Cloudflare Python Worker that generates and schedules
social media posts for a San Jose real-estate brand. Each Monday it selects an
unused topic from a D1 database, drafts a post and an image prompt with an
OpenAI agent, generates a graphic with GPT Image 2, uploads it to an R2 bucket,
and schedules the post as a Buffer draft on every connected channel.

This repository contains the Worker, the local CLI for dry-run and end-to-end
testing, the agent definitions, and the test suite.

## Architecture

The following diagram shows how the weekly job moves data between Cloudflare
bindings, OpenAI, and Buffer.

```mermaid
flowchart TD
    classDef external fill:#e8f0fe,stroke:#1a73e8,color:#0b57d0
    classDef cf fill:#fef7e0,stroke:#f9ab00,color:#b06000
    classDef agent fill:#e6f4ea,stroke:#188038,color:#0d652d

    Cron(["Cron trigger<br/>0 14 * * MON"]):::external --> Worker
    subgraph cf ["Cloudflare"]
        Worker["smm-agent Worker<br/>(Python)"]:::cf
        D1[("D1<br/>smm-agent-db<br/>keywords table")]:::cf
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

## How it works

The weekly job runs on a cron trigger. The pipeline has four stages:

1. **Select topics.** The Worker pulls unused topics from the `keywords` table
   in the `smm-agent-db` D1 database. Each topic is marked `used_at` after a
   successful live run, so a topic is never reused.
2. **Draft posts.** The `social-post-editor` agent uses the OpenAI Agents SDK to
   produce a post description, keywords, and a structured image prompt. The
   agent can select up to three typed reference images from R2 (headshot,
   indoor, outdoor, logo) and must follow reference-accuracy rules: it cannot
   invent an outdoor scene, a person, or a logo unless the matching typed
   reference is selected.
3. **Generate images.** Each draft's image prompt is sent to GPT Image 2. In a
   dry-run the file is written to `dry_run_outputs/`; in a live run the image is
   uploaded to the `smm-agent-assets` R2 bucket under
   `assets/generated_graphics/`.
4. **Schedule posts.** A scheduled draft is created in Buffer for each selected
   channel. Buffer requires manual review before the post is published.

A second agent, `performance-analyst`, reads the last 30 days of Buffer
sent-post metrics and returns writing recommendations that feed back into the
next draft.

## Repository layout

```
agents/                 Agent prompt definitions (frontmatter + instructions)
migrations/             D1 schema migrations
src/                    Worker entrypoint, job orchestration, CLI, and modules
tests/                  Pytest suite
wrangler.jsonc          Cloudflare Worker configuration
pyproject.toml          Python dependencies and tooling
```

Key modules in `src/`:

- `worker.py` — Cloudflare Worker entrypoint. Handles `fetch` for health and
  asset reads, and `scheduled` for the weekly cron.
- `job.py` — `run_weekly_job` orchestrates the four-stage pipeline and is shared
  by the Worker, the CLI, and the tests.
- `social_agent.py` — wraps the OpenAI Agents SDK calls for drafting and
  performance analysis.
- `image_pipeline.py` — GPT Image 2 generation and R2 upload.
- `buffer_client.py` — async GraphQL client for Buffer channel listing, post
  creation, and metrics.
- `settings.py` — reads and validates environment-backed configuration.
- `cli.py` — local CLI for dry-run, end-to-end, and Buffer inspection.

## Prerequisites

Install the following before you begin:

- [uv](https://docs.astral.sh/uv/) 0.12 or later
- [Node.js](https://nodejs.org/) 22 (required by `pywrangler`; Node 24 and later
  removed the `--experimental-wasm-stack-switching` flag that Pyodide needs)
- A Cloudflare account on the Workers Paid plan (the bundled dependencies
  exceed the 3 MB free-plan Worker size limit, and the weekly cron needs more
  than the 10 ms free-plan CPU limit)
- A Buffer account with at least one connected channel and an API key
- An OpenAI API key with access to GPT Image 2

## Local setup

1. Clone the repository.
2. Copy `.env.example` to `.env` and fill in the secret values:

   ```
   OPENAI_API_KEY=
   BUFFER_API_KEY=
   BUFFER_ORGANIZATION_ID=
   ```

3. Install the Python dependencies:

   ```bash
   uv sync
   ```

4. Run the test suite:

   ```bash
   uv run pytest -q
   ```

## Configuration

The Worker reads configuration from Cloudflare environment variables and
secrets. Non-secret values live in `wrangler.jsonc` under `vars`; secret values
are set with `wrangler secret put` and never appear in the repository.

| Variable | Where | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | secret | Authenticates OpenAI Agents and GPT Image 2 calls |
| `BUFFER_API_KEY` | secret | Authenticates the Buffer GraphQL API |
| `BUFFER_ORGANIZATION_ID` | secret | Targets the Buffer organization |
| `ASSET_PUBLIC_BASE_URL` | `wrangler.jsonc` | Public origin of the Worker, used to build image URLs for Buffer |
| `OPENAI_IMAGE_MODEL` | `wrangler.jsonc` | GPT Image 2 model name |
| `OPENAI_IMAGE_WIDTH` | `wrangler.jsonc` | Image width in pixels (multiple of 16) |
| `OPENAI_IMAGE_HEIGHT` | `wrangler.jsonc` | Image height in pixels (multiple of 16) |
| `OPENAI_IMAGE_QUALITY` | `wrangler.jsonc` | One of `low`, `medium`, `high`, `auto` |
| `BUFFER_API_URL` | `wrangler.jsonc` | Buffer GraphQL endpoint |
| `CONTENT_BRIEF` | `wrangler.jsonc` | Editorial brief the agent follows |
| `MIN_SCHEDULE_LEAD_MINUTES` | `wrangler.jsonc` | Minimum minutes between now and a post's due time |
| `SCHEDULE_HORIZON_DAYS` | `wrangler.jsonc` | Maximum days between now and a post's due time |
| `MAX_POST_CHARS` | `wrangler.jsonc` | Maximum characters in the Buffer post text |
| `RETRY_MAX_ATTEMPTS` | `wrangler.jsonc` | Retry attempts for transient Buffer and image errors |
| `RETRY_BACKOFF_SECONDS` | `wrangler.jsonc` | Initial exponential backoff in seconds |

## R2 brand information and source images

The Worker reads exact business contact values from `info/contact.json` in the
`smm-agent-assets` R2 bucket:

```json
{
  "business_name": "Your Business Name",
  "phone": "(555) 555-5555",
  "city": "Your City, ST",
  "website": "https://your-website.example/"
}
```

Store the logo at `info/logo.png`. Contact details and the logo are optional in
each generated graphic; when selected, the values and logo file are used
verbatim.

Organize source photos by R2 folder: `indoors/`, `outdoors/`, `headshots/`,
and `headshot group/`. The agent may combine complementary sources—for example,
a headshot for the Realtor's identity, an outdoor image for the setting, and
the logo for the brand mark. The pipeline validates each role independently
before it sends the selected files to GPT Image 2.

## Local CLI

The CLI in `src/cli.py` runs the same pipeline locally against the production
D1 and R2. It accepts a mode and optional flags.

### Modes

- `dry-run` — generates posts and images without calling Buffer `createPost`
  or marking D1 keywords as used. Image files are written to
  `dry_run_outputs/`.
- `headshot-test` — runs one deterministic dry-run post against a preselected
  Realtor topic with a headshot reference.
- `end-to-end` — performs production mutations: it creates Buffer scheduled
  drafts and marks D1 keywords as used.
- `buffer_state` — lists the configured Buffer organization and channels.
- `buffer_insights` — reports per-channel Buffer metrics for the last 30 days.

### Flags

- `--json` — print the complete machine-readable result instead of the
  validation report.
- `--skip-keyword-update` — submit posts without marking the selected D1
  keywords as used (`end-to-end` only).
- `--linkedin` — build and submit posts only for available LinkedIn channels.
- `--instagram` — build and submit posts only for available Instagram channels.
- `--facebook` — build and submit posts only for available Facebook channels.
- `--n N` — generate and schedule N posts for this run (1–3; default 3).
- `--force` — run on a non-Monday for local testing. The schedule anchors to
  the next Monday so publish times stay inside the future scheduling window.
- `--topic TOPIC` — select one exact unused D1 topic (`dry-run` only; implies
  `--n=1`).
- `--reference-image PATH` — include a local source image in the dry-run
  reference catalog (repeatable).
- `--reference-key R2_KEY` — include an exact remote R2 source-image key in the
  generation catalog (repeatable).
- `--output-dir DIR` — directory for GPT Image 2 outputs generated by a dry-run
  (default `dry_run_outputs`).

The platform flags `--linkedin`, `--instagram`, and `--facebook` are mutually
exclusive.

### Examples

Run a dry-run of one post:

```bash
uv run python src/cli.py dry-run --n=1
```

Run a headshot test with a local source image:

```bash
uv run python src/cli.py headshot-test \
  --reference-image ../media/headshot.png
```

Run an end-to-end post on Facebook without marking the keyword as used:

```bash
uv run python src/cli.py end-to-end --facebook --n=1 --skip-keyword-update --force
```

List the configured Buffer channels:

```bash
uv run python src/cli.py buffer_state
```

## Deploy

The Worker deploys with `pywrangler`, the CLI for Cloudflare Python Workers.
`pywrangler` bundles the Python dependencies into the Worker upload.

1. Set `ASSET_PUBLIC_BASE_URL` in `wrangler.jsonc` to the deployed Worker
   origin (for example, `https://smm-agent.<subdomain>.workers.dev`).
2. Apply the D1 migrations to the remote database:

   ```bash
   npx wrangler d1 migrations apply smm-agent-db --remote
   ```

3. Set the secrets. Each command prompts for the value:

   ```bash
   npx wrangler secret put OPENAI_API_KEY
   npx wrangler secret put BUFFER_API_KEY
   npx wrangler secret put BUFFER_ORGANIZATION_ID
   ```

4. Deploy the Worker:

   ```bash
   PATH="/opt/homebrew/opt/node@22/bin:$PATH" uv run pywrangler deploy
   ```

The cron trigger runs every Monday at 14:00 UTC (`0 14 * * MON`).

## Testing

The test suite uses `pytest`:

```bash
uv run pytest -q
```

Lint the code with `ruff`:

```bash
uv run ruff check src tests
```

## Notes on dependency versions

The Cloudflare Python runtime uses Pyodide, which constrains the versions you
can bundle:

- `pydantic` is pinned to `2.10.6`. The Pyodide package index ships a
  compatible `pydantic-core` wheel for this version. Newer pydantic versions do
  not yet have a PyEmscripten wheel that matches the runtime's Python 3.13
  platform.
- `tzdata` is an explicit dependency. The `zoneinfo` module needs the IANA
  timezone database at import time, and Pyodide does not bundle it by default.
- `openai_compat.py` patches the OpenAI SDK's Responses API usage models so a
  missing `cache_write_tokens` field does not raise a pydantic `ValidationError`.
  The live API returns `cached_tokens` but the SDK requires both fields.