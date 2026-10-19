"""Naver API requests, article deduplication and cached result files."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from news_transport import fetch, load_env, redact

BASE = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
TRACKING_KEYS = {'fbclid', 'gclid', 'nclick', 'nclicks'}


def api_config() -> tuple[str, dict[str, str]]:
    load_env(BASE / '.env')
    provider = os.environ.get('NAVER_API_PROVIDER', 'developers')
    client_id = os.environ.get('NAVER_CLIENT_ID', '')
    secret = os.environ.get('NAVER_CLIENT_SECRET', '')
    if provider == 'ncp':
        return 'https://naverapihub.apigw.ntruss.com/search/v1/news', {
            'X-NCP-APIGW-API-KEY-ID': client_id, 'X-NCP-APIGW-API-KEY': secret}
    if provider == 'developers':
        return 'https://openapi.naver.com/v1/search/news.json', {
            'X-Naver-Client-Id': client_id, 'X-Naver-Client-Secret': secret}
    raise ValueError('NAVER_API_PROVIDER must be ncp or developers')


def rss_config() -> dict[str, str]:
    load_env(BASE / '.env')
    keys = {'url': 'RSS_URL', 'publisher': 'RSS_PUBLISHER', 'country': 'RSS_COUNTRY'}
    source = {key: os.environ.get(name, '').strip() for key, name in keys.items()}
    missing = [name for key, name in keys.items() if not source[key]]
    if missing:
        raise ValueError('Missing RSS settings in .env: ' + ', '.join(missing))
    return source


def clean_text(text: str) -> str:
    return html.unescape(re.sub(r'<[^>]*>', '', text or '')).strip()


def parse_timestamp(value: str) -> datetime | None:
    try:
        result = parsedate_to_datetime(value)
        return result.astimezone(KST) if result.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def canonical_url(value: str) -> str:
    parts = urlsplit(html.unescape(value.strip()))
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in TRACKING_KEYS]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ''))


def article_alias(value: str) -> str:
    url = canonical_url(value)
    parts = urlsplit(url)
    if parts.hostname and (parts.hostname == 'naver.com' or parts.hostname.endswith('.naver.com')):
        match = re.search(r'/(?:mnews/)?article/(\d+)/(\d+)', parts.path)
        params = dict(parse_qsl(parts.query))
        if match:
            return 'naver:' + ':'.join(match.groups())
        if params.get('oid') and params.get('aid'):
            return 'naver:' + params['oid'] + ':' + params['aid']
    return url


class Corpus:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.aliases: dict[str, str] = {}

    def add(self, item: dict, query: str, rank: int) -> None:
        links = [item.get('originallink', ''), item.get('link', '')]
        aliases = {article_alias(url) for url in links if url}
        if not aliases:
            return  # Raw response still retains this unusable result.
        previous = {self.aliases[alias] for alias in aliases if alias in self.aliases}
        if previous:
            chosen = sorted(previous)[0]
            row = self.rows[chosen]
            for duplicate in previous - {chosen}:
                other = self.rows.pop(duplicate)
                row['queries'] = sorted(set(row['queries']) | set(other['queries']))
                for matched_query, position in other['query_ranks'].items():
                    row['query_ranks'][matched_query] = min(row['query_ranks'].get(matched_query, position), position)
                for alias, owner in list(self.aliases.items()):
                    if owner == duplicate:
                        self.aliases[alias] = chosen
        else:
            chosen = hashlib.sha256(sorted(aliases)[0].encode()).hexdigest()[:20]
            row = self.rows[chosen] = {
                'article_id': chosen, 'title': clean_text(item.get('title', '')),
                'description': clean_text(item.get('description', '')),
                'originallink': item.get('originallink', ''), 'link': item.get('link', ''),
                'pubDate': item.get('pubDate', ''), 'queries': [], 'query_ranks': {},
            }
        row['queries'] = sorted(set(row['queries']) | {query})
        row['query_ranks'][query] = min(row['query_ranks'].get(query, rank), rank)
        for alias in aliases:
            self.aliases[alias] = chosen


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def read_jsonl(path: Path) -> list[dict]:
    # str.splitlines() splits U+2028/U+2029 inside valid JSON strings.
    # JSONL records are separated by physical newline bytes.
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def read_pipeline_log(folder: Path) -> dict:
    path = folder / 'pipeline_log.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def update_pipeline_log(folder: Path, **sections) -> None:
    log = read_pipeline_log(folder)
    log.update(sections)
    log['updated_at'] = datetime.now(KST).isoformat()
    write_json(folder / 'pipeline_log.json', log)


def body_results_log(folder: Path) -> list[dict]:
    entries = []
    for path in sorted((folder / 'bodies').glob('*.json')):
        result = json.loads(path.read_text(encoding='utf-8'))
        entries.append({
            **{key: result.get(key) for key in
               ('article_id', 'title', 'requested_url', 'fetched_url', 'retrieved_at',
                'reprocessed_at', 'processing_mode', 'body_status', 'body_character_count',
                'robots_result', 'http_status', 'http_requests', 'error')},
            'result_file': path.relative_to(folder).as_posix(),
            'html_file': path.with_suffix('.html').relative_to(folder).as_posix()
                         if path.with_suffix('.html').exists() else None,
        })
    return entries


def collection_folder(value: str | None = None) -> Path | None:
    root = (BASE / 'data').resolve()
    if value is None:
        pointer = root / 'latest_prism_news.txt'
        if not pointer.exists():
            return None
        value = pointer.read_text(encoding='utf-8').strip()
    folder = (root / value).resolve()
    if folder.parent != root:
        raise ValueError('Collection folder must be inside project/news/data')
    return folder


def load_bodies() -> dict[str, dict]:
    """Reuse body results across news snapshots, preferring extracted text."""
    bodies = {}
    for path in (BASE / 'data').glob('*/bodies/*.json'):
        body = json.loads(path.read_text(encoding='utf-8'))
        article_id = body['article_id']
        previous = bodies.get(article_id, {})
        rank = lambda row: (row.get('body_status') == 'extracted_unverified',
                            row.get('retrieved_at', ''))
        if not previous or rank(body) > rank(previous):
            bodies[article_id] = body
    return bodies


def export_corpus(path: Path, corpus: Corpus) -> None:
    rows = sorted(corpus.rows.values(),
                  key=lambda row: parse_timestamp(row.get('pubDate', '')) or datetime.min.replace(tzinfo=KST),
                  reverse=True)
    with (path / 'articles.jsonl').open('w', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def search_request(query: str, start: int, endpoint: str, *,
                   display: int = 100, sort: str = 'date') -> dict:
    parameters = {'query': query, 'display': display, 'start': start, 'sort': sort, 'format': 'json'}
    return {'method': 'GET', 'url': endpoint + '?' + urlencode(parameters), 'parameters': parameters}


def query_api(query: str, start: int, headers: dict, endpoint: str, *,
              display: int = 100, sort: str = 'date') -> dict:
    url = search_request(query, start, endpoint, display=display, sort=sort)['url']
    for attempt in range(3):
        response = fetch(url, headers=headers)
        if response['status'] == 200:
            return json.loads(response['body'].decode('utf-8'))
        if response['status'] == 429 or response['status'] >= 500:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
        detail = redact(response['body'].decode('utf-8', errors='replace')[:1000])
        raise RuntimeError(f"Naver HTTP {response['status']}: {detail}")
    raise RuntimeError('Retry attempts exhausted')
