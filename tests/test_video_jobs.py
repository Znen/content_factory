"""Реестр видео-задач <project>/media/.gf_video_jobs.jsonl."""
from gf import video_jobs


def test_read_jobs_empty_when_no_file(tmp_path):
    assert video_jobs.read_jobs(tmp_path) == []


def test_append_and_read_preserve_order(tmp_path):
    video_jobs.append_job(tmp_path, {"submit_id": "a", "mode": "i2v", "status": "pending"})
    video_jobs.append_job(tmp_path, {"submit_id": "b", "mode": "t2v", "status": "success"})
    jobs = video_jobs.read_jobs(tmp_path)
    assert [j["submit_id"] for j in jobs] == ["a", "b"]
    assert jobs[0]["mode"] == "i2v"


def test_update_job_sets_status_and_output(tmp_path):
    video_jobs.append_job(tmp_path, {"submit_id": "a", "status": "pending", "output": None})
    video_jobs.update_job(tmp_path, "a", status="success", output="/x/clip.mp4")
    jobs = video_jobs.read_jobs(tmp_path)
    assert jobs[0]["status"] == "success"
    assert jobs[0]["output"] == "/x/clip.mp4"


def test_update_job_only_matching_submit_id(tmp_path):
    video_jobs.append_job(tmp_path, {"submit_id": "a", "status": "pending"})
    video_jobs.append_job(tmp_path, {"submit_id": "b", "status": "pending"})
    video_jobs.update_job(tmp_path, "b", status="fail")
    by_id = {j["submit_id"]: j["status"] for j in video_jobs.read_jobs(tmp_path)}
    assert by_id == {"a": "pending", "b": "fail"}


def test_registry_lives_under_media(tmp_path):
    video_jobs.append_job(tmp_path, {"submit_id": "a", "status": "pending"})
    assert (tmp_path / "media" / ".gf_video_jobs.jsonl").exists()
