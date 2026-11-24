"""B-owned batch storage location shared by admin routes and reading/export."""
from pathlib import Path

from src.knowledge_builder.batches import BatchRegistry
from src.knowledge_builder.batch_sources import BatchSources

ROOT = Path(__file__).resolve().parents[2]


def batch_registry(settings):
    path = Path(getattr(settings, "b_batch_registry", None) or "data/knowledge_builder/batches/ledger.json")
    return BatchRegistry(path if path.is_absolute() else ROOT / path)


def batch_sources(settings):
    def path(value):
        if not value:
            return None
        value = Path(value)
        return value if value.is_absolute() else ROOT / value
    return BatchSources(batch_registry(settings).path,
        corpus_path=path(getattr(settings, "b_source_corpus", None)),
        cache_path=path(getattr(settings, "b_source_cache", None)),
        offline=getattr(settings, "b_source_offline", False))
