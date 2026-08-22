"""Download options, task lifecycle and the manager's queue mechanics.

The manager is exercised with a stubbed worker, so nothing here hits the
network or spawns yt-dlp.
"""

from __future__ import annotations

import pytest

from app.models.download import (
    AUDIO_FORMATS,
    MP3_BITRATES,
    VIDEO_FORMATS,
    VIDEO_QUALITIES,
    DownloadOptions,
    DownloadStatus,
    DownloadTask,
    MediaInfo,
    Progress,
)


class TestDownloadStatus:
    @pytest.mark.parametrize(
        "status", [DownloadStatus.COMPLETE, DownloadStatus.FAILED, DownloadStatus.CANCELLED]
    )
    def test_terminal_states(self, status):
        assert status.is_terminal
        assert not status.is_active
        assert not status.is_pending

    @pytest.mark.parametrize(
        "status",
        [
            DownloadStatus.ANALYZING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PROCESSING,
            DownloadStatus.ORGANIZING,
        ],
    )
    def test_active_states(self, status):
        assert status.is_active
        assert not status.is_terminal

    @pytest.mark.parametrize("status", [DownloadStatus.QUEUED, DownloadStatus.PAUSED])
    def test_pending_states(self, status):
        assert status.is_pending
        assert not status.is_active
        assert not status.is_terminal

    def test_every_documented_status_exists(self):
        values = {s.value for s in DownloadStatus}
        assert {
            "Queued", "Analyzing", "Downloading", "Processing",
            "Complete", "Failed", "Cancelled",
        } <= values


class TestDownloadOptions:
    def test_audio_label_includes_the_bitrate(self):
        options = DownloadOptions(media_kind="audio", audio_format="mp3", audio_bitrate="320")
        assert options.quality_label() == "MP3 - 320 kbps"

    @pytest.mark.parametrize("fmt", ["wav", "flac"])
    def test_lossless_label_omits_a_bitrate(self, fmt):
        options = DownloadOptions(media_kind="audio", audio_format=fmt, audio_bitrate="320")
        assert options.quality_label() == fmt.upper()

    def test_video_label(self):
        options = DownloadOptions(media_kind="video", video_format="mp4", video_quality="1080p")
        assert options.quality_label() == "MP4 - 1080p"

    def test_best_video_label(self):
        options = DownloadOptions(media_kind="video", video_quality="best")
        assert options.quality_label() == "MP4 - Best"

    def test_target_extension_follows_the_kind(self):
        assert DownloadOptions(media_kind="audio", audio_format="flac").target_extension == "flac"
        assert DownloadOptions(media_kind="video", video_format="mkv").target_extension == "mkv"

    def test_the_documented_formats_are_offered(self):
        assert set(VIDEO_FORMATS) == {"mp4", "mkv", "webm"}
        assert set(AUDIO_FORMATS) == {"mp3", "m4a", "wav", "flac"}
        assert set(MP3_BITRATES) == {"128", "192", "256", "320"}
        assert VIDEO_QUALITIES[0] == "best"
        assert "2160p" in VIDEO_QUALITIES and "360p" in VIDEO_QUALITIES


class TestProgress:
    def test_percent_from_bytes(self):
        assert Progress(downloaded_bytes=50, total_bytes=200).percent == 25.0

    def test_percent_from_fragments_when_the_size_is_unknown(self):
        assert Progress(fragment_index=3, fragment_count=6).percent == 50.0

    def test_unknown_progress_is_zero(self):
        assert Progress().percent == 0.0

    def test_percent_never_exceeds_one_hundred(self):
        assert Progress(downloaded_bytes=300, total_bytes=200).percent == 100.0


class TestDownloadTask:
    def test_each_task_gets_a_unique_id(self):
        assert DownloadTask(url="a").id != DownloadTask(url="a").id

    def test_starts_queued(self):
        assert DownloadTask(url="a").status == DownloadStatus.QUEUED

    def test_display_title_falls_back_to_the_url(self):
        assert DownloadTask(url="https://example.com/x").display_title == "https://example.com/x"

    def test_display_title_prefers_the_analysed_title(self):
        task = DownloadTask(url="https://example.com/x")
        task.info = MediaInfo(title="Real Title")
        assert task.display_title == "Real Title"

    def test_retry_clears_the_previous_failure(self):
        task = DownloadTask(url="a")
        task.status = DownloadStatus.FAILED
        task.error = "boom"
        task.error_detail = "trace"
        task.progress = Progress(downloaded_bytes=10, total_bytes=100)

        task.reset_for_retry()

        assert task.status == DownloadStatus.QUEUED
        assert task.error == "" and task.error_detail == ""
        assert task.progress.downloaded_bytes == 0


@pytest.fixture
def manager(qapp, settings):
    from app.downloader.manager import DownloadManager

    instance = DownloadManager(settings)
    yield instance
    instance.shutdown(500)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app


class TestQueueMechanics:
    """Queue bookkeeping, with downloads stubbed out entirely."""

    def _enqueue(self, manager, count=1, **overrides):
        tasks = []
        for index in range(count):
            task = manager.enqueue(
                f"https://example.com/{index}", DownloadOptions(**overrides), start=False
            )
            tasks.append(task)
        return tasks

    def test_enqueue_registers_the_task(self, manager):
        task = self._enqueue(manager)[0]
        assert manager.task(task.id) is task
        assert len(manager.tasks) == 1

    def test_queue_order_is_preserved(self, manager):
        tasks = self._enqueue(manager, 3)
        assert [t.id for t in manager.tasks] == [t.id for t in tasks]

    def test_counts_reflect_status(self, manager):
        tasks = self._enqueue(manager, 4)
        tasks[0].status = DownloadStatus.DOWNLOADING
        tasks[1].status = DownloadStatus.COMPLETE
        tasks[2].status = DownloadStatus.FAILED

        counts = manager.counts()
        assert counts == {"active": 1, "pending": 1, "complete": 1, "failed": 1, "total": 4}

    def test_has_work_tracks_unfinished_items(self, manager):
        task = self._enqueue(manager)[0]
        assert manager.has_work
        task.status = DownloadStatus.COMPLETE
        assert not manager.has_work

    def test_remove(self, manager):
        task = self._enqueue(manager)[0]
        assert manager.remove(task.id) is True
        assert manager.task(task.id) is None
        assert manager.remove(task.id) is False

    def test_reorder(self, manager):
        tasks = self._enqueue(manager, 3)
        manager.move(tasks[2].id, -2)
        assert [t.id for t in manager.tasks][0] == tasks[2].id

    def test_reorder_clamps_at_the_edges(self, manager):
        tasks = self._enqueue(manager, 2)
        assert manager.move(tasks[0].id, -5) is False
        manager.move(tasks[0].id, 99)
        assert [t.id for t in manager.tasks][-1] == tasks[0].id

    def test_clear_finished_only_removes_terminal_items(self, manager):
        tasks = self._enqueue(manager, 3)
        tasks[0].status = DownloadStatus.COMPLETE
        tasks[1].status = DownloadStatus.FAILED
        assert manager.clear_finished() == 2
        assert len(manager.tasks) == 1

    def test_cancelling_a_pending_task_marks_it_immediately(self, manager):
        task = self._enqueue(manager)[0]
        manager._tokens[task.id] = _token()
        manager.cancel(task.id)
        assert task.status == DownloadStatus.CANCELLED

    def test_mark_complete_records_the_outcome(self, manager):
        task = self._enqueue(manager)[0]
        manager.mark_complete(task, "/library/x.mp3", 42)
        assert task.status == DownloadStatus.COMPLETE
        assert task.output_path == "/library/x.mp3"
        assert task.media_id == 42
        assert task.finished_at

    def test_mark_failed_records_the_reason(self, manager):
        task = self._enqueue(manager)[0]
        manager.mark_failed(task, "Nope", "detail")
        assert task.status == DownloadStatus.FAILED
        assert task.error == "Nope"
        assert task.error_detail == "detail"

    def test_concurrency_can_change_at_runtime(self, manager):
        manager.set_concurrency(4)
        assert manager.concurrency == 4
        manager.set_concurrency(1)
        assert manager.concurrency == 1

    def test_concurrency_is_bounded(self, manager):
        manager.set_concurrency(999)
        assert manager.concurrency == 8
        manager.set_concurrency(0)
        assert manager.concurrency == 1

    def test_signals_fire_on_enqueue(self, manager):
        seen = []
        manager.task_added.connect(seen.append)
        self._enqueue(manager)
        assert len(seen) == 1


def _token():
    from app.downloader.manager import _CancelToken

    return _CancelToken()


class TestConcurrencyLimiter:
    """The limiter must survive being adjusted while work is in flight."""

    def _limiter(self, limit=2):
        from app.downloader.manager import ConcurrencyLimiter

        return ConcurrencyLimiter(limit)

    def test_admits_up_to_the_limit(self):
        limiter = self._limiter(2)
        assert limiter.acquire() and limiter.acquire()
        assert limiter.running == 2

    def test_release_frees_a_slot(self):
        limiter = self._limiter(1)
        limiter.acquire()
        limiter.release()
        assert limiter.running == 0
        assert limiter.acquire()

    def test_a_waiting_worker_starts_when_the_limit_is_raised(self):
        import threading

        limiter = self._limiter(1)
        limiter.acquire()

        started = threading.Event()

        def waiter():
            limiter.acquire()
            started.set()

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        assert not started.wait(0.3), "should still be waiting at limit 1"

        limiter.set_limit(2)
        assert started.wait(2.0), "raising the limit must release the waiter"
        thread.join(1)

    def test_a_cancelled_worker_stops_waiting(self):
        import threading

        limiter = self._limiter(1)
        limiter.acquire()

        token = _token()
        result = {}

        def waiter():
            result["ok"] = limiter.acquire(token)

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        token.cancel()
        thread.join(2)

        assert result.get("ok") is False
        assert limiter.running == 1, "a cancelled waiter must not take a slot"

    def test_lowering_the_limit_does_not_interrupt_running_work(self):
        limiter = self._limiter(4)
        for _ in range(4):
            limiter.acquire()
        limiter.set_limit(1)
        assert limiter.running == 4, "already-running downloads keep going"

    def test_the_limit_is_bounded(self):
        limiter = self._limiter(2)
        limiter.set_limit(999)
        assert limiter.limit == 8
        limiter.set_limit(0)
        assert limiter.limit == 1

    def test_release_never_goes_negative(self):
        limiter = self._limiter(1)
        limiter.release()
        limiter.release()
        assert limiter.running == 0
