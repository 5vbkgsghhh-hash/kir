"""Exercise the real installed MCP SDK's HTTP transport without a network port."""
import json


async def call(app, name, arguments, *, headers=None, base_url="http://127.0.0.1:8765",
               input_responses=None, request_state=None):
    import httpx
    params = {"name": name, "arguments": arguments, "_meta": {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "kir-test", "version": "1"},
    }}
    if input_responses is not None:
        params["inputResponses"] = input_responses
    if request_state is not None:
        params["requestState"] = request_state
    request_headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                       "MCP-Protocol-Version": "2026-07-28", "mcp-method": "tools/call", "mcp-name": name}
    if isinstance(headers, list):
        request_headers = list(request_headers.items()) + headers
    else:
        request_headers.update(headers or {})
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url=base_url) as client:
            return await client.post("/mcp", headers=request_headers, content=json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}))
