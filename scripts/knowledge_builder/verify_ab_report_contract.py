"""Offline B attachment check against A's actual report validator at a Git revision.

Only the two pure validation functions are loaded; no A database, worker, network,
branch merge or runtime service is started. This is not full integration testing.
"""
import argparse
import ast
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import tempfile

from src.knowledge_builder.batches import BatchRegistry
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.report_knowledge import build_report_knowledge

ROOT = Path(__file__).resolve().parents[2]


def a_validator(ref):
    commit = subprocess.check_output(['git', 'rev-parse', '--verify', ref+'^{commit}'], cwd=ROOT, text=True).strip()
    source = subprocess.check_output(['git', 'show', commit+':app/report_bundle.py'], cwd=ROOT, text=True, encoding='utf-8')
    tree = ast.parse(source)
    names = {'b_knowledge', 'validate_sections'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in functions} != names:
        raise ValueError('A report validator interface changed; review its new contract first')
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), commit+':app/report_bundle.py', 'exec'), namespace)
    return commit, namespace['validate_sections']


def document(number, identifiers):
    papers = [PaperInput(f'https://openalex.org/W{i}', f'Vision paper {i}', 'We evaluate COCO.',
                        2024, 'CVPR', [], f'https://openalex.org/W{i}', 'contract-check') for i in identifiers]
    return dict(format_version='a-paperinput/1', batch_id=number, batch_code=f'CONTRACT-{number}',
                total_papers=len(papers), exported_papers=len(papers), excluded_papers=0,
                items=[asdict(paper) for paper in papers], excluded=[])


def check(ref, output):
    commit, validate = a_validator(ref)
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = []
    with tempfile.TemporaryDirectory(prefix='report-contract-', dir=output.parent) as directory:
        root = Path(directory)
        registry = BatchRegistry(root/'ledger.json')
        frozen_reports = []
        for phase in ('first', 'second', 'withdraw_second', 'withdraw_all'):
            if phase == 'first':
                registry.ingest(document(1, [1, 2]))
            elif phase == 'second':
                registry.ingest(document(2, [2, 3]))
            elif phase == 'withdraw_second':
                registry.withdraw('CONTRACT-2')
            else:
                registry.withdraw('CONTRACT-1')
            report = build_report_knowledge(registry.workspace(root/'feedback.json').export_effective())
            knowledge = report['knowledge']
            frozen = {'papers': [dict(paper_id=p['input']['openalex_id'], **{
                key: p['input'][key] for key in ('title', 'abstract', 'year', 'venue')}) for p in knowledge['papers']]}
            section = dict(provider='B', revision=report['scope']['knowledge_revision'],
                           paper_ids=report['scope']['paper_ids'], data=report)
            validate(frozen, [section])  # A+B is valid without C; no manual confirmation gate.
            validate(frozen, [])  # A-only reports remain allowed too.
            frozen_reports.append((deepcopy(frozen), deepcopy(section)))
            counts.append(report['scope']['paper_count'])
        if counts != [2, 3, 2, 0]:
            raise AssertionError('Unexpected batch/withdrawal scope')
        if frozen_reports[0][1]['data']['revision'] != frozen_reports[2][1]['data']['revision']:
            raise AssertionError('Withdrawal did not restore the original report version')
        # Historical frozen reports still validate after current batches are withdrawn.
        for frozen, section in frozen_reports:
            validate(frozen, [section])
        stale = deepcopy(frozen_reports[0][1]); stale['revision'] = '0'*64
        try:
            validate(frozen_reports[0][0], [stale])
        except ValueError:
            pass
        else:
            raise AssertionError('Mismatched knowledge version was accepted')
    result = dict(passed=True, a_commit=commit, b_commit=subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        counts=counts, checks=['B_attachment_matches_A', 'AB_without_C_allowed', 'A_only_allowed',
                              'withdrawal_restores_revision', 'historical_report_unchanged', 'stale_version_rejected'],
        network_calls=0, scope='pure_A_validator_and_real_B_modules_not_full_worker_integration')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--a-ref', default='origin/data-pipeline')
    parser.add_argument('--output', type=Path, default=ROOT/'.cache/ab-handoff-checks/report-contract.json')
    args = parser.parse_args()
    check(args.a_ref, args.output.resolve())


if __name__ == '__main__':
    main()
