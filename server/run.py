"""D gateway launcher. Run from repository root: python -m server.run."""

import uvicorn


if __name__ == '__main__':
    # A single worker is required by the local in-memory session store.
    uvicorn.run('server.api.main:create_app', factory=True, host='127.0.0.1', port=8001, workers=1)
