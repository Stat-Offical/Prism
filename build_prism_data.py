"""Build the portal from RSS titles, news results and article body text."""
from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlsplit

from news_api import (
    BASE, KST, body_results_log, collection_folder, load_bodies, parse_timestamp, read_jsonl,
    read_pipeline_log, rss_config, update_pipeline_log,
)

WEB = BASE / "web"


def main():
    source = rss_config()
    folder = collection_folder()
    log = read_pipeline_log(folder) if folder else {}
    collection = log.get("collection", {})
    titles = json.loads((folder / "rss_titles.json").read_text(encoding="utf-8")) if folder else []
    rows = read_jsonl(folder / "articles.jsonl") if folder else []
    rss_log = [{"title": title,
                "collection_queries": [search["query"] for search in log.get("api_searches", [])
                                       if title in search.get("rss_titles", [])]}
               for title in titles]
    active = [entry["title"] for entry in rss_log if entry["collection_queries"]]
    bodies = load_bodies()
    articles = []
    for article in rows:
        sources = article.get("rss_titles", [])
        cached = bodies.get(article["article_id"], {})
        body = cached.get("body_text", "") if cached.get("body_status") == "extracted_unverified" else ""
        stamp = parse_timestamp(article.get("pubDate", ""))
        domain = urlsplit(article["originallink"] or article["link"]).hostname or ""
        articles.append({
            "id": article["article_id"], "title": article["title"],
            "summary": article["description"], "url": article["originallink"] or article["link"],
            "imageUrl": cached.get("image_url") or "",
            "publisher": cached.get("publisher_name_extracted") or
                         domain.removeprefix("www."),
            "providedAt": stamp.isoformat() if stamp else "",
            "body": body, "bodyStatus": cached.get("body_status", "not_requested"),
            "bodyRetrievedAt": cached.get("retrieved_at"), "rssTitles": sources,
            "queries": article.get("queries", []),
            "queryRanks": article.get("query_ranks", {}),
        })
    payload = {
        "meta": {"builtAt": datetime.now(KST).isoformat(),
                 "collectedAt": collection.get("finished_at"),
                 "queryMode": collection.get("query_mode"),
                 "source": source},
        "rssTitles": active, "articles": articles,
    }
    WEB.mkdir(exist_ok=True)
    (WEB / "data.js").write_text(
        "window.PRISM_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2).replace("</", "<\\/") + ";\n",
        encoding="utf-8")
    if folder:
        crawl_log = body_results_log(folder)
        update_pipeline_log(
            folder, portal_built_at=payload["meta"]["builtAt"], source=source,
            rss_input_fields=["title"], rss_titles_file="rss_titles.json",
            counts={"rss_items": len(titles), "active_rss_items": len(active),
                    "collected_articles": len(rows), "portal_articles": len(articles),
                    "crawl_results_in_this_folder": len(crawl_log),
                    "portal_articles_with_body": sum(bool(a["body"]) for a in articles)},
            rss_extraction=rss_log, crawling=crawl_log,
        )
    print(json.dumps({"rss_titles": len(active), "articles": len(articles),
                      "articles_with_body": sum(bool(a["body"]) for a in articles)}))


if __name__ == "__main__":
    main()
