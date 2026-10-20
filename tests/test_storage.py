from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bilirelay.auth import CredentialStore, make_qr_svg
from bilirelay.errors import BiliError
from bilirelay.subscriptions import Subscription, SubscriptionStore

TEMP_ROOT = ROOT / "tests" / ".tmp"


def make_temp_dir() -> Path:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEMP_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


class CredentialStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.work = make_temp_dir()

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def test_save_load_clear(self) -> None:
        path = self.work / "credential.json"
        store = CredentialStore(path)
        store.save("SESSDATA=abc", {"uid": 2, "name": "测试"})
        self.assertTrue(path.is_file())
        loaded = CredentialStore(path)
        loaded.load()
        self.assertEqual(loaded.cookie, "SESSDATA=abc")
        self.assertEqual(loaded.user["name"], "测试")
        loaded.clear()
        self.assertFalse(path.exists())
        self.assertEqual(loaded.cookie, "")

    def test_corrupt_file_does_not_raise(self) -> None:
        path = self.work / "credential.json"
        path.write_text("{not json", encoding="utf-8")
        store = CredentialStore(path)
        store.load()
        self.assertEqual(store.cookie, "")


class SubscriptionStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.work = make_temp_dir()
        self.path = self.work / "subscriptions.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)

    def test_add_list_remove_and_reload(self) -> None:
        store = SubscriptionStore(self.path, max_per_session=3)
        sub = store.add(
            Subscription(umo="bot:group:1", uid=2, name="碧诗", types=["video", "live"])
        )
        self.assertEqual(sub.uid, 2)
        self.assertEqual(len(store.for_session("bot:group:1")), 1)
        self.assertEqual(len(store.for_session("other")), 0)

        # 重复添加会合并类型
        store.add(
            Subscription(umo="bot:group:1", uid=2, name="碧诗", types=["dynamic"])
        )
        merged = store.get("bot:group:1", 2)
        self.assertIsNotNone(merged)
        self.assertEqual(sorted(merged.types), ["dynamic", "live", "video"])

        # 重新加载
        reloaded = SubscriptionStore(self.path, max_per_session=3)
        self.assertEqual(len(reloaded.all()), 1)
        self.assertEqual(reloaded.get("bot:group:1", 2).name, "碧诗")

        self.assertTrue(reloaded.remove("bot:group:1", 2))
        self.assertFalse(reloaded.remove("bot:group:1", 2))
        self.assertEqual(len(SubscriptionStore(self.path).all()), 0)

    def test_max_per_session(self) -> None:
        store = SubscriptionStore(self.path, max_per_session=1)
        store.add(Subscription(umo="u", uid=2))
        with self.assertRaises(BiliError):
            store.add(Subscription(umo="u", uid=3))

    def test_counts(self) -> None:
        store = SubscriptionStore(self.path)
        store.add(Subscription(umo="u1", uid=2, types=["video"]))
        store.add(Subscription(umo="u2", uid=2, types=["live"]))
        counts = store.counts()
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["sessions"], 2)
        self.assertEqual(counts["ups"], 1)
        self.assertEqual(counts["by_type"]["video"], 1)
        self.assertEqual(counts["by_type"]["live"], 1)

    def test_file_format(self) -> None:
        store = SubscriptionStore(self.path)
        store.add(Subscription(umo="u", uid=2))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["subscriptions"]), 1)


class QrTest(unittest.TestCase):
    def test_svg(self) -> None:
        svg = make_qr_svg("https://example.com/login")
        if not svg:
            self.skipTest("qrcode 未安装")
        self.assertIn("<svg", svg)


if __name__ == "__main__":
    unittest.main()
