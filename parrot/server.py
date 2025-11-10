from aiohttp import web
from typing import Callable, Dict, Awaitable, Optional
import asyncio
from pathlib import Path
from .static import handle_static_request
from .mml_adapter import convert_mml_file_to_html_string
from .utils import guess_mime_type
import json
import logging

logger = logging.getLogger("parrot")
logging.basicConfig(level=logging.INFO, format="[parrot] %(message)s")

HandlerType = Callable[[str, str, web.Request], Awaitable[web.StreamResponse]]

class HTTPServer:
    def __init__(self, host="127.0.0.1", port=8080, root=".", enable_dir_listing=False):
        self.host = host
        self.port = port
        self.root = Path(root).resolve()
        self.enable_dir_listing = enable_dir_listing
        self._routes: Dict[str, HandlerType] = {}
        self._app = web.Application()
        self._app.router.add_route('*', '/{tail:.*}', self._catch_all)
        logger.info(f"Parrot root set to {self.root}")

    def route(self, path: str, methods: Optional[list]=None):
        """
        Decorator to register handler functions.

        Handler signature (async):
        async def handler(method: str, path: str, request: aiohttp.web.Request) -> aiohttp.web.Response
        """
        methods = methods or ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
        def decorator(fn: HandlerType):
            self._routes[path] = fn
            logger.info(f"Registered route {path} [{','.join(methods)}]")
            return fn
        return decorator

    async def _catch_all(self, request: web.Request):
        path = request.path
        method = request.method.upper()

        handler = self._routes.get(path)
        if handler:
            try:
                result = await handler(method, path, request)
                if isinstance(result, web.StreamResponse):
                    return result
                return web.Response(text=str(result))
            except web.HTTPException as e:
                raise
            except Exception:
                logger.exception("Route handler error")
                return web.Response(status=500, text="Internal Server Error")

        return await handle_static_request(request, filesystem_root=str(self.root), enable_dir_listing=self.enable_dir_listing)

    async def run(self):
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, host=self.host, port=self.port)
        logger.info(f"Starting parrot on http://{self.host}:{self.port}")
        await site.start()
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await runner.cleanup()

    def json_response(self, data, status=200):
        return web.Response(text=json.dumps(data), status=status, content_type="application/json")

    async def serve_static(self, relative_path: str):
        """
        Serve a file relative to the server root. Supports on-the-fly .mml conversion.
        This is a convenience helper you can call from route handlers.
        """
        file_path = Path(self.root) / relative_path.lstrip("/")
        if not file_path.exists():
            return web.Response(status=404, text="File not found")

        if file_path.suffix == ".mml":
            loop = asyncio.get_event_loop()
            html = await loop.run_in_executor(None, convert_mml_file_to_html_string, str(file_path))
            if html is None:
                return web.Response(status=500, text="MML conversion failed")
            return web.Response(text=html, content_type="text/html")

        try:
            return web.FileResponse(path=file_path)
        except Exception as e:
            try:
                data = file_path.read_bytes()
                ctype = guess_mime_type(str(file_path))
                return web.Response(body=data, content_type=ctype)
            except Exception as e2:
                return web.Response(status=500, text=f"Error reading file: {e2}")
