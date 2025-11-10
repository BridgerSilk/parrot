import asyncio
from parrot.server import HTTPServer

server = HTTPServer()

# example route using decorator
@server.route("/api/ping")
async def ping(method, path, request):
    return server.json_response({"pong": True, "path": path})

# example route that returns static content using helper
@server.route("/panel")
async def panel_dashboard(method, path, request):
    return await server.serve_static("/parrot/templates/404.mml")

if __name__ == "__main__":
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("Shutting down parrot...")