"""Check a running local B API; creates an admin session and writes evidence only."""
import argparse
from datetime import datetime
import ipaddress
import http.cookiejar
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, Request, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.knowledge_builder.effective_export import validate_effective_export
from src.knowledge_builder.report_knowledge import validate_report_knowledge

BASE = 'http://127.0.0.1:8001'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def require(condition, description):
    if not condition:
        raise ValueError(description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New evidence directory; never overwritten')
    parser.add_argument('--base-url', default=BASE, help='Loopback API URL, default port 8001')
    parser.add_argument('--withdrawn-feedback-id', help='Optional previously withdrawn receipt to verify after restart')
    args = parser.parse_args()
    endpoint = urlsplit(args.base_url)
    try:
        local = ipaddress.ip_address(endpoint.hostname or '').is_loopback
    except ValueError:
        local = endpoint.hostname == 'localhost'
    if not local or endpoint.scheme != 'http' or endpoint.username or endpoint.password or endpoint.path not in ('', '/') or endpoint.query or endpoint.fragment:
        parser.error('--base-url must be an HTTP loopback origin without credentials or path')
    base = args.base_url.rstrip('/')
    started_at = datetime.now().astimezone().isoformat()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Evidence directory already exists; do not overwrite it.')
    output.mkdir(parents=True)
    client = build_opener(NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))
    checks = []

    def read(path, query=None):
        suffix = '?' + urlencode(query) if query else ''
        with client.open(base + path + suffix, timeout=120) as response:
            return json.load(response), dict(response.headers)

    def denied(path, expected):
        try:
            read(path)
        except HTTPError as error:
            require(error.code == expected, f'{path}: expected {expected}, got {error.code}')
            checks.append(f'{path}: HTTP {expected} as expected')
        else:
            raise ValueError(f'{path}: request should have been rejected')

    try:
        for path in ('/api/admin/knowledge/effective-export', '/api/admin/knowledge/report-export'):
            denied(path, 401)
        credentials = json.loads((args.state / 'credentials.json').read_text(encoding='utf-8'))
        body = json.dumps({'username': 'admin', 'password': credentials['ADMIN_PASSWORD']}).encode()
        with client.open(Request(base + '/api/admin/sessions', data=body,
                                 headers={'Content-Type': 'application/json'}), timeout=30) as response:
            require(response.status == 200, 'Admin login failed')
            response.read()  # Do not display/save login payload or cookies.
        del credentials, body
        checks.append('Local administrator login: HTTP 200')
        effective, effective_headers = read('/api/admin/knowledge/effective-export')
        validate_effective_export(effective)
        revision = effective['revision']
        report, report_headers = read('/api/admin/knowledge/report-export', {'expected_revision': revision})
        validate_report_knowledge(report)
        tags, tags_headers = read('/api/knowledge/author-tags', {'expected_revision': revision})
        require(report['scope']['knowledge_revision'] == revision, 'Report knowledge revision differs')
        require(tags['knowledge_revision'] == revision, 'Author tags knowledge revision differs')
        require(tags == report['author_tags'], 'Public tags differ from report tags')
        require(report['quality']['counts'] == {key: effective['counts'][key]
                for key in ('papers', 'entities', 'relations')}, 'Report counts differ')
        require(sorted(report['scope']['paper_ids']) == sorted(part['input']['openalex_id']
                for part in effective['papers']), 'Report paper scope differs')
        require(report['knowledge']['revision'] == revision, 'Embedded knowledge revision differs')
        for headers in (effective_headers, report_headers, tags_headers):
            lowered = {key.lower(): value for key, value in headers.items()}
            require(lowered.get('x-knowledge-revision') == revision, 'Version header differs')
            require(lowered.get('cache-control') == 'no-store', 'Missing no-store header')
        checks.append('Effective export and report integrity, paper scope, counts, tags and headers agree')
        for path in ('/api/admin/knowledge/effective-export', '/api/admin/knowledge/report-export', '/api/knowledge/author-tags'):
            denied(path + '?expected_revision=' + '0' * 64, 409)
        selected = next((author for author in tags['authors'] if author['source_id'] and author['tags']), None)
        if selected:
            filtered, _ = read('/api/knowledge/author-tags',
                               {'expected_revision': revision, 'source_id': selected['source_id']})
            require(len(filtered['authors']) == 1 and filtered['authors'][0] == selected,
                    'Exact author selection differs')
            checks.append('Exact stable author ID returns the same supported tags')
        else:
            checks.append('NO SAMPLE: no tagged author with stable source ID; page test needs another dataset')
        unknown, _ = read('/api/knowledge/author-tags', {'source_id': 'test:unknown-author-runtime-verification'})
        require(unknown['authors'] == [], 'Unknown author must not fall back to same-name/all authors')
        if args.withdrawn_feedback_id:
            receipt, _ = read('/api/knowledge/feedback/' + args.withdrawn_feedback_id)
            require(receipt['status'] == 'withdrawn', 'Previously withdrawn feedback did not survive restart')
            checks.append('Specified feedback is withdrawn; restart must be performed by operator')
        else:
            checks.append('NOT RUN: withdrawn feedback persistence (no receipt ID supplied)')
        sync, _ = read('/api/health')
        summary = dict(status='passed', started_at=started_at, finished_at=datetime.now().astimezone().isoformat(),
                       base_url=base, counts=effective['counts'],
                       knowledge_revision=revision, report_revision=report['revision'], checks=checks,
                       graph_sync={key: sync.get('graph_sync', {}).get(key)
                                   for key in ('state', 'revision', 'batch_id', 'error')},
                       author_sample=({key: selected[key] for key in ('source_id', 'names', 'paper_ids')}
                                      if selected else None),
                       limitations=['Does not validate all C graph content or formal A handoff',
                                    'Does not verify every feedback state across restart'])
        for name, document in (('effective', effective), ('report', report), ('author-tags', tags), ('summary', summary)):
            (output / f'{name}.json').write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS: requested runtime checks; inspect summary for NOT RUN/NO SAMPLE items')
        print('Counts:', effective['counts'])
        print('Author sample:', summary['author_sample'])
        print('Evidence:', output)
    except Exception as error:
        # Never print a request, login payload, cookie or arbitrary HTTP body.
        detail = str(error) if isinstance(error, ValueError) else (
            f'HTTP {error.code}' if isinstance(error, HTTPError) else type(error).__name__)
        (output / 'failure.json').write_text(json.dumps({'status': 'failed', 'started_at': started_at, 'finished_at': datetime.now().astimezone().isoformat(), 'error': detail,
                                                       'completed_checks': checks}, indent=2), encoding='utf-8')
        print('FAILED:', detail, '; evidence:', output)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
