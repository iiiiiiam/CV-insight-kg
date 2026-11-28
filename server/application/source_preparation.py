"""One shared B source job for HTTP ingest and local-ledger automatic detection.

Network work runs off the API/publication thread. Only accepted managed batches
are scanned; existing demo corpora are never fetched automatically.
"""
import logging
import threading
import time

from server.application.knowledge_batches import batch_registry, batch_sources
from src.knowledge_builder.models import PaperInput


class SourcePreparation:
    poll_seconds = 10
    retry_seconds = 300

    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.job = dict(running=False, error=None)
        self.last_revision = None
        self.next_attempt = 0

    def status(self):
        with self.lock:
            return dict(self.job)

    def _claim(self, revision=None, *, force=False):
        with self.lock:
            if self.stop.is_set() or self.job['running']:
                return False
            if not force and revision == self.last_revision and time.monotonic() < self.next_attempt:
                return False
            self.job.update(running=True, error=None)
            return True

    def schedule(self, submit):
        # HTTP ingest and explicit retry share the same slot as the automatic watcher.
        if self._claim(force=True):
            submit(self.run)

    def run(self):
        try:
            while not self.stop.is_set():
                registry = batch_registry(self.settings)
                snapshot = registry.snapshot()
                papers = [PaperInput(**part['input']) for part in snapshot['papers']]
                with self.lock:
                    self.last_revision = snapshot['revision']
                batch_sources(self.settings).prepare(papers, stop_event=self.stop)
                if registry.snapshot()['revision'] == snapshot['revision']:
                    with self.lock:
                        self.last_revision = snapshot['revision']
                    break
        except Exception:
            logging.getLogger(__name__).exception('B source preparation interrupted')
            with self.lock:
                self.job['error'] = '来源补充中断，已有结果保留，后台将自动重试'
        finally:
            with self.lock:
                self.job['running'] = False
                self.next_attempt = time.monotonic() + self.retry_seconds

    def check(self):
        registry = batch_registry(self.settings)
        if not registry.path.exists():
            return
        state = registry.read()
        if not state['batches']:
            return
        from src.knowledge_builder.batches import _snapshot
        snapshot = _snapshot(state)
        revision = snapshot['revision']
        with self.lock:
            if self.job['running'] or (revision == self.last_revision and time.monotonic() < self.next_attempt):
                return
        papers = [PaperInput(**part['input']) for part in snapshot['papers']]
        summary = batch_sources(self.settings).summary(papers)
        if not summary['pending'] and not summary['partial']:
            with self.lock:
                self.last_revision = revision
            return
        if self._claim(revision):
            self.run()

    def _watch(self):
        while not self.stop.is_set():
            try:
                self.check()
            except Exception:
                logging.getLogger(__name__).exception('B source watcher could not read current state')
            if self.stop.wait(self.poll_seconds):
                break

    def start(self):
        self.thread = threading.Thread(target=self._watch, name='b-source-preparation', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=1)
