"""Shared B reading workspace for HTTP and offline graph handoff."""

from pathlib import Path

from server.application.knowledge import KnowledgeSnapshot, KnowledgeSnapshotInvalid
from src.knowledge_builder.extraction import load_vocabulary
from src.knowledge_builder.feedback import FeedbackStore, KnowledgeFeedback
from src.knowledge_builder.source_corpus import load_reading_corpus
from src.knowledge_builder.batches import BatchStoreInvalid
from src.knowledge_builder.batch_sources import BatchSourcesInvalid
from server.application.knowledge_batches import batch_registry, batch_sources

ROOT = Path(__file__).resolve().parents[2]


def reading_workspace(settings, *, snapshot_factory=KnowledgeSnapshot):
    # Once the first batch has been accepted, even an empty active snapshot is
    # authoritative. Never silently resurrect the fixed demonstration corpus.
    registry = batch_registry(settings)
    try:
        managed = bool(registry.read()["batches"])
        if managed:
            path = Path(settings.b_vocabulary_path) if settings.b_vocabulary_path else None
            if path is not None and not path.is_absolute():
                path = ROOT / path
            return registry.workspace(registry.path.parent / "feedback/state.json", load_vocabulary(path),
                                      source_store=batch_sources(settings))
    except (BatchStoreInvalid, BatchSourcesInvalid) as exc:
        raise KnowledgeSnapshotInvalid("批次存档无法校验，请检查后重试；不会退回旧样本") from exc
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
