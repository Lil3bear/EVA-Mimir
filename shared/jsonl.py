import json
import sys
from typing import Any


def serialize(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def deserialize(line: str) -> Any:
    return json.loads(line.strip())


def write_line(obj: Any, stream=None) -> None:
    out = stream or sys.stdout
    out.write(serialize(obj))
    out.flush()


def read_lines(stream=None):
    inp = stream or sys.stdin
    buffer = ""
    while True:
        chunk = inp.read(1)
        if not chunk:
            break
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if line:
                yield deserialize(line)
