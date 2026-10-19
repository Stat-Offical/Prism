"""Collect Naver news candidates using each RSS title and its publisher."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from news_api import (
    BASE, KST, Corpus, api_config, clean_text, export_corpus, query_api, rss_config,
    search_request, update_pipeline_log, write_json,
)
from news_transport import fetch, redact


def parse_rss(payload: bytes) -> list[str]:
    titles = []
    seen = set()
    for item in ET.fromstring(payload).findall(".//item"):
        title = clean_text(item.findtext("title", ""))
        if title and title not in seen:
            titles.append(title)
            seen.add(title)
    return titles


def attach_provenance(corpus: Corpus, rss_queries: dict[str, str]) -> None:
    for article in corpus.rows.values():
        article["rss_titles"] = sorted(title for title, query in rss_queries.items()
                                       if query in article["queries"])


def collect(*, limit: int = 10, per_release: int = 30, rebuild: bool = True) -> Path:
    endpoint, headers = api_config()
    if not all(headers.values()):
        raise RuntimeError("NAVER_CLIENT_ID and NAVER_CLIENT_SECRET are required.")
    source = rss_config()
    started = datetime.now(KST)
    folder = BASE / "data" / started.strftime("news_%Y%m%d_%H%M%S_%f")
    folder.mkdir(parents=True)
    (folder / "raw").mkdir()
    collection = {
        "status": "running", "started_at": started.isoformat(), "feed": source["url"],
        "query_mode": "rss_title_publisher", "api": endpoint, "per_release": per_release,
        "rss_fields": ["title"],
        "unique_articles": 0,
        "source_use_verified": False, "article_bodies_collected": False,
    }
    searches = []
    corpus = Corpus()
    update_pipeline_log(folder, collection=collection, api_searches=searches)
    try:
        response = fetch(source["url"], {"User-Agent": "PrismNewsPilot/0.1"})
        if response["status"] != 200:
            raise RuntimeError(f'RSS HTTP {response["status"]}')
        titles = parse_rss(response["body"])[:limit]
        if not titles:
            raise RuntimeError("The selected RSS feed contains no usable press releases.")
        write_json(folder / "rss_titles.json", titles)
        rss_queries = {title: f"{title} {source['publisher']}" for title in titles
                       if not re.search(r"개최|채용|모집|워크숍|세미나|포럼", title)}
        queries = list(dict.fromkeys(rss_queries.values()))
        for index, query in enumerate(queries, 1):
            result = {"query": query, "status": "pending", "returned_items": 0,
                      "requested_at": datetime.now(KST).isoformat(),
                      "log_file": None,
                      "rss_titles": [title for title, value in rss_queries.items() if query == value],
                      "request": search_request(query, 1, endpoint, display=per_release, sort="sim")}
            payload = None
            searches.append(result)
            update_pipeline_log(folder, collection=collection, api_searches=searches)
            try:
                payload = query_api(query, 1, headers, endpoint, display=per_release, sort="sim")
                for rank, item in enumerate(payload.get("items", []), 1):
                    if not clean_text(item.get("title", "")):
                        continue
                    if urlsplit(item.get("originallink") or item.get("link", "")).scheme not in {"http", "https"}:
                        continue
                    corpus.add(item, query, rank)
                result.update(status="success", returned_items=len(payload.get("items", [])),
                              total_reported=payload.get("total", 0))
                print(json.dumps({"query": index, "returned": result["returned_items"],
                                  "unique_so_far": len(corpus.rows)}), flush=True)
            except Exception as exc:
                result.update(status="failed", error=redact(str(exc)))
                if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                    raise
            finally:
                result["finished_at"] = datetime.now(KST).isoformat()
                if payload is not None:
                    result["log_file"] = f"raw/{index:02d}.json"
                    write_json(folder / result["log_file"], {"query": query, "response": payload})
                collection["unique_articles"] = len(corpus.rows)
                update_pipeline_log(folder, collection=collection, api_searches=searches)
        attach_provenance(corpus, rss_queries)
        export_corpus(folder, corpus)
        collection.update(
            status="partial" if any(q["status"] == "failed" for q in searches) else "complete",
            finished_at=datetime.now(KST).isoformat(), unique_articles=len(corpus.rows),
        )
        if not corpus.rows:
            raise RuntimeError("No news candidates were returned; the previous homepage pool is retained.")
        update_pipeline_log(folder, collection=collection, api_searches=searches)
        (BASE / "data" / "latest_prism_news.txt").write_text(folder.name, encoding="utf-8")
        if rebuild:
            subprocess.run([sys.executable, "-B", str(BASE / "build_prism_data.py")], check=True)
        return folder
    except Exception as exc:
        collection.update(status="failed", error=redact(str(exc)), unique_articles=len(corpus.rows),
                          finished_at=datetime.now(KST).isoformat())
        update_pipeline_log(folder, collection=collection, api_searches=searches)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--per-release", type=int, default=30)
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 50 or not 1 <= args.per_release <= 100:
        parser.error("limit must be 1..50 and per-release must be 1..100")
    try:
        folder = collect(limit=args.limit, per_release=args.per_release, rebuild=not args.no_build)
    except Exception as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 1
    print("Saved RSS-title news search: " + str(folder))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
