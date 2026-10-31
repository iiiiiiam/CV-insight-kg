"""D adapter reuses B review rules, archive persistence and business export format."""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import io
import zipfile

from src.knowledge_builder.extraction import extract_candidates, fingerprint, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.paths import default_review_directory
from src.knowledge_builder.review import REVIEW_VERSION, ReviewSession
from src.knowledge_builder.review_storage import load_review_records
from src.knowledge_builder.review_storage import save_review
from src.knowledge_builder.export import build_exports
from src.knowledge_builder.export_io import export_files


ROOT = Path(__file__).resolve().parents[2]
STATUSES = ('pending', 'confirmed', 'rejected')


class UnknownSnapshotPaper(LookupError):
    pass


class KnowledgeSnapshotInvalid(ValueError):
    """Invalid inputs/archives must be visible, never replaced with pending data."""


class KnowledgeSnapshotChanged(ValueError):
    pass


class KnowledgeReviewRejected(ValueError):
    pass


class KnowledgeReviewStorageError(OSError):
    pass


def _path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _counts(session):
    return {status: {'entities': len(session.select(status).entities),
                     'relations': len(session.select(status).relations)} for status in STATUSES}


class KnowledgeSnapshot:
    """Request-local state. Writes use a copy and replace state only after B saves."""

    def __init__(self, manifest: Path | None = None, *, vocabulary_path=None, reviews_directory=None):
        try:
            self.papers = load_openalex_sample(_path(manifest or ROOT / 'examples/week1_baseline.json'))
            vocabulary = load_vocabulary(_path(vocabulary_path) if vocabulary_path else None)
            self.results = {p.openalex_id: extract_candidates(p, vocabulary) for p in self.papers}
            self.by_id = {p.openalex_id: p for p in self.papers}
            self.review_directory = _path(reviews_directory) if reviews_directory else default_review_directory(ROOT)
            records = load_review_records(self.review_directory, self.papers, list(self.results.values()))
            self.sessions, self.archive_revisions, self.archive_paths = {}, {}, {}
            for paper in self.papers:
                identifier = paper.openalex_id
                if identifier in records:
                    stored = records[identifier][1]
                    self.sessions[identifier] = stored.session
                    self.archive_revisions[identifier] = stored.revision
                    self.archive_paths[identifier] = records[identifier][0]
                else:
                    self.sessions[identifier] = ReviewSession(paper, self.results[identifier])
                    self.archive_revisions[identifier] = None
                    self.archive_paths[identifier] = self.review_directory / (fingerprint(identifier) + '.json')
            self.snapshot_revision = fingerprint({
                'extractions': {key: fingerprint(asdict(result)) for key, result in self.results.items()},
                'archives': self.archive_revisions,
            })
            self.loaded_at = datetime.now(timezone.utc).isoformat()
        except (ValueError, OSError, TypeError, KeyError) as exc:
            raise KnowledgeSnapshotInvalid(
                f'无法读取或校验 B 样本、词表或审核存档：{exc}。请核对版本和存档后重试；不会自动丢弃审核记录。'
            ) from exc

    def overview(self):
        entity_counts = Counter(c.entity.kind for r in self.results.values() for c in r.entities)
        relation_counts = Counter(c.kind for r in self.results.values() for c in r.relations)
        paper_counts = {key: _counts(session) for key, session in self.sessions.items()}
        counts = {status: {kind: sum(c[status][kind] for c in paper_counts.values())
                           for kind in ('entities', 'relations')} for status in STATUSES}
        first = next(iter(self.results.values()))
        return {
            'origin': 'B extraction and validated review archives; fixed A snapshot',
            'status': 'review_snapshot', 'confirmed_count': sum(counts['confirmed'].values()),
            'read_only': True, 'review_counts': counts, 'review_version': REVIEW_VERSION,
            'snapshot_revision': self.snapshot_revision, 'loaded_at': self.loaded_at,
            'schema_version': first.schema_version, 'rule_version': first.rule_version,
            'vocabulary_version': first.vocabulary_version,
            'vocabulary_fingerprint': first.vocabulary_fingerprint,
            'dataset_id': self.papers[0].dataset_id,
            'entity_count': sum(entity_counts.values()), 'relation_count': sum(relation_counts.values()),
            'entity_counts': dict(entity_counts), 'relation_counts': dict(relation_counts),
            'diagnostic_count': sum(len(r.diagnostics) for r in self.results.values()),
            'papers': [{'openalex_id': p.openalex_id, 'title': p.title, 'year': p.year,
                        'venue': p.venue, 'entity_count': len(self.results[p.openalex_id].entities),
                        'relation_count': len(self.results[p.openalex_id].relations),
                        'review_counts': paper_counts[p.openalex_id],
                        'has_archive': self.archive_revisions[p.openalex_id] is not None,
                        'history_count': len(self.sessions[p.openalex_id].history)} for p in self.papers],
        }

    def candidates(self, paper_id: str, snapshot_revision: str | None = None):
        if snapshot_revision is not None and snapshot_revision != self.snapshot_revision:
            raise KnowledgeSnapshotChanged('B 输入、词表或审核存档已变化，请刷新整个候选页面后重新查看。')
        paper = self.by_id.get(paper_id)
        if paper is None:
            raise UnknownSnapshotPaper('该论文不在 B 已校验的固定样本中。')
        session = self.sessions[paper_id]
        counts = _counts(session)
        return {
            'paper': asdict(paper), 'result': asdict(self.results[paper_id]),
            'review': {
                'version': REVIEW_VERSION, 'counts': counts,
                'has_archive': self.archive_revisions[paper_id] is not None,
                'archive_revision': self.archive_revisions[paper_id],
                'items': [asdict(item) for item in session.items],
                'history': [asdict(event) for event in session.history],
            },
            'snapshot_revision': self.snapshot_revision, 'loaded_at': self.loaded_at,
            'read_only': True, 'confirmed_count': sum(counts['confirmed'].values()), 'scope': 'fixed_snapshot',
            'notice': '原始抽取候选始终待审；当前审核状态来自 B 校验后的存档。提及不等于使用或验证，C 正式图谱待接入。',
        }

    def apply_review(self, paper_id, candidate_id, action, *, reviewer, reason, snapshot_revision, name=None):
        if snapshot_revision != self.snapshot_revision:
            raise KnowledgeSnapshotChanged('B 数据已变化，未保存本次操作。请重新读取后再审核。')
        if paper_id not in self.sessions:
            raise UnknownSnapshotPaper('该论文不在 B 固定样本中。')
        if action not in ('confirm', 'reject', 'correct', 'reopen'):
            raise KnowledgeReviewRejected('不支持的审核操作。')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise KnowledgeReviewRejected('请填写操作理由（1—2000 字）。')
        if action == 'correct' and (not isinstance(name, str) or not name.strip() or len(name) > 300):
            raise KnowledgeReviewRejected('改名需填写实体显示名称（1—300 字）；证据保持只读。')
        if action != 'correct' and name is not None:
            raise KnowledgeReviewRejected('仅改名操作可提交显示名称。')
        proposed = deepcopy(self.sessions[paper_id])
        history_start = len(proposed.history)
        try:
            if action == 'correct':
                proposed.correct(candidate_id, name=name, reviewer=reviewer, reason=reason)
            else:
                getattr(proposed, action)(candidate_id, reviewer=reviewer, reason=reason)
        except ValueError as exc:
            messages = {
                'Unknown candidate ID': '未找到该候选，请重新读取数据。',
                'Confirm both endpoint entities before the relation': '请先分别确认关系两端的实体，再确认这条关系。',
                'Reopen a decided candidate before changing it': '该记录已经有决定，请先撤回，再进行新的审核。',
                'Candidate is already pending': '该记录已经待审核，不需要撤回。',
                'Only an entity may receive a nonempty display name': '只有实体可以修改显示名称，关系类型和端点保持不变。',
                'Correction must change the candidate': '新名称与当前名称相同，无需保存。',
            }
            raise KnowledgeReviewRejected(messages.get(str(exc), str(exc))) from exc
        try:
            revision = save_review(self.archive_paths[paper_id], proposed,
                                   expected_revision=self.archive_revisions[paper_id])
        except (FileExistsError, ValueError) as exc:
            raise KnowledgeSnapshotChanged('审核存档被其他窗口修改、移除或正在写入，未覆盖原记录。请重新读取后再试。') from exc
        except OSError as exc:
            raise KnowledgeReviewStorageError('审核存档保存失败，本次操作未生效。请检查目录权限和磁盘后重试。') from exc
        self.sessions[paper_id] = proposed
        self.archive_revisions[paper_id] = revision
        self.snapshot_revision = fingerprint({
            'extractions': {key: fingerprint(asdict(result)) for key, result in self.results.items()},
            'archives': self.archive_revisions,
        })
        return {'saved': True, 'paper_id': paper_id, 'candidate_id': candidate_id, 'action': action,
                'archive_revision': revision, 'snapshot_revision': self.snapshot_revision,
                'item': asdict(proposed.get(candidate_id)),
                'affected_candidate_ids': [e.after.candidate_id for e in proposed.history[history_start:]]}

    def download(self, filename, snapshot_revision):
        if snapshot_revision != self.snapshot_revision:
            raise KnowledgeSnapshotChanged('B 数据已变化，请重新读取后下载，确保文件与页面统计一致。')
        if filename not in ('confirmed.json', 'pending.json', 'rejected.json', 'bundle.zip'):
            raise KnowledgeReviewRejected('不支持的下载格式。')
        bundle = build_exports(self.papers, list(self.results.values()), self.sessions)
        files = export_files(bundle, self.papers)
        if filename != 'bundle.zip':
            return files[filename], 'application/json', 'b-' + filename
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for file_name, body in files.items():
                archive.writestr(file_name, body)
        return output.getvalue(), 'application/zip', 'b-knowledge.zip'

    def confirmed(self, paper_id):
        """Public subset: no pending/rejected records or reviewer names/reasons/history."""
        paper = self.by_id.get(paper_id)
        if paper is None:
            return {'paper_id': paper_id, 'supported': False, 'scope': 'fixed_snapshot',
                    'entities': [], 'relations': [], 'notice': '该论文尚未纳入 B 的固定审核样本。'}
        selection = self.sessions[paper_id].select('confirmed')
        return {'paper_id': paper_id, 'supported': True, 'scope': 'fixed_snapshot',
                'entities': [asdict(item) for item in selection.entities],
                'relations': [asdict(item) for item in selection.relations],
                'source': {'title': paper.title, 'abstract': paper.abstract, 'source_url': paper.source_url},
                'dataset_id': paper.dataset_id, 'snapshot_revision': self.snapshot_revision,
                'vocabulary_version': self.results[paper_id].vocabulary_version,
                'notice': '仅展示 B 存档中已确认的内容；提及不等于论文使用、提出或验证了该项内容。'}
