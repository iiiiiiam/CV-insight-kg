"""Read-only D adapter for B's real, validated fixed-snapshot candidates."""

from collections import Counter
from dataclasses import asdict
from pathlib import Path

from src.knowledge_builder.extraction import extract_candidates, load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample


ROOT = Path(__file__).resolve().parents[2]


class UnknownSnapshotPaper(LookupError):
    pass


class KnowledgeSnapshot:
    def __init__(self, manifest: Path | None = None):
        self.papers = load_openalex_sample(manifest or ROOT / 'examples/week1_baseline.json')
        vocabulary = load_vocabulary()
        self.results = {p.openalex_id: extract_candidates(p, vocabulary) for p in self.papers}
        self.by_id = {p.openalex_id: p for p in self.papers}

    def overview(self):
        entity_counts = Counter(c.entity.kind for r in self.results.values() for c in r.entities)
        relation_counts = Counter(c.kind for r in self.results.values() for c in r.relations)
        first = next(iter(self.results.values()))
        return {
            'origin': 'B extract_candidates; validated A fixed snapshot',
            'status': 'pending', 'confirmed_count': 0, 'read_only': True,
            'schema_version': first.schema_version, 'rule_version': first.rule_version,
            'vocabulary_version': first.vocabulary_version,
            'vocabulary_fingerprint': first.vocabulary_fingerprint,
            'dataset_id': self.papers[0].dataset_id,
            'entity_count': sum(entity_counts.values()), 'relation_count': sum(relation_counts.values()),
            'entity_counts': dict(entity_counts), 'relation_counts': dict(relation_counts),
            'diagnostic_count': sum(len(r.diagnostics) for r in self.results.values()),
            'papers': [{'openalex_id': p.openalex_id, 'title': p.title, 'year': p.year,
                        'venue': p.venue, 'entity_count': len(self.results[p.openalex_id].entities),
                        'relation_count': len(self.results[p.openalex_id].relations)} for p in self.papers],
        }

    def candidates(self, paper_id: str):
        paper = self.by_id.get(paper_id)
        if paper is None:
            raise UnknownSnapshotPaper('该论文不在B已校验的固定样本中。')
        return {'paper': asdict(paper), 'result': asdict(self.results[paper_id]),
                'read_only': True, 'confirmed_count': 0, 'scope': 'fixed_snapshot',
                'notice': '提及候选均待审核；不代表使用、提出、实验验证或人工确认。'}
