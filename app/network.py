"""Bounded retries for idempotent official metadata requests."""
import time
import requests


def retry_request(action, attempts=3):
    for attempt in range(attempts):
        try:
            return action()
        except requests.RequestException as exc:
            if attempt+1==attempts:
                raise
            delay=min(2**attempt,8)
            response=getattr(exc,'response',None)
            if response is not None:
                try:delay=min(max(float(response.headers.get('Retry-After',delay)),0),30)
                except (TypeError,ValueError):pass
            time.sleep(delay)
    raise ValueError('Retry count must be positive')
