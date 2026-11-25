from os import environ

timeout = 210
graceful_timeout = 210

if environ.get("RENDER_SERVICE_ID") and environ.get("COPILOT_GITHUB_CLIENT_ID", "").strip():
    # Keep one copy of Django and the SDK on the memory-constrained web instance.
    workers = 1
    threads = 2


def post_worker_init(worker):
    from study.simulation.oral_jobs import wake

    wake()
