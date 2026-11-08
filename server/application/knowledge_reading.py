"""Shared B reading workspace for HTTP and offline graph handoff."""

from pathlib import Path

from server.application.knowledge import KnowledgeSnapshot, KnowledgeSnapshotInvalid
from src.knowledge_builder.extraction import load_vocabulary
from src.knowledge_builder.feedback import FeedbackStore, KnowledgeFeedback
from src.knowledge_builder.source_corpus import load_reading_corpus

ROOT = Path(__file__).resolve().parents[2]


def reading_workspace(settings, *, snapshot_factory=KnowledgeSnapshot):
    snapshot = snapshot_factory(vocabulary_path=settings.b_vocabulary_path,
                                reviews_directory=settings.b_reviews_directory)
    path = Path(settings.b_vocabulary_path) if settings.b_vocabulary_path else None
    if path is not None and not path.is_absolute():
        path = ROOT / path
    vocabulary = load_vocabulary(path)
    papers, results, sources = snapshot.papers, snapshot.results, None
    corpus_path = getattr(settings, "b_source_corpus", None)
    if corpus_path:
        corpus_path = Path(corpus_path)
        if not corpus_path.is_absolute():
            corpus_path = ROOT / corpus_path
        try:
            papers, sources, results = load_reading_corpus(corpus_path, papers, vocabulary)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise KnowledgeSnapshotInvalid("来源增强数据无法读取或校验，请检查 B_SOURCE_CORPUS") from exc
    return KnowledgeFeedback(papers, results, snapshot.sessions, vocabulary,
        FeedbackStore(snapshot.review_directory / "_feedback" / "state.json"), source_records=sources)
