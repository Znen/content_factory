# Content Factory (`generation-factory`)

Generative MCP layer for the Hermes agent: cheap ComfyUI drafts + Nano Banana finals,
organized into per-project `media/` per the storage spec. Sits alongside `knowledge-factory`.

> **Ставишь у себя (fal.ai / Replicate через Codex)?** Передай своему агенту файл
> **[AGENT_SETUP.md](AGENT_SETUP.md)** — он всё настроит сам (клон, установка, ключ, подключение к
> Codex). Предпочитаешь разобраться руками — см. **[QUICKSTART.md](QUICKSTART.md)**. Локальная
> инфраструктура для fal/Replicate не нужна — только API-ключ.

## Tools (for Hermes)

- `gf_generate_draft(project, prompt, n=4, negative="", seed=0)` — N cheap ComfyUI drafts
  → `<project>/media/generated/<date>/_drafts/draft-NN.png`.
- `gf_generate_final(project, prompt, refs=None, aspect="9:16")` — Nano Banana final (≤4 refs)
  → `<project>/media/generated/<date>/nano_*.png`.
- `gf_generate_video(project, mode, prompt, ...)` — Seedance video via Dreamina CLI
  (`mode`: i2v|t2v|frames|multimodal). Hybrid wait: downloads the mp4 if ready within
  `GF_DREAMINA_POLL_WAIT`, otherwise records `submit_id` (pending) in `.gf_video_jobs.jsonl`.
- `gf_list_video_jobs(project)` / `gf_fetch_video(project, submit_id)` — registry status +
  pick up a finished clip by its ticket.
- `gf_fal_run(project, endpoint, input, wait_seconds=None)` — run a fal.ai model endpoint or
  authenticated workflow endpoint through the async queue. Downloads discovered output media to
  `<project>/media/generated/<date>/` and video/audio to `<project>/media/generated/<date>/video/`.
- `gf_fal_list_workflows(search="", used_endpoint_ids="", limit=50, cursor="")` — list the
  authenticated user's fal.ai workflows.
- `gf_replicate_run(project, model, input, wait_seconds=None)` — run any Replicate model
  (`owner/name`, `owner/name:<version>` or a bare 64-hex version) through the predictions API.
  `@R:/...` file markers anywhere in `input` are uploaded via the Replicate Files API; output
  media are downloaded like fal's (video/audio → `video/`). Timeout → `pending` + `poll_url`.

`project` is the absolute path to the project folder.

## Install

    python -m pip install -e ".[dev]"

## Run the gateway

    gf serve            # stdio (local Hermes subprocess) — default
    gf serve --http     # streamable-HTTP on GF_MCP_BIND:GF_MCP_PORT (8766); bearer if GF_MCP_TOKEN set

## Config (env / .env)

See `.env.example`. Key vars: `GF_COMFYUI_URL` (8188), `GF_COMFYUI_CKPT`, `GF_NANO_SERVER_URL`
(3001), `GF_IMAGE_CAP_USD` (soft cap), `GF_MCP_PORT` (8766), `GF_MCP_TOKEN`. Video (Dreamina):
`GF_DREAMINA_BIN` (`dreamina`), `GF_DREAMINA_POLL_WAIT` (180s), `GF_DREAMINA_MODEL`
(`seedance2.0fast`). Magnific (images/REST): `GF_MAGNIFIC_API_KEY`, `GF_MAGNIFIC_BASE_URL`
(`https://api.magnific.com`), `GF_MAGNIFIC_TIMEOUT` (180s), `GF_MAGNIFIC_POLL_INTERVAL` (3s),
`GF_MAGNIFIC_DOWNLOAD_TIMEOUT` (120s), `GF_MAGNIFIC_DOWNLOAD_RETRIES` (3).
fal.ai: `FAL_KEY`, `GF_FAL_QUEUE_URL` (`https://queue.fal.run`), `GF_FAL_API_URL`
(`https://api.fal.ai`), `GF_FAL_TIMEOUT` (180s), `GF_FAL_POLL_INTERVAL` (3s),
`GF_FAL_DOWNLOAD_TIMEOUT` (120s).
Replicate: `REPLICATE_API_TOKEN`, `GF_REPLICATE_BASE_URL` (`https://api.replicate.com`),
`GF_REPLICATE_TIMEOUT` (180s), `GF_REPLICATE_POLL_INTERVAL` (3s),
`GF_REPLICATE_DOWNLOAD_TIMEOUT` (120s).
`project` must be an **absolute** path — generators refuse a relative path (fail-closed).
Prompt writer: `ANTHROPIC_API_KEY`, `GF_WRITER_MODEL` (`claude-sonnet-5`).

## External services

- **ComfyUI** at `Q:\ComfyUI_windows_portable` — start before using drafts; default `:8188`.
  Default checkpoint `juggernautxl_ragnarok.safetensors` (override `GF_COMFYUI_CKPT`).
- **Nitro Express (Nano Banana)** at `R:\nitro_banana` — `npm run dev:server`, `:3001`.
  Password in `~/.lionfilms/nitro_banana.env` (`NITRO_BANANA_APP_PASSWORD`).
- **fal.ai** queue API — set `FAL_KEY` in `.env`. The factory uses `Authorization: Key <FAL_KEY>`
  but never prints the key. Inputs may include public URLs, data URIs, or explicit local file
  markers such as `@R:/project/ref.png`; only `@...` markers are converted. A marker inside
  `video_urls`/`image_urls`/`audio_urls` is **uploaded to fal storage** and replaced by the
  returned `https://v3.fal.media/...` URL, because those fields reject data URIs (Seedance
  reference-to-video); markers anywhere else become MIME-correct base64 data URIs. Plain
  strings stay untouched. fal pricing is endpoint-specific, so `cost_usd` is returned as
  `null` and not invented by the factory.

## fal.ai examples

    gf fal-run R:\Projects\demo fal-ai/nano-banana-pro "{\"prompt\":\"cinematic portrait\"}"
    gf fal-run R:\Projects\demo workflows/my-workflow "{\"image\":\"@R:/Projects/demo/ref.png\"}"
    gf fal-list-workflows --search portrait --limit 20

Curated public fal endpoints verified for this integration note:

- Model endpoints: `fal-ai/nano-banana-pro`;
  `bytedance/seedance-2.0/text-to-video`, `bytedance/seedance-2.0/image-to-video`,
  `bytedance/seedance-2.0/reference-to-video`, and their fast variants;
  `fal-ai/kling-video/v3/standard/image-to-video`;
  `fal-ai/wan-25-preview/image-to-video`.
- Public workflow templates are browsable at <https://fal.ai/workflows/templates>. These are
  templates, not your private workflow list.
- Authenticated user workflows come from `gf fal-list-workflows` /
  `gf_fal_list_workflows`, and endpoint IDs beginning with `workflows/` run through the same
  queue contract as model endpoints.

## Tests

    python -m pytest              # unit tests (mocked HTTP)
    GF_RUN_LIVE=1 python -m pytest -m live   # hits real ComfyUI/Nitro

## Cost-gating

Each generation logs an estimate to `<project>/media/.gf_cost_log.jsonl`. If `GF_IMAGE_CAP_USD`
is set, a generation that would push cumulative project spend over the cap is refused.

## Roadmap

Phase 1 (this): skeleton + `gf_generate_draft` + `gf_generate_final`.
Phase 2: `gf_save_asset`, `gf_assemble_shot` (face+location multi-ref), prompt sidecars.
Phase 3: `gf_contact_sheet`, process memory. Phase 4: wire into Hermes `config.yaml`, archive old agent.
