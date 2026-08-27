import json
import threading
import time
import unittest

from shared.jsonl import write_line


class SlowStream:
    def __init__(self):
        self.parts = []

    def write(self, value):
        for char in value:
            self.parts.append(char)
            time.sleep(0)

    def flush(self):
        pass


class JsonlTests(unittest.TestCase):
    def test_concurrent_writes_remain_complete_lines(self):
        stream = SlowStream()
        threads = [
            threading.Thread(
                target=lambda worker=worker: [
                    write_line({"worker": worker, "item": item}, stream)
                    for item in range(20)
                ]
            )
            for worker in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        lines = "".join(stream.parts).splitlines()
        self.assertEqual(len(lines), 80)
        self.assertEqual(len([json.loads(line) for line in lines]), 80)


if __name__ == "__main__":
    unittest.main()
