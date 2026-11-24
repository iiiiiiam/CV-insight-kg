"""Freeze A metadata, then assemble versioned Markdown/HTML/CSV/JSON report bundles."""
import csv
from collections import Counter
import hashlib
import html
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from sqlalchemy import select

from .models import (BatchLedger, BatchPaperVersion, Job, Paper,
                     PaperSource, StablePaper)
from .paper_quality import research_paper_scope
from .paths import configured_path
from .workflow_tasks import digest, encode


def artifact_root():
    return configured_path('A_REPORT_ROOT', 'data/report-tasks')


def snapshot(db, scope):
    batch_ids = sorted(set(scope.get('batch_ids', [])))
    venues, years = scope.get('venues', []), scope.get('years', [])
    paper_ids = set(scope.get('paper_ids', []))
    batches, selected = [], {}
    if batch_ids:
        for identifier in batch_ids:
            job = db.get(Job, identifier)
            if job is None:
                raise LookupError(f'未找到批次 {identifier}')
            if job.status in ('running', 'queued'):
                raise ValueError('选中批次仍在运行，请完成后再创建报告')
            from .data_overview import handoff
            manifest = handoff(db, job)
            batches.append({key: manifest.get(key) for key in
                ('batch_id', 'batch_code', 'batch_revision', 'state', 'status', 'counts')})
            if db.get(BatchLedger, identifier) is None:
                raise ValueError('历史批次缺少冻结版本，请改用当前有效论文范围')
            for version in db.scalars(select(BatchPaperVersion).where(BatchPaperVersion.job_id == identifier)):
                content = json.loads(version.content_json)
                paper = content['paper']
                if venues and paper['venue'] not in venues or years and paper['year'] not in years:
                    continue
                identity = db.get(StablePaper, version.paper_id)
                selected[version.paper_id] = _paper(paper, identity.stable_id, content['sources'])
    else:
        query = select(Paper).where(research_paper_scope()).order_by(Paper.id)
        if venues:
            query = query.where(Paper.venue.in_(venues))
        if years:
            query = query.where(Paper.year.in_(years))
        for paper in db.scalars(query):
            identity = db.get(StablePaper, paper.id)
            sources = [{'source': s.source, 'source_id': s.source_id,
                        'source_url': _source_url(s), 'raw': json.loads(s.raw_json)}
                       for s in db.scalars(select(PaperSource).where(PaperSource.paper_id == paper.id)
                                           .order_by(PaperSource.id))]
            value = {key: getattr(paper, key) for key in
                ('title', 'year', 'venue', 'openalex_id', 'doi', 'abstract', 'source_url', 'cited_by_count')}
            value['authors'] = json.loads(paper.authors_json)
            selected[paper.id] = _paper(value, identity.stable_id if identity else paper.canonical_key, sources)
    papers = sorted((p for p in selected.values() if not paper_ids or p['paper_id'] in paper_ids),
                    key=lambda p: p['paper_id'])
    if paper_ids and {p['paper_id'] for p in papers} != paper_ids:
        raise ValueError('部分选中论文不在当前范围或已撤回，请刷新论文列表后重试')
    from .operations import quality
    coverage = [c for c in quality(db)['coverage']
                if (not venues or c.get('venue') in venues) and (not years or c.get('year') in years)]
    frozen = dict(mode='selected_batches_historical' if batch_ids else 'current_effective',
                  scope=scope, batches=batches, papers=papers, coverage=coverage)
    frozen['revision'] = digest(frozen)
    return frozen


def _source_url(source):
    if source.source_url:
        return source.source_url
    try:
        raw = json.loads(source.raw_json)
        return raw.get('source_url') or raw.get('id')
    except (ValueError, AttributeError):
        return None


def _paper(value, stable_id, sources):
    result = {key: value.get(key) for key in
        ('title', 'year', 'venue', 'openalex_id', 'doi', 'abstract', 'source_url', 'cited_by_count')}
    result['authors'] = value.get('authors', [])
    result['stable_id'] = stable_id
    result['paper_id'] = result['openalex_id'] or stable_id
    result['sources'] = [{key: s.get(key) for key in ('source', 'source_id', 'source_url')} |
                         {'raw_sha256': digest(s.get('raw'))} for s in sources]
    return result


def b_knowledge(section):
    data = section['data']
    if data.get('format_version') == 'knowledge-report/1':
        return data.get('knowledge')
    return data if data.get('format_version') == 'knowledge-effective/1.0' else None


def validate_sections(frozen, sections):
    providers = [s['provider'] for s in sections]
    if len(providers) != len(set(providers)):
        raise ValueError('每个提供方只能提交一个固定版本的报告数据')
    native_b = next((s for s in sections if s['provider'] == 'B' and b_knowledge(s)), None)
    ids = {p['paper_id'] for p in frozen['papers']}
    for section in sections:
        if set(section['paper_ids']) != ids or len(section['paper_ids']) != len(ids):
            raise ValueError(f"{section['provider']} 的论文范围与 A 报告范围不一致")
        if section['provider'] == 'B' and section['data'].get('format_version') == 'knowledge-report/1':
            from src.knowledge_builder.report_knowledge import validate_report_knowledge
            try:
                validate_report_knowledge(section['data'])
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError('B 报告知识附件校验失败，请重新读取完整附件') from exc
        if section['provider'] == 'B' and b_knowledge(section) is not None:
            from src.knowledge_builder.effective_export import validate_effective_export
            knowledge = b_knowledge(section)
            validate_effective_export(knowledge)
            if section['revision'] != knowledge['revision']:
                raise ValueError('B 报告数据版本与有效知识快照不一致')
            actual = {p['input']['openalex_id'] for p in knowledge['papers']}
            if actual != ids:
                raise ValueError('B 有效知识快照的实际论文与报告范围不一致')
            by_id = {p['paper_id']: p for p in frozen['papers']}
            for part in knowledge['papers']:
                paper = by_id[part['input']['openalex_id']]
                if any(part['input'].get(key) != paper.get(key) for key in ('title', 'abstract', 'year', 'venue')):
                    raise ValueError('B 的论文内容版本与 A 冻结版本不一致')
        if section['provider'] == 'C' and section['data'].get('statistics') is not None:
            statistics = section['data']['statistics']
            if (statistics.get('paper_count') != len(ids) or
                statistics.get('batch_id') != section['data'].get('batch_id') or
                section['data'].get('batch_id') != 'effective-' + section['revision']):
                raise ValueError('C 的统计数量或发布批次与报告版本不一致')
            if native_b and section['revision'] != native_b['revision']:
                raise ValueError('B 知识与 C 统计不是同一版本')


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def csv_bytes(rows, fields):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        value = {}
        for key in fields:
            item = row.get(key)
            if isinstance(item, (dict, list)):
                item = encode(item)
            if isinstance(item, str) and item.lstrip().startswith(('=', '+', '-', '@')):
                item = "'" + item
            value[key] = item
        writer.writerow(value)
    return ('\ufeff' + output.getvalue()).encode()


def a_summary(frozen, quality):
    """Summarize exactly the frozen report scope and its selected batch receipts."""
    papers = frozen['papers']
    total = len(papers)
    conferences = Counter((paper['venue'], paper['year']) for paper in papers)
    sources = {}
    for paper in papers:
        for source in paper['sources']:
            sources.setdefault(source['source'], set()).add(paper['paper_id'])
    changes = None
    if frozen['batches']:
        changes = {key: sum((batch.get('counts') or {}).get(key, 0) for batch in frozen['batches'])
                   for key in ('added', 'duplicate', 'updated', 'withdrawn', 'failed')}
    return dict(format_version='a-report-summary/1', a_revision=frozen['revision'],
        scope_mode=frozen['mode'], scope=frozen['scope'], paper_count=total,
        conference_years=[dict(venue=venue, year=year, paper_count=count)
                          for (venue, year), count in sorted(conferences.items())],
        sources=[dict(source=name, paper_count=len(ids)) for name, ids in sorted(sources.items())],
        field_quality={field: dict(complete=complete, missing=total-complete,
                                  completeness_ratio=round(complete/total, 6) if total else None)
                       for field, complete in quality['complete'].items()},
        selected_batch_count=len(frozen['batches']), batch_changes=changes,
        batch_changes_basis='selected_batches_full_receipts' if changes is not None else 'no_batches_selected',
        formal_collection_coverage=frozen.get('coverage', []))


def summary_markdown(summary):
    mode = '所选批次历史论文' if summary['scope_mode'] == 'selected_batches_historical' else '当前有效论文'
    lines = ['# 数据概述', '', f'本报告包含 {summary["paper_count"]} 篇{mode}。', '',
             '## 会议与年份', '', '| 会议 | 年份 | 论文数 |', '| --- | ---: | ---: |']
    lines.extend(f'| {row["venue"]} | {row["year"]} | {row["paper_count"]} |'
                 for row in summary['conference_years'])
    lines.extend(['', '## 数据来源', '', '按来源覆盖的唯一论文数统计，同一篇论文可以有多个来源。'])
    lines.extend(f'- {row["source"]} 覆盖 {row["paper_count"]} 篇。' for row in summary['sources'])
    lines.extend(['', '## 字段完整度', '', '| 字段 | 完整篇数 | 缺失篇数 | 完整率 |', '| --- | ---: | ---: | ---: |'])
    labels = {'abstract': '摘要', 'doi': 'DOI', 'authors': '作者', 'sources': '来源记录'}
    for field, value in summary['field_quality'].items():
        ratio = f'{value["completeness_ratio"]:.2%}' if value['completeness_ratio'] is not None else '无论文'
        lines.append(f'| {labels[field]} | {value["complete"]} | {value["missing"]} | {ratio} |')
    lines.extend(['', '## 批次处理汇总', ''])
    changes = summary['batch_changes']
    if changes is None:
        lines.append('本次按论文范围生成报告，未指定导入批次。批次处理汇总未纳入本报告。')
    else:
        lines.append(f'共选择 {summary["selected_batch_count"]} 个批次，按这些批次的完整回执累计统计。')
        lines.append('批次可以包含相同论文，这些累计次数与报告的去重论文数分别计算。')
        names = {'added': '新增', 'duplicate': '重复', 'updated': '更新', 'withdrawn': '撤回关联', 'failed': '失败来源记录'}
        lines.extend(f'- {names[key]} {value}。' for key, value in changes.items())
    lines.extend(['', f'数据版本 `{summary["a_revision"]}`。', ''])
    return '\n'.join(lines)


def readable_html(title, markdown):
    """Render the generated, escaped report without scripts or external resources."""
    blocks, code, table = [], [], []
    in_code = False
    def flush_table():
        if table:
            rows = []
            for index, row in enumerate(table):
                cells = [s.strip() for s in row.strip('|').split('|')]
                if all(set(c) <= set('-: ') for c in cells):
                    continue
                tag = 'th' if index == 0 else 'td'
                rows.append('<tr>' + ''.join(f'<{tag}>' + html.escape(c) + f'</{tag}>' for c in cells) + '</tr>')
            blocks.append('<table>' + ''.join(rows) + '</table>')
            table.clear()
    for line in markdown.splitlines():
        if not in_code and line.startswith('|'):
            table.append(line)
            continue
        flush_table()
        if line.startswith('```'):
            if in_code:
                blocks.append('<pre>' + html.escape('\n'.join(code)) + '</pre>')
                code = []
            in_code = not in_code
        elif in_code:
            code.append(line)
        elif line.startswith('# '):
            blocks.append('<h1>' + html.escape(line[2:]) + '</h1>')
        elif line.startswith('## '):
            blocks.append('<h2>' + html.escape(line[3:]) + '</h2>')
        elif line.startswith('### '):
            blocks.append('<h3>' + html.escape(line[4:]) + '</h3>')
        elif line.startswith('- '):
            blocks.append('<p class="item">' + html.escape(line[2:]) + '</p>')
        elif line.strip():
            blocks.append('<p>' + html.escape(line) + '</p>')
    flush_table()
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>' + html.escape(title) + '</title><style>body{margin:0;background:#f3f7f7;color:#193539;'
        'font:16px/1.8 system-ui,sans-serif}main{max-width:920px;margin:36px auto;padding:32px 40px;'
        'background:white;border:1px solid #dce7e7;border-radius:14px}h1{font-size:28px;margin:0 0 24px}'
        'h2{font-size:21px;border-top:1px solid #e1ebeb;padding-top:24px;margin-top:32px}'
        'p,pre{overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f3f7f7;padding:18px;border-radius:8px}'
        '.item{padding-left:12px;border-left:3px solid #51978c}@media(max-width:600px){main{margin:12px;'
        'padding:20px}h1{font-size:24px}}table{border-collapse:collapse;width:100%;margin:16px 0}'
        'th,td{text-align:left;padding:10px;border-bottom:1px solid #dce7e7}th{background:#f3f7f7}'
        '@media print{body{background:white}main{border:0;margin:0;max-width:none}}'
        '</style></head><body><main>' + '\n'.join(blocks) + '</main></body></html>').encode()


def generate(task, payload, checkpoint):
    checkpoint('papers', 15, '读取创建任务时冻结的论文与来源')
    frozen, sections = payload['snapshot'], payload['sections']
    validate_sections(frozen, sections)
    papers = frozen['papers']
    source_rows = [dict(paper_id=p['paper_id'], **s) for p in papers for s in p['sources']]
    missing = {field: [p['paper_id'] for p in papers if not p.get(field)]
               for field in ('abstract', 'doi', 'authors', 'sources')}
    quality = dict(papers=len(papers), scope=frozen['mode'], missing=missing,
                   complete={field: len(papers)-len(ids) for field, ids in missing.items()},
                   coverage_basis='field_completeness_in_frozen_report_scope',
                   formal_collection_coverage=frozen.get('coverage', []),
                   note='字段完整率按本报告论文范围计算；正式采集覆盖率单独引用冻结基准，不等同于知识抽取准确率。')
    summary = a_summary(frozen, quality)
    summary_md = summary_markdown(summary)
    checkpoint('chapters', 40, '生成论文明细、来源和质量章节')
    title = payload['title']
    # Headings are escaped for Markdown too, so titles cannot insert additional chapters.
    safe_title = ' '.join(title.split()).replace('#', '\\#')
    labels = {'abstract': '摘要', 'doi': 'DOI', 'authors': '作者', 'sources': '来源记录'}
    quality_md = '# 数据质量\n\n' + f'论文总数：{len(papers)}。\n\n' + '\n'.join(
        f'- {labels[name]}：完整 {quality["complete"][name]} 篇，缺失 {len(ids)} 篇。'
        for name, ids in missing.items()) + '\n\n' + quality['note'] + '\n'
    for coverage in frozen.get('coverage', []):
        quality_md += f'\n- 正式采集范围：{coverage.get("venue", coverage.get("scope", "未知"))} {coverage.get("year", "")}；覆盖率：{coverage.get("coverage_ratio", "未核定")}；基准：{coverage.get("baseline_revision", "未提供")}。\n'
    scope_label = '所选批次历史论文' if frozen['mode'] == 'selected_batches_historical' else '当前有效论文'
    chapters = [f'# {safe_title}\n\n创建时间：{task.created_at.isoformat()} UTC\n\n'
                f'论文范围：{scope_label}；论文数：{len(papers)}。\n\n'
                f'数据版本：`{frozen["revision"]}`。\n\n',
                summary_md.replace('## ', '### ').replace('# 数据概述', '## 数据概述'),
                '## 论文与来源\n\n论文明细见 papers.csv / papers.json，来源明细见 sources.csv / sources.json。\n\n',
                quality_md.replace('# 数据质量', '## 数据质量')]
    files = {'summary.json': json_bytes(summary), 'summary.md': summary_md.encode(),
             'papers.json': json_bytes(papers),
             'papers.csv': csv_bytes(papers, ['paper_id', 'stable_id', 'title', 'year', 'venue',
                 'authors', 'doi', 'openalex_id', 'source_url', 'cited_by_count', 'abstract']),
             'sources.json': json_bytes(source_rows),
             'sources.csv': csv_bytes(source_rows, ['paper_id', 'source', 'source_id', 'source_url', 'raw_sha256']),
             'quality.json': json_bytes(quality), 'quality.md': quality_md.encode(),
             'batches.json': json_bytes(frozen['batches'])}
    providers = {s['provider']: s for s in sections}
    for provider, label in [('B', '知识、证据、标签与知识质量'), ('C', '趋势、分布及作者机构统计')]:
        section = providers.get(provider)
        if section:
            files[f'{provider.lower()}-data.json'] = json_bytes(section)
            chapters.append(f'\n## {label}\n\n提供方：{provider}；版本：`{section["revision"]}`。'
                            f'完整数据见 {provider.lower()}-data.json。\n')
            if provider == 'B' and section['data'].get('counts'):
                chapters.append('\n```json\n' + json.dumps(section['data']['counts'], ensure_ascii=False, indent=2) + '\n```\n')
            if provider == 'B' and b_knowledge(section) is not None:
                knowledge = b_knowledge(section)
                exported = {key: [] for key in ('entities', 'relations', 'evidence', 'labels')}
                for part in knowledge['papers']:
                    identifier = part['input']['openalex_id']
                    for group in ('entities', 'relations'):
                        for item in part[group]:
                            exported[group].append(dict(paper_id=identifier, **item))
                            exported['evidence'].extend(dict(paper_id=identifier,
                                candidate_id=item['candidate_id'], evidence=e) for e in item['evidence'])
                    exported['labels'].extend(dict(paper_id=identifier, classification=item)
                        for item in part.get('source_classifications', []))
                for group, items in exported.items():
                    files[f'b-{group}.json'] = json_bytes(items)
                files['b-source-classifications.json'] = json_bytes(exported['labels'])
                files['b-quality.json'] = json_bytes(dict(revision=section['revision'],
                    counts=knowledge['counts'], source_classification_count=len(exported['labels']),
                    note='按 B 有效知识快照统计；来源分类沿用 B 数据，作者标签规则及准确率以 B 后续输出为准。'))
                if section['data'].get('format_version') == 'knowledge-report/1':
                    attachment = section['data']
                    files['b-report.json'] = json_bytes(attachment)
                    files['b-author-tags.json'] = json_bytes(attachment['author_tags'])
                    files['b-labels.json'] = files['b-author-tags.json']
                    files['b-quality.json'] = json_bytes(attachment['quality'])
                    counts = attachment['quality']['counts']
                    chapters.append('\n### 作者论文知识标签与知识质量\n\n'
                        '作者标签表示作者参与的当前有效论文涉及哪些主题、方法、任务和数据集，'
                        '保留支持论文与原文证据。标签不表示作者专长或提出该方法。\n\n'
                        f'知识附件版本：`{attachment["revision"]}`。'
                        f'有效实体条目 {counts["entities"]} 次，关系条目 {counts["relations"]} 次，按论文累计。'
                        '\n\n知识质量明细见 b-quality.json；证据覆盖率不代表抽取准确率，当前准确率未评估。\n')
                chapters.append(f'\n实体 {len(exported["entities"])} 条，关系 {len(exported["relations"])} 条，'
                    f'证据 {len(exported["evidence"])} 条，来源分类 {len(exported["labels"])} 条。'
                    '\n\n明细见 b-entities.json、b-relations.json、b-evidence.json、b-labels.json 和 b-quality.json。\n')
            if provider == 'C':
                statistics = section['data'].get('statistics', {})
                if statistics:
                    files['c-statistics.json'] = json_bytes(statistics)
                    chapters.append(f'\n统计论文数：{statistics.get("paper_count", "未提供")}。\n')
                    if 'years' in statistics:
                        files['c-years.csv'] = csv_bytes(statistics['years'], ['year', 'paper_count'])
                        chapters.append('\n| 年份 | 论文数 |\n| --- | ---: |\n' + ''.join(
                            f'| {r.get("year")} | {r.get("paper_count")} |\n' for r in statistics['years']))
                for key in ('trends', 'distributions', 'authors', 'institutions', 'coauthors'):
                    if key in section['data']:
                        files[f'c-{key}.json'] = json_bytes(section['data'][key])
                pending = section['data'].get('pending_sections', [])
                if pending:
                    chapters.append('\n本次尚未提供的统计章节：' + '、'.join(pending) + '。\n')
        else:
            chapters.append(f'\n## {label}\n\n本次未附 {provider} 的报告数据。\n')
    report = '\n'.join(chapters)
    files['report.md'] = report.encode()
    files['report.html'] = readable_html(title, report)
    files['README.md'] = ('# 报告文件\n\n打开 report.html 或 report.md 阅读；CSV 可用于表格核对，JSON 保留完整结构。'
        '\n\nmanifest.json 记录论文范围、版本和各内容文件 SHA-256；checksums.sha256 同时包含 manifest.json 的校验值。'
        '\n\n报告使用创建任务时的冻结数据；后续导入和撤回不改变本报告。\n').encode()
    checkpoint('manifest', 65, '生成文件清单与 SHA-256 校验值')
    manifest = dict(format_version='a-report-bundle/1', task_id=task.id, title=title,
        created_at=task.created_at.isoformat() + 'Z', a_revision=frozen['revision'],
        scope=frozen['scope'], scope_mode=frozen['mode'], paper_count=len(papers),
        providers={s['provider']: s['revision'] for s in sections},
        missing_providers=[p for p in ('B', 'C') if p not in providers],
        files=[dict(name=name, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
               for name, body in sorted(files.items())])
    files['manifest.json'] = json_bytes(manifest)
    files['checksums.sha256'] = ''.join(hashlib.sha256(body).hexdigest() + '  ' + name + '\n'
        for name, body in sorted(files.items())).encode()
    root = artifact_root() / task.id
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f'attempt-{task.attempts}'
    if destination.exists():
        raise ValueError('该任务尝试的产物已存在，请重试以生成新的完整产物')
    checkpoint('packaging', 85, '打包报告并核对文件完整性')
    with tempfile.TemporaryDirectory(prefix='.building-', dir=root) as temp:
        temporary = Path(temp)
        for name, body in files.items():
            (temporary / name).write_bytes(body)
        archive = temporary / 'report.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for name, body in sorted(files.items()):
                info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, body)
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError('ZIP 校验失败')
        archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        os.replace(temporary, destination)
    return dict(paper_count=len(papers), a_revision=frozen['revision'],
                providers=manifest['providers'], missing_providers=manifest['missing_providers'],
                artifact_directory=f'{task.id}/attempt-{task.attempts}',
                download_url=f'/api/admin/reports/{task.id}/download',
                zip_sha256=archive_sha, zip_bytes=(destination/'report.zip').stat().st_size,
                files=manifest['files'] + [dict(name='manifest.json', bytes=len(files['manifest.json']),
                    sha256=hashlib.sha256(files['manifest.json']).hexdigest()),
                    dict(name='checksums.sha256', bytes=len(files['checksums.sha256']),
                         sha256=hashlib.sha256(files['checksums.sha256']).hexdigest())])
