"""Test suite for Antigravity Chat Sync.
Tests config, protobuf utilities, project mapping, scanner, and sync engine.
"""

import os
import sys
import unittest
from pathlib import Path

# Add package root to sys.path
package_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(package_root))

from antigravity_chat_sync.backup_manager import BackupManager
from antigravity_chat_sync.chat_scanner import ChatScanner
from antigravity_chat_sync.config import default_config
from antigravity_chat_sync.project_manager import ProjectManager
from antigravity_chat_sync.protobuf_utils import (
    extract_summary_metadata,
    merge_proto_summaries,
    parse_protobuf_dict,
    parse_trajectory_summaries,
    varint_decode,
    varint_encode,
)
from antigravity_chat_sync.sync_engine import SyncEngine


class TestAntigravityChatSync(unittest.TestCase):
    def test_varint_codec(self):
        numbers = [0, 1, 127, 128, 300, 16384, 1000000]
        for n in numbers:
            encoded = varint_encode(n)
            decoded, new_offset = varint_decode(encoded, 0)
            self.assertEqual(n, decoded)
            self.assertEqual(len(encoded), new_offset)

    def test_protobuf_merge(self):
        cid1 = "11111111-1111-1111-1111-111111111111"
        cid2 = "22222222-2222-2222-2222-222222222222"
        raw1 = b"\x0a\x06Test 1\x10\x05"
        raw2 = b"\x0a\x06Test 2\x10\x0a"

        # Merge into empty
        merged = merge_proto_summaries(b"", {cid1: raw1, cid2: raw2})
        entries = dict(parse_trajectory_summaries(merged))
        self.assertIn(cid1, entries)
        self.assertIn(cid2, entries)
        self.assertEqual(entries[cid1], raw1)
        self.assertEqual(entries[cid2], raw2)

        # Update cid1
        raw1_updated = b"\x0a\x0eTest 1 Updated\x10\x06"
        merged2 = merge_proto_summaries(merged, {cid1: raw1_updated})
        entries2 = dict(parse_trajectory_summaries(merged2))
        self.assertEqual(entries2[cid1], raw1_updated)
        self.assertEqual(entries2[cid2], raw2)

    def test_config_paths(self):
        val = default_config.validate()
        self.assertTrue(val["ide_base_exists"])
        self.assertTrue(val["app_base_exists"])
        self.assertTrue(val["app_summaries_db_exists"])

    def test_project_manager(self):
        pm = ProjectManager()
        projects = pm.get_all_projects()
        self.assertIsInstance(projects, list)

        # Test project slug normalization and matching
        slug = pm.make_slug("Sample Project 1")
        self.assertEqual(slug, "sample-project-1")

    def test_chat_scanner(self):
        scanner = ChatScanner()
        items = scanner.scan_all()
        self.assertGreater(len(items), 0)

        # Check fields
        first = items[0]
        self.assertTrue(len(first.id) > 10)
        self.assertTrue(len(first.title) > 0)
        self.assertIn(first.status, ("NEW", "UPDATED", "SYNCED"))

    def test_backup_manager(self):
        bm = BackupManager()
        backups = bm.list_backups()
        self.assertIsInstance(backups, list)


if __name__ == "__main__":
    unittest.main()
