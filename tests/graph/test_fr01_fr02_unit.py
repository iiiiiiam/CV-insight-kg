from src.graph_query.repository import GraphRepository


def test_fr01_same_dimension_is_or_and_different_dimensions_are_and():
    filters = {
        "author": ["author:1", "Alice"],
        "topic": ["Vision", "Generation"],
        "method": ["Diffusion"],
        "year": 2024,
    }
    where = GraphRepository.where(filters)
    params = GraphRepository.filter_params(filters)

    assert "f.id IN $author" in where
    assert "toLower(f.name) IN $topic_normalized" in where
    assert "any(alias IN coalesce(f.aliases,[])" in where
    assert "p.year=$year" in where
    assert " AND " in where
    assert params["author"] == ["author:1", "Alice"]
    assert params["author_normalized"] == ["author:1", "alice"]
    assert params["topic_normalized"] == ["vision", "generation"]


def test_fr01_old_single_value_contract_remains_supported():
    params = GraphRepository.filter_params({"venue": "CVPR"})
    assert params["venue"] == ["CVPR"]
    assert params["venue_normalized"] == ["cvpr"]
