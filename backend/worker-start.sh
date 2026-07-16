#!/bin/sh
set -eu

# A worker can become healthy before the web container during a rolling
# deploy. Run the same advisory-locked idempotent expansion first.
python -m app.migrate

# The supervisor owns two nodes: an adaptive POSIX face pool and an isolated
# single-slot Drive downloader. It forwards termination and stops both nodes if
# either one exits.
exec python -m app.workers.supervisor
