import json
import os
import time
from pathlib import Path
from shared.types import ChallengeConfig, SubmissionRecord


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f".{os.getpid()}.{time.time()}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def challenge_dir(workspace_dir: Path, challenge_id: str) -> Path:
    return workspace_dir / challenge_id


def save_challenge_config(workspace_dir: Path, config: ChallengeConfig) -> None:
    path = challenge_dir(workspace_dir, config.id) / "challenge.json"
    _atomic_write(path, config.__dict__)


def load_challenge_config(workspace_dir: Path, challenge_id: str) -> ChallengeConfig | None:
    path = challenge_dir(workspace_dir, challenge_id) / "challenge.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ChallengeConfig(**data)
    except Exception:
        return None


def append_submission(workspace_dir: Path, challenge_id: str,
                      flag: str, correct: bool,
                      writeup: str = "", solver_id: str = "") -> SubmissionRecord:
    record = SubmissionRecord(
        id=f"sub_{os.urandom(4).hex()}",
        flag=flag,
        correct=correct,
        submitted_at=time.time(),
        writeup=writeup,
        solver_id=solver_id,
    )
    submissions_dir = challenge_dir(workspace_dir, challenge_id) / "submissions"
    filename = f"{int(record.submitted_at * 1000)}-{record.id}.json"
    _atomic_write(submissions_dir / filename, record.__dict__)
    return record


def list_submissions(workspace_dir: Path, challenge_id: str) -> list[SubmissionRecord]:
    submissions_dir = challenge_dir(workspace_dir, challenge_id) / "submissions"
    if not submissions_dir.exists():
        return []
    records = []
    for f in sorted(submissions_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            records.append(SubmissionRecord(**data))
        except Exception:
            continue
    return records


def is_solved(workspace_dir: Path, challenge_id: str) -> bool:
    return any(s.correct for s in list_submissions(workspace_dir, challenge_id))
