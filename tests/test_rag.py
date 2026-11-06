import os
import unittest
from unittest.mock import patch
from src import rag
from src.helpdesk_common import mask_pii
from src import email_poller
from test_email_poller import ENV


class RagTests(unittest.TestCase):
    @patch.dict(os.environ, {**ENV, "RAG_SCORE_THRESHOLD": "0.35"})
    def test_one_index_with_bounded_results(self):
        tool = rag.search_tool()
        self.assertEqual(tool["vector_store_ids"], ["test-index"])
        self.assertEqual(tool["max_num_results"], 5)
        for invalid in ("first,second", "first second", ""):
            with patch.dict(os.environ, {"SEARCH_INDEX_ID": invalid}):
                with self.assertRaises(ValueError):
                    rag.search_tool()
        with patch.dict(os.environ, {"RAG_SCORE_THRESHOLD": "1.1"}):
            with self.assertRaises(ValueError):
                rag.search_tool()

    def test_trace_masks_queries_and_omits_document_text(self):
        trace = rag.search_trace({"type": "file_search_call",
                                  "queries": ["VPN a@b.ru token=secret"],
                                  "results": [{"filename": "vpn.md", "file_id": "file-1",
                                               "score": 0.8, "text": "Private fragment"}]}, mask_pii)
        self.assertEqual(trace["queries"], ["VPN [email] token=[SECRET]"])
        self.assertNotIn("text", trace["results"][0])

    @patch.dict(os.environ, ENV)
    def test_live_answer_shape_preserves_search_and_verified_sources(self):
        data = {"status": "completed", "output": [
            {"type": "file_search_call", "status": "completed", "queries": ["командировка"],
             "results": [{"filename": "business-travel.md", "file_id": "file-1", "score": 0.9}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text",
             "text": "По учебному регламенту согласуйте поездку с руководителем.\nДокумент: business-travel.md",
             "annotations": [{"type": "file_citation", "filename": "business-travel.md",
                              "file_id": "file-1"},
                             {"type": "file_citation", "filename": "unknown.md"},
                             {"type": "file_citation", "filename": "account-access.md"}]}]},
        ], "usage": {"input_tokens": 100, "output_tokens": 40}}
        with patch.object(email_poller, "request_json", return_value=data) as request:
            result = email_poller.agent_answer("Как оформить командировку?", "fake", "test@example.org", [])
        tools = request.call_args.kwargs["data"]["tools"]
        self.assertEqual(sum(t["type"] == "file_search" for t in tools), 1)
        self.assertEqual(sum(t["type"] == "mcp" for t in tools), 1)
        self.assertEqual(result["searches"][0]["queries"], ["командировка"])
        self.assertEqual(len(result["sources"]), 1)
        self.assertIn("/knowledge-base/business-travel.md", result["text"])
        self.assertNotIn("unknown.md", result["text"])
        self.assertIsNone(result["ticket_id"])

    def test_no_citation_does_not_invent_source(self):
        self.assertEqual(rag.cited_sources({"output": []}), [])
        self.assertEqual(rag.add_source_links("Не знаю", []), "Не знаю")

    def test_annotations_on_unknown_answer_are_not_published(self):
        response = {"output": [{"type": "message", "role": "assistant", "content": [{
            "type": "output_text", "text": "Не знаю: в базе нет информации. Могу создать заявку.",
            "annotations": [{"type": "file_citation", "filename": "vacation.md"}],
        }]}]}
        self.assertEqual(rag.cited_sources(response), [])

    def test_check_accepts_ticket_synonym_and_rejects_unrelated_sources(self):
        from scripts.check_rag import validate_results
        checks = {
            "known": {"searches": [{}], "ticket_id": None,
                      "sources": [{"filename": "business-travel.md"}]},
            "unknown": {"searches": [{}], "ticket_id": None, "sources": [],
                        "text": "Не знаю: в базе знаний нет этой информации. Могу создать заявку."},
        }
        validate_results(checks)
        checks["unknown"]["sources"] = [{"filename": "vacation.md"}]
        with self.assertRaises(AssertionError):
            validate_results(checks)


if __name__ == "__main__":
    unittest.main()
