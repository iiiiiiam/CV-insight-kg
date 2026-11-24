import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from sqlalchemy import inspect
from app.models import database

class SchemaStartupTests(unittest.TestCase):
 def test_concurrent_first_start_creates_one_complete_schema(self):
  with tempfile.TemporaryDirectory() as directory:
   url='sqlite:///'+str(Path(directory)/'empty.db')
   code='from app.models import database; f=database('+repr(url)+'); f.kw["bind"].dispose()'
   children=[subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(3)]
   for child in children:
    out,err=child.communicate(timeout=45);self.assertEqual(child.returncode,0,err.decode())
   f=database(url)
   try:self.assertIn('a_handoff_receipts',inspect(f.kw['bind']).get_table_names())
   finally:f.kw['bind'].dispose()
