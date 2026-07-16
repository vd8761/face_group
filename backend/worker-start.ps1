$ErrorActionPreference = "Stop"

# Match the production launcher while retaining Celery's Windows-safe solo
# pool. The supervisor starts separate face and Drive nodes at concurrency one.
python -m app.migrate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m app.workers.supervisor
exit $LASTEXITCODE
