import anyio, os
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

API_KEY = os.environ["MCP_API_KEY"]
URL = "https://mcp.tenantsage.org/mcp/"

TOOLS_TO_TEST = [
    # Governance tools — actor added
    ("policy.check",      {"actor": "e2e-test", "action": "read", "resource_type": "document", "resource_id": "test-001"}),
    ("risk.score",        {"actor": "e2e-test", "action": "read", "resource_type": "document", "resource_id": "test-001"}),
    ("audit.log",         {"actor": "e2e-test", "action": "read", "input": {"resource_id": "test-001"}, "outcome": "success"}),
    ("workflow.dispatch", {"actor": "e2e-test", "type": "test", "title": "e2e-test-run", "input_data": {}}),
    ("approval.request",  {"actor": "e2e-test", "subject": "e2e-test-run", "reason": "e2e validation", "input_data": {}}),
    # RAG tools
    ("rag.retrieve",      {"query_embedding": [0.1] * 1536, "top_k": 1}),
    ("rag.ingest_source", {"name": "e2e-test", "source_type": "document", "metadata": {}}),
    ("rag.ingest_chunks", {"source_id": "00000000-0000-0000-0000-000000000000", "chunks": []}),
]

async def main():
    headers = {"X-API-Key": API_KEY}
    async with streamablehttp_client(URL, headers=headers, timeout=30) as (r, w, _):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print(f"INIT_OK  serverName={init.serverInfo.name!r} version={init.serverInfo.version!r}")

            tools_result = await s.list_tools()
            names = [t.name for t in tools_result.tools]
            print(f"TOOLS_COUNT {len(names)}  names={names}")
            print()

            for tool_name, args in TOOLS_TO_TEST:
                try:
                    res = await s.call_tool(tool_name, args)
                    is_err = getattr(res, "isError", None)
                    text = ""
                    if getattr(res, "content", None):
                        first = res.content[0]
                        text = getattr(first, "text", str(first))
                    status = "ERROR" if is_err else "OK"
                    # Print full text for errors (tracebacks), truncate for OK
                    display = text if is_err else text[:120]
                    print(f"[{status}]  {tool_name}")
                    if display:
                        for line in display.splitlines():
                            print(f"       {line}")
                    print()
                except Exception as e:
                    print(f"[EXCEPTION]  {tool_name}: {type(e).__name__}: {str(e)[:200]}")
                    print()

anyio.run(main)
