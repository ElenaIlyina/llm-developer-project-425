import os
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from src.mcp_client import call_create_ticket


class McpClientTests(unittest.TestCase):
    def invoke(self, error=False, failure=None):
        result = SimpleNamespace(isError=error, model_dump=lambda **kw: {'content': [{'text': '{"ticket_id":"id"}'}]})
        session = SimpleNamespace(initialize=AsyncMock(), call_tool=AsyncMock(return_value=result, side_effect=failure))
        @asynccontextmanager
        async def transport(*args, **kwargs):
            yield ('reader', 'writer')
        @asynccontextmanager
        async def connection(*args, **kwargs):
            yield session
        mcp = ModuleType('mcp')
        mcp.ClientSession = MagicMock(side_effect=connection)
        sse = ModuleType('mcp.client.sse')
        sse.sse_client = MagicMock(side_effect=transport)
        with patch.dict('sys.modules', {'mcp': mcp, 'mcp.client': ModuleType('mcp.client'), 'mcp.client.sse': sse}), \
                patch.dict(os.environ, {'MCP_SERVER_URL': 'https://example.invalid/sse'}):
            try:
                value = call_create_ticket({'text': 'Принтер', 'request_id': 'mail-key'}, 'fake-token')
            except Exception as exc:
                value = exc
        return value, session, sse

    def test_one_authenticated_call_with_no_retry(self):
        value, session, transport = self.invoke()
        self.assertIsInstance(value, dict)
        session.initialize.assert_awaited_once()
        session.call_tool.assert_awaited_once_with('create-ticket', {'text': 'Принтер', 'request_id': 'mail-key'})
        self.assertEqual(transport.sse_client.call_args.kwargs['headers'], {'Authorization': 'Bearer fake-token'})

    def test_error_or_timeout_never_repeats_a_write(self):
        for error, failure in [(True, None), (False, TimeoutError())]:
            value, session, _ = self.invoke(error=error, failure=failure)
            self.assertIsInstance(value, (RuntimeError, TimeoutError))
            session.call_tool.assert_awaited_once()
