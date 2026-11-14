from pathlib import Path
import tempfile
from unittest.mock import patch

from sqlalchemy import select

from app.data_overview import dashboard
from app.models import Paper,database
from app.reserve import summary
from server.run_a import prepare_database_url


def test_new_local_database_has_the_same_seed_as_the_preview():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'new'/ 'a.db'
        url=prepare_database_url('sqlite:///'+str(path))
        factory=database(url)
        try:
            with factory() as db:
                assert dashboard(db,14)['total_papers']==420
                assert summary(db)['available']==2534
        finally:factory.kw['bind'].dispose()


def test_existing_database_is_preserved_without_reseeding():
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'existing.db';url='sqlite:///'+str(path)
        factory=database(url)
        try:
            with factory() as db:
                db.add(Paper(canonical_key='kept',title='Keep existing data',title_normalized='keep existing data',venue='CVPR',year=2024))
                db.commit()
            with patch('app.demo.create_demo') as seed:
                assert prepare_database_url(url)==url
                seed.assert_not_called()
            with factory() as db:
                assert list(db.scalars(select(Paper.title)))==['Keep existing data']
        finally:factory.kw['bind'].dispose()


def test_explicit_remote_database_is_passed_through_without_local_seed():
    url='mysql+pymysql://fixture:fixture-only@127.0.0.1:3306/fixture'
    with patch('app.demo.create_demo') as seed:
        assert prepare_database_url(url)==url
        seed.assert_not_called()
