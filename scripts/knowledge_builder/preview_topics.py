"""Preview source topic hierarchies from a frozen B corpus, without a server or Neo4j."""

import argparse
from collections import Counter

from src.knowledge_builder.extraction import load_vocabulary
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.source_corpus import load_corpus
from src.knowledge_builder.source_enrichment import analyze_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="data/knowledge_builder/source_corpus/corpus.json")
    parser.add_argument("--limit", type=int, default=5, help="Number of paper examples; all papers are counted")
    args = parser.parse_args()
    vocabulary = load_vocabulary()
    baseline = load_openalex_sample("examples/week1_baseline.json")
    papers, sources = load_corpus(args.corpus, baseline, vocabulary)
    counts = Counter(papers=len(papers))
    parents = set()
    for index, paper in enumerate(papers):
        classifications = analyze_sources(paper, vocabulary, sources[paper.openalex_id])["source_classifications"]
        topics = [t for t in classifications if t["kind"] == "topic"]
        directions = [t for t in classifications if t["kind"] == "research_direction"]
        counts["papers_with_directions"] += bool(directions)
        counts["other"] += any(t.get("selection") == "fallback" for t in directions)
        counts["multiple"] += len(directions) > 1
        counts["single_classified"] += len(directions) == 1 and directions[0].get("selection") != "fallback"
        counts["direction_assignments"] += len(directions)
        classified = [t for t in topics if "subfield" in t.get("hierarchy", {})]
        counts["topics"] += len(topics)
        counts["topics_with_subfield"] += len(classified)
        counts["papers_with_subfield"] += bool(classified)
        parents.update(t["hierarchy"]["subfield"]["source_id"] for t in classified)
        if index < max(0, args.limit):
            print(paper.title)
            for direction in directions:
                print("  " + direction["parent_name"] + " -> " + direction["name"]
                      + " [basis: " + ", ".join(sorted({t.get("channel", "task") for t in direction["mapped_from"]})) + "]")
            for topic in topics:
                parent = topic.get("hierarchy", {}).get("subfield")
                print("  " + (parent["name"] if parent else "[parent not supplied]") + " -> " + topic["name"])
    print(dict(counts, unique_subfields=len(parents)))


if __name__ == "__main__":
    main()
