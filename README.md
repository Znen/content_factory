# Content Factory (`generation-factory`)

Generative MCP layer for the Hermes agent: cheap ComfyUI drafts + Nano Banana finals,
organized into per-project `media/` per the storage spec. Sits alongside `knowledge-factory`.

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
(`seedance2.0fast`). Prompt writer: `ANTHROPIC_API_KEY`, `GF_WRITER_MODEL` (`claude-sonnet-5`).

## External services

- **ComfyUI** at `Q:\ComfyUI_windows_portable` — start before using drafts; default `:8188`.
  Default checkpoint `juggernautxl_ragnarok.safetensors` (override `GF_COMFYUI_CKPT`).
- **Nitro Express (Nano Banana)** at `R:\nitro_banana` — `npm run dev:server`, `:3001`.
  Password in `~/.lionfilms/nitro_banana.env` (`NITRO_BANANA_APP_PASSWORD`).

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
