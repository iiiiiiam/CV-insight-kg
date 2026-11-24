"""Conservative exclusion of known proceedings front matter; raw records remain intact."""
from sqlalchemy import and_, not_, select
from .models import Paper, StablePaper

FRONT_MATTER = frozenset({
    'proceedings', 'senior area chairs and area chairs', 'outstanding reviewers',
    'organizers', 'copyright page', 'copyright', 'author index', 'keynotes', 'title page',
    'title page i', 'title page ii', 'title page iii', 'title page iv',
    'message from the program and general chairs', 'table of contents',
})


def research_paper_scope():
    # A missing author alone is not grounds for rejecting a research paper.
    return and_(not_(and_(Paper.title_normalized.in_(FRONT_MATTER), Paper.authors_json == '[]')),
                Paper.id.not_in(select(StablePaper.paper_id).where(StablePaper.active.is_(False))))


def research_metadata_scope():
    return not_(and_(Paper.title_normalized.in_(FRONT_MATTER),Paper.authors_json=='[]'))


def is_front_matter(row):
    from .ingest import normalize_title
    return normalize_title(row.get('title', '')) in FRONT_MATTER and not row.get('authors')
