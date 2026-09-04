"""``python -m workers`` entrypoint."""

from workers.app import run_worker

if __name__ == "__main__":
    run_worker()
