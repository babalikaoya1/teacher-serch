import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage import Outbox
from wechat_uia import parse_time
from main import normalize_server


class HelperTests(unittest.TestCase):
    def test_queue_survives_restart_and_keeps_identical_message_occurrences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.db"
            item = {"text": "初中数学家教", "sender": "测试发布者", "sent_at": "2026-11-04T10:00:00+00:00"}
            queue = Outbox(path)
            queue.remember("群来源", [item, item])
            first = queue.batch("群来源")
            self.assertEqual(len(first), 2)
            self.assertNotEqual(first[0]["message_key"], first[1]["message_key"])
            queue.close()
            queue = Outbox(path)
            self.assertEqual(queue.batch("群来源"), first)
            queue.acknowledge("群来源", first)
            queue.remember("群来源", [item, item])
            self.assertEqual(queue.batch("群来源"), [])
            queue.save_checkpoint("群来源", {"revision": 1, "last_sent_at": item["sent_at"]})
            queue.close()
            queue = Outbox(path)
            self.assertEqual(queue.checkpoint("群来源")["revision"], 1)
            queue.close()

    def test_time_is_original_time_and_unknown_time_stays_unknown(self):
        now = datetime(2026, 11, 4, 18, 0, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(parse_time("昨天 17:31", now).isoformat(), "2026-11-03T17:31:00+08:00")
        self.assertEqual(parse_time("2026年11月2日 08:10", now).isoformat(), "2026-11-02T08:10:00+08:00")
        self.assertIsNone(parse_time("某个星期", now))

    def test_device_credentials_only_use_https_or_local_debugging(self):
        self.assertEqual(normalize_server("https://example.test/"), "https://example.test/api")
        self.assertEqual(normalize_server("http://127.0.0.1:8000"), "http://127.0.0.1:8000/api")
        with self.assertRaises(ValueError):
            normalize_server("http://public.example")
        with self.assertRaises(ValueError):
            normalize_server("https://user:password@example.test")


if __name__ == "__main__":
    unittest.main()
