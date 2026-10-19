"""Extract article bodies for the current Prism news snapshot."""
from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import trafilatura
from lxml import html as lxml_html
from trafilatura.utils import decode_file

from news_api import (
    BASE, KST, body_results_log, collection_folder, load_bodies, read_jsonl,
    update_pipeline_log, write_json,
)
from news_transport import fetch, load_env, redact

AGENT = 'PrismNewsPilot/0.1'
REDIRECTS = {301, 302, 303, 307, 308}
BODY_SELECTORS = {
    'tbc.co.kr': "//*[@id='article_body']",
    'news1.kr': "//*[@id='articleBodyContent']",
}


def public_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return False
    if parts.username or parts.password or parts.hostname.lower() == 'localhost':
        return False
    try:
        return ipaddress.ip_address(parts.hostname).is_global
    except ValueError:
        return not parts.hostname.lower().endswith(('.local', '.internal', '.localhost'))


def select_articles(rows, limit):
    selected, domains = [], Counter()
    for row in rows:
        domain = urlsplit(row['originallink'] or row['link']).hostname
        if domains[domain] >= 3:
            continue
        selected.append(row)
        domains[domain] += 1
        if len(selected) == limit:
            break
    return selected


def representative_image(tree, url):
    for name in ('og:image:secure_url', 'og:image', 'twitter:image', 'twitter:image:src'):
        for value in tree.xpath(f'//meta[@property="{name}" or @name="{name}"]/@content'):
            image_url = urljoin(url, value.strip())
            if value.strip() and public_url(image_url):
                return image_url
    return None


def parse_body(payload, url):
    payload = decode_file(payload)
    tree = lxml_html.fromstring(payload)
    image_url = representative_image(tree, url)
    extracted = trafilatura.extract(
        payload, url=url, output_format='json', with_metadata=True,
        include_comments=False, include_tables=True)
    document = json.loads(extracted) if extracted else {}
    text = document.get('text', '').strip()
    selector = BODY_SELECTORS.get((urlsplit(url).hostname or '').removeprefix('www.'))
    if selector:
        nodes = tree.xpath(selector)
        text = ''
        if nodes:
            content = nodes[0]
            for noise in content.xpath('.//script|.//style|.//figure|.//nav|.//aside'):
                noise.drop_tree()
            for block in content.xpath('.//br|.//p|.//div'):
                block.tail = '\n' + (block.tail or '')
            text = '\n'.join(line.strip() for line in content.text_content().splitlines() if line.strip())
    links = {urljoin(url, value) for value in tree.xpath('//a/@href')}
    return {
        'body_status': ('extracted_unverified' if len(text) >= 200 else
                        'short_text_review' if text else 'extraction_failed'),
        'body_text': text, 'body_character_count': len(text),
        'image_url': image_url,
        'publisher_date_extracted': document.get('date'),
        'extracted_title': document.get('title'),
        'publisher_name_extracted': next(iter(tree.xpath('//meta[@property="og:site_name"]/@content')), None) or document.get('sitename'),
        'extraction_library': 'trafilatura',
        'extraction_method': 'publisher_dom' if selector else 'trafilatura',
        'kosis_links': sorted(link for link in links if
            (urlsplit(link).hostname or '').lower() == 'kosis.kr' or
            (urlsplit(link).hostname or '').lower().endswith('.kosis.kr')),
    }


def extract_body(row, storage, request, allowed):
    result = {
        'article_id': row['article_id'], 'title': row['title'],
        'requested_url': row['originallink'] or row['link'],
        'retrieved_at': datetime.now(KST).isoformat(),
        'body_status': 'pending', 'source_usage_verified': False,
        'processing_mode': 'http', 'http_requests': [],
    }
    url = result['requested_url']
    try:
        for _ in range(6):
            if not public_url(url):
                result['body_status'] = 'unsafe_url_skipped'
                break
            permitted, reason = allowed(url)
            result['robots_result'] = reason
            if not permitted:
                result['body_status'] = reason
                break
            attempt = {'url': url, 'requested_at': datetime.now(KST).isoformat()}
            result['http_requests'].append(attempt)
            response = request(url)
            attempt.update(http_status=response['status'], finished_at=datetime.now(KST).isoformat())
            result['http_status'], result['fetched_url'] = response['status'], url
            if response['status'] in REDIRECTS:
                url = urljoin(url, response['location'])
                continue
            if response['status'] != 200:
                result['body_status'] = 'http_error'
                break
            if len(response['body']) > 5_000_000:
                result['body_status'] = 'page_too_large'
                break
            if response.get('content_type') and 'html' not in response['content_type'].lower():
                result['body_status'] = 'unsupported_content'
                break
            (storage / (row['article_id'] + '.html')).write_bytes(response['body'])
            result.update(parse_body(response['body'], url))
            break
        else:
            result['body_status'] = 'too_many_redirects'
    except Exception as exc:
        result.update(body_status='fetch_or_extract_error', error=redact(str(exc))[:600])
        if result['http_requests'] and 'finished_at' not in result['http_requests'][-1]:
            result['http_requests'][-1].update(error=result['error'], finished_at=datetime.now(KST).isoformat())
    result['finished_at'] = datetime.now(KST).isoformat()
    return result


def main(args):
    load_env(BASE / '.env')
    folder = collection_folder(args.run)
    if folder is None:
        raise ValueError('Collect news before fetching article bodies.')
    corpus = read_jsonl(folder / 'articles.jsonl')
    cached = load_bodies()
    storage = folder / 'bodies'
    storage.mkdir(exist_ok=True)
    if args.reextract:
        selected = [row for row in corpus if (storage / (row['article_id'] + '.html')).exists()][:args.limit]
    else:
        pending = [row for row in corpus if row['article_id'] not in cached or
                   (args.retry_failed and cached[row['article_id']]['body_status'] != 'extracted_unverified')]
        selected = select_articles(pending, args.limit)
    robots_cache, last_request = {}, {}

    def request(url):
        origin = urlsplit(url).netloc
        time.sleep(max(0, 1 - (time.monotonic() - last_request.get(origin, 0))))
        response = fetch(url, headers={'User-Agent': AGENT}, timeout=20)
        last_request[origin] = time.monotonic()
        return response

    def allowed(url):
        parts = urlsplit(url)
        origin = parts.scheme + '://' + parts.netloc
        if origin not in robots_cache:
            robots_url = origin + '/robots.txt'
            response = request(robots_url)
            for _ in range(4):
                if response['status'] not in REDIRECTS:
                    break
                robots_url = urljoin(robots_url, response['location'])
                if not public_url(robots_url):
                    return False, 'robots_redirect_unsafe'
                response = request(robots_url)
            if response['status'] == 404:
                robots_cache[origin] = (None, 'robots_not_found')
            elif response['status'] != 200:
                robots_cache[origin] = (False, 'robots_unavailable')
            else:
                text = response['body'].decode('utf-8', errors='replace')
                if '<html' in text.lower() or '<!doctype' in text.lower():
                    robots_cache[origin] = (False, 'robots_unparseable')
                else:
                    parser = RobotFileParser()
                    parser.parse(text.splitlines())
                    robots_cache[origin] = (parser, 'robots_checked')
        parser, reason = robots_cache[origin]
        if parser is False:
            return False, reason
        if parser is None or parser.can_fetch(AGENT, url):
            return True, reason
        return False, 'robots_disallowed'

    for index, row in enumerate(selected, 1):
        if args.reextract:
            result = json.loads((storage / (row['article_id'] + '.json')).read_text(encoding='utf-8'))
            result.update(parse_body((storage / (row['article_id'] + '.html')).read_bytes(),
                                    result.get('fetched_url') or result['requested_url']))
            result['reprocessed_at'] = datetime.now(KST).isoformat()
            result['processing_mode'] = 'cached_html'
        else:
            result = extract_body(row, storage, request, allowed)
        write_json(storage / (row['article_id'] + '.json'), result)
        cached[row['article_id']] = result
        print(json.dumps({'progress': f'{index}/{len(selected)}',
                          'article_id': row['article_id'], 'status': result['body_status']}), flush=True)
    outputs = [cached[row['article_id']] for row in corpus if row['article_id'] in cached]
    counts = dict(Counter(row['body_status'] for row in outputs))
    update_pipeline_log(folder, body_processing={
        'finished_at': datetime.now(KST).isoformat(), 'attempted_this_run': len(selected),
        'mode': 'cached_html' if args.reextract else 'http',
        'total_articles': len(corpus), 'stored_results': len(outputs), 'statuses': counts,
        'full_body_completeness_verified': False,
        'selection': ('Saved HTML in corpus order.' if args.reextract else
                      'Newest unprocessed candidates, at most 3 per publisher domain.'),
    }, crawling=body_results_log(folder))
    if not args.no_build:
        subprocess.run([sys.executable, '-B', str(BASE / 'build_prism_data.py')], check=True)
    print(json.dumps({'attempted': len(selected), 'statuses': counts}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', help='Collection folder; defaults to latest_prism_news.txt')
    parser.add_argument('--limit', type=int, default=24)
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--reextract', action='store_true', help='Re-extract saved HTML without network requests')
    parser.add_argument('--no-build', action='store_true')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('limit must be positive')
    main(args)
