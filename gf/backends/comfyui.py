"""ComfyUI backend — REST client written from scratch (old agent had no Python client).

Flow: POST /prompt (API-format workflow) -> prompt_id -> poll /history/{id} -> GET /view.
Pure HTTP; no cost/project logic. `session` param defaults to `requests` for test injection.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path

import requests

_BUNDLED = Path(__file__).resolve().parent.parent / "workflows" / "sdxl_txt2img_api.json"


class ComfyError(Exception):
    pass


def load_workflow(path: "str | None") -> dict:
    src = Path(path) if path else _BUNDLED
    if not src.exists():
        raise ComfyError(f"Workflow not found: {src}")
    return json.loads(src.read_text(encoding="utf-8"))


def build_workflow(template: dict, *, ckpt: str, prompt: str, negative: str,
                   n: int, seed: int, width: int, height: int, steps: int, cfg: float) -> dict:
    wf = copy.deepcopy(template)
    wf["4"]["inputs"]["ckpt_name"] = ckpt
    wf["6"]["inputs"]["text"] = prompt
    wf["7"]["inputs"]["text"] = negative
    wf["5"]["inputs"]["batch_size"] = n
    wf["5"]["inputs"]["width"] = width
    wf["5"]["inputs"]["height"] = height
    wf["3"]["inputs"]["seed"] = seed
    wf["3"]["inputs"]["steps"] = steps
    wf["3"]["inputs"]["cfg"] = cfg
    return wf


def _submit(session, server_url: str, wf: dict, client_id: str) -> str:
    url = f"{server_url.rstrip('/')}/prompt"
    try:
        r = session.post(url, json={"prompt": wf, "client_id": client_id}, timeout=30)
    except requests.exceptions.ConnectionError as e:
        raise ComfyError(f"Cannot reach ComfyUI at {server_url}. "
                         f"Start it (Q:\\ComfyUI_windows_portable). ({e})") from e
    if r.status_code != 200:
        raise ComfyError(f"POST /prompt failed HTTP {r.status_code}: {r.text[:300]}")
    pid = r.json().get("prompt_id")
    if not pid:
        raise ComfyError(f"No prompt_id in response: {r.text[:200]}")
    return pid


def _poll(session, server_url: str, pid: str, poll_interval: float, timeout: float) -> list:
    url = f"{server_url.rstrip('/')}/history/{pid}"
    deadline = time.time() + timeout
    while True:
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            hist = r.json()
            if pid in hist:
                images = []
                for node in hist[pid].get("outputs", {}).values():
                    images.extend(node.get("images", []))
                return images
        if time.time() > deadline:
            raise ComfyError(f"ComfyUI job {pid} timed out after {timeout}s")
        if poll_interval:
            time.sleep(poll_interval)


def _download(session, server_url: str, image: dict) -> bytes:
    from urllib.parse import urlencode
    params = {"filename": image.get("filename", ""),
              "subfolder": image.get("subfolder", ""),
              "type": image.get("type", "output")}
    url = f"{server_url.rstrip('/')}/view?{urlencode(params)}"
    r = session.get(url, timeout=60)
    if r.status_code != 200:
        raise ComfyError(f"GET /view failed HTTP {r.status_code}")
    return r.content


def generate(prompt: str, out_dir: Path, *, server_url: str, ckpt: str,
             workflow_path: "str | None" = None, n: int = 4, negative: str = "",
             seed: int = 0, width: int = 1024, height: int = 1024, steps: int = 20,
             cfg: float = 7.0, poll_interval: float = 1.0, timeout: float = 300.0,
             session=None) -> "list[Path]":
    session = session or requests
    template = load_workflow(workflow_path)
    wf = build_workflow(template, ckpt=ckpt, prompt=prompt, negative=negative, n=n,
                        seed=seed, width=width, height=height, steps=steps, cfg=cfg)
    client_id = uuid.uuid4().hex
    pid = _submit(session, server_url, wf, client_id)
    images = _poll(session, server_url, pid, poll_interval, timeout)
    if not images:
        raise ComfyError(f"ComfyUI job {pid} produced no images")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, img in enumerate(images, start=1):
        data = _download(session, server_url, img)
        p = out_dir / f"draft-{i:02d}.png"
        p.write_bytes(data)
        saved.append(p)
    return saved
