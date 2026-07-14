from pathlib import Path

from candidatura_agent.run_lock import exclusive_run_lock


def test_exclusive_run_lock_prevents_overlap_and_releases(tmp_path: Path):
    lock_path = tmp_path / "hourly.lock"
    with exclusive_run_lock(lock_path) as first:
        assert first is True
        with exclusive_run_lock(lock_path) as second:
            assert second is False
    with exclusive_run_lock(lock_path) as third:
        assert third is True
