from src.graph_query.repository import GraphRepository
from src.graph_query.search import normalize


def test_fr01_same_dimension_is_or_and_different_dimensions_are_and():
    filters = {
        "author": ["author:1", "Alice"],
        "topic": ["Vision", "Generation"],
        "method": ["Diffusion"],
        "year": 2024,
    }
    params = normalize(filters)
    where = GraphRepository.where(params)

    assert "toLower(f.id) IN $author" in where
    assert "toLower(f.name) IN $topic" in where
    assert "any(v IN coalesce(f.search_tokens,[])" in where
    assert "p.year IN $year" in where
    assert " AND " in where
    assert params["author"] == ["alice", "author:1"]
    assert params["topic"] == ["generation", "vision"]
    assert params["year"] == [2024]


def test_fr01_old_single_value_contract_remains_supported():
    params = normalize({"venue": "CVPR"})
    assert params["venue"] == ["cvpr"]
