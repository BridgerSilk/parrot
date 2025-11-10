import aiofiles
import asyncio
from aiohttp import web
from pathlib import Path
from .utils import guess_mime_type, file_mtime, compute_etag_bytes
from .mml_adapter import convert_mml_file_to_html_string
from datetime import datetime, timezone

CHUNK_SIZE = 64 * 1024

async def read_file_bytes(path: Path) -> bytes:
    async with aiofiles.open(path, "rb") as f:
        return await f.read()

async def stream_file(response: web.StreamResponse, path: Path):
    async with aiofiles.open(path, "rb") as f:
        while True:
            chunk = await f.read(CHUNK_SIZE)
            if not chunk:
                break
            await response.write(chunk)
    await response.write_eof()

async def handle_static_request(request: web.Request, filesystem_root: str, enable_dir_listing: bool = False):
    """
    Main static handler:
    - map URL path to filesystem path under filesystem_root
    - if a .mml file exists at that path (or index.mml in dir) -> convert to html string and serve (no physical html)
    - else if .html file exists -> serve it
    - else serve other static resources if exist
    - else 404
    """

    rel_url_path = request.match_info.get("tail", "")
    if rel_url_path == "":
        rel_url_path = request.path.lstrip("/")

    root = Path(filesystem_root).resolve()

    joined = (root / rel_url_path).resolve()
    if not str(joined).startswith(str(root)):
        return web.Response(status=403, text="Forbidden")

    if joined.is_dir():
        for idx in ("index.mml", "index.html"):
            idx_path = joined / idx
            if idx_path.exists():
                joined = idx_path
                break
        else:
            if enable_dir_listing:
                items = []
                for p in joined.iterdir():
                    items.append(p.name + ("/" if p.is_dir() else ""))
                body = "<html><body><h1>Directory listing for {}</h1><ul>{}</ul></body></html>".format(
                    request.path, "".join(f"<li><a href=\"{name}\">{name}</a></li>" for name in items)
                )
                return web.Response(text=body, content_type="text/html")
            return web.Response(status=404, text="Not Found")

    if joined.suffix == "":
        mml_try = joined.with_suffix(".mml")
        html_try = joined.with_suffix(".html")
        if mml_try.exists():
            return await _serve_mml(mml_try, request)
        if html_try.exists():
            joined = html_try

    if joined.suffix == ".mml" and joined.exists():
        return await _serve_mml(joined, request)

    if joined.exists() and joined.is_file():
        return await _serve_file(joined, request)

    for ext in (".mml", ".html"):
        p = joined.with_suffix(ext)
        if p.exists():
            if ext == ".mml":
                return await _serve_mml(p, request)
            else:
                return await _serve_file(p, request)

    return web.Response(status=404, text="Not Found")

async def _serve_mml(mml_path: Path, request: web.Request):
    html = await asyncio.get_event_loop().run_in_executor(None, convert_mml_file_to_html_string, str(mml_path))
    if html is None:
        return web.Response(status=500, text="MML conversion failed")
    body_bytes = html.encode("utf-8")
    etag = compute_etag_bytes(body_bytes)
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "ETag": etag,
        "Cache-Control": "no-cache",
        "Last-Modified": (file_mtime(mml_path) or datetime.now()).strftime("%a, %d %b %Y %H:%M:%S GMT")
    }
    if_none_match = request.headers.get("If-None-Match")
    if if_none_match and if_none_match == etag:
        return web.Response(status=304, headers=headers)

    return web.Response(body=body_bytes, headers=headers)

async def _serve_file(path: Path, request: web.Request):
    mime = guess_mime_type(str(path))
    body_bytes = await read_file_bytes(path)
    etag = compute_etag_bytes(body_bytes)
    headers = {
        "Content-Type": mime,
        "ETag": etag,
        "Cache-Control": "public, max-age=60",
    }
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=headers)
    return web.Response(body=body_bytes, headers=headers)