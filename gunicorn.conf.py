timeout = 210
graceful_timeout = 210


def post_worker_init(worker):
    from study.simulation.oral_jobs import wake

    wake()
