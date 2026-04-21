from __future__ import annotations

import unittest
from unittest.mock import patch

from subbake.ui.dashboard import Dashboard


class DashboardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboard = Dashboard()
        self.dashboard.live.refresh = lambda: None

    def test_running_batch_shows_current_batch_and_elapsed_latency(self) -> None:
        self.dashboard.stage_states["LOAD_FILE"] = "done"
        self.dashboard.stage_states["PARSE"] = "done"
        self.dashboard.set_total_steps(8)

        with patch("subbake.ui.dashboard.monotonic", return_value=10.0):
            self.dashboard.mark_running("TRANSLATE_BATCH", label="TRANSLATE_BATCH 1/4")

        self.assertEqual(self.dashboard.batch.index, 1)
        self.assertEqual(self.dashboard.batch.total, 4)

        with patch("subbake.ui.dashboard.monotonic", return_value=13.25):
            self.assertEqual(self.dashboard._batch_latency_display(), "3.25s")
            self.assertEqual(self.dashboard._eta_display(), "-")

    def test_eta_shows_after_multiple_completed_batches_and_counts_down_each_second(self) -> None:
        with patch("subbake.ui.dashboard.monotonic", side_effect=[0.0, 0.1]):
            self.dashboard.mark_running("LOAD_FILE")
            self.dashboard.mark_done("LOAD_FILE")
        with patch("subbake.ui.dashboard.monotonic", side_effect=[0.1, 0.2]):
            self.dashboard.mark_running("PARSE")
            self.dashboard.mark_done("PARSE")

        self.dashboard.set_total_steps(8)

        with patch("subbake.ui.dashboard.monotonic", return_value=1.0):
            self.dashboard.mark_running("TRANSLATE_BATCH", label="TRANSLATE_BATCH 1/4")
        self.dashboard.set_batch(1, 4, 2.0, "TRANSLATE_BATCH 1/4")
        with patch("subbake.ui.dashboard.monotonic", return_value=4.0):
            self.dashboard.mark_done("TRANSLATE_BATCH")
        with patch("subbake.ui.dashboard.monotonic", return_value=4.0):
            self.dashboard.mark_running("TRANSLATE_BATCH", label="TRANSLATE_BATCH 2/4")
        self.dashboard.set_batch(2, 4, 2.5, "TRANSLATE_BATCH 2/4")
        with patch("subbake.ui.dashboard.monotonic", return_value=6.5):
            self.dashboard.mark_done("TRANSLATE_BATCH")
        with patch("subbake.ui.dashboard.monotonic", return_value=6.5):
            self.dashboard.mark_running("TRANSLATE_BATCH", label="TRANSLATE_BATCH 3/4")

        with patch("subbake.ui.dashboard.monotonic", return_value=7.0):
            first_eta = self.dashboard._eta_display()
        with patch("subbake.ui.dashboard.monotonic", return_value=8.0):
            second_eta = self.dashboard._eta_display()

        self.assertNotEqual(first_eta, "-")
        self.assertEqual(self._duration_to_seconds(first_eta) - 1, self._duration_to_seconds(second_eta))

    def test_eta_recalibrates_faster_when_near_completion(self) -> None:
        self.dashboard.batch_stage_totals["TRANSLATE_BATCH"] = 4
        self.dashboard.batch_stage_durations["TRANSLATE_BATCH"] = [10.0, 10.0]
        self.dashboard.batch_stage_current["TRANSLATE_BATCH"] = 3
        self.dashboard.current_stage = "TRANSLATE_BATCH"
        self.dashboard.current_stage_started_at = 100.0

        with patch("subbake.ui.dashboard.monotonic", return_value=102.0):
            first_eta = self.dashboard._eta_display()

        self.dashboard.batch_stage_durations["TRANSLATE_BATCH"].append(40.0)
        with patch("subbake.ui.dashboard.monotonic", return_value=104.0):
            second_eta = self.dashboard._eta_display()

        self.assertNotEqual(first_eta, "-")
        self.assertGreater(self._duration_to_seconds(second_eta), self._duration_to_seconds(first_eta) - 2)

    def _duration_to_seconds(self, value: str) -> int:
        if value.endswith("s") and "m" not in value and "h" not in value:
            return int(value[:-1])
        minutes = 0
        seconds = 0
        hours = 0
        for part in value.split():
            if part.endswith("h"):
                hours = int(part[:-1])
            elif part.endswith("m"):
                minutes = int(part[:-1])
            elif part.endswith("s"):
                seconds = int(part[:-1])
        return (hours * 3600) + (minutes * 60) + seconds
