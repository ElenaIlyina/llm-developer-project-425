"""One search index, safe trace metadata and verified source links."""
import json
import os
import re
from pathlib import Path


def search_tool():
    index_id = os.environ["SEARCH_INDEX_ID"].strip()
    if not index_id or any(char.isspace() or char == "," for char in index_id):
        raise ValueError("SEARCH_INDEX_ID must contain one nonempty index ID")
    threshold = float(os.environ.get("RAG_SCORE_THRESHOLD", "0.35"))
    if not 0 <= threshold <= 1:
        raise ValueError("RAG_SCORE_THRESHOLD must be in [0, 1]")
    return {
        "type": "file_search", "vector_store_ids": [index_id],
        "max_num_results": 5,
        "ranking_options": {"score_threshold": threshold},
    }


def search_trace(item, mask):
    return {
        "id": item.get("id"), "status": item.get("status"),
        "queries": [mask(str(query))[:500] for query in item.get("queries", [])],
        "results": [{"file_id": result.get("file_id"),
                     "filename": result.get("filename"), "score": result.get("score")}
                    for result in (item.get("results") or [])],
    }


def cited_sources(response):
    with Path(__file__).with_name("knowledge_sources.json").open(encoding="utf-8") as source:
        catalog = json.load(source)
    sources = {}
    for item in response.get("output", []):
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        for part in item.get("content", []):
            # Yandex can annotate all retrieved files, including irrelevant ones.
            # Publish only sources the answer explicitly identifies as its basis.
            references = re.findall(
                r"^(?:Документ|Источник)\s*:\s*(.+)$",
                part.get("text", ""), flags=re.MULTILINE | re.IGNORECASE,
            )
            for annotation in part.get("annotations", []):
                if annotation.get("type") != "file_citation":
                    continue
                filename = annotation.get("filename", "")
                explicitly_cited = filename and any(
                    re.search(r"(?<![\w.-])" + re.escape(filename) + r"(?![\w.-])", line)
                    for line in references
                )
                if filename in catalog and explicitly_cited:
                    sources[filename] = {"filename": filename,
                                         "file_id": annotation.get("file_id"),
                                         **catalog[filename]}
    return list(sources.values())


def add_source_links(answer, sources):
    if not sources:
        return answer
    lines = [source["title"] + " — " + source["url"] for source in sources]
    return answer + "\n\nИсточники (учебная база):\n" + "\n".join(lines)
