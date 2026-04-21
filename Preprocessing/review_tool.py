import sys
import csv
import array as _array
import wave as _wave
from pathlib import Path

# To install the required PyQt6 libraries for this code, run:
# pip install PyQt6 PyQt6-Qt6 PyQt6-sip

# For PyQt6 Multimedia support (QMediaPlayer, QAudioOutput), also install:
# pip install PyQt6.QtMultimedia

# Then, you can safely import:
from PyQt6.QtCore import Qt, QUrl, QRectF, QPointF, QRect, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QTextEdit, QPushButton, QLabel,
    QSplitter, QMessageBox, QStyledItemDelegate, QStyle,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# ── CONFIG ────────────────────────────────────────────────────────────────────
_ROOT    = Path(__file__).resolve().parent.parent
# Directory produced by pipeline.py:
#   chunk_000.wav + chunk_000.txt
#   chunk_001.wav + chunk_001.txt
OUTPUT_DIR = str(_ROOT / "Preprocessing" / "Alla_output")
# Optional review state persisted separately (stem, reviewed)
REVIEW_STATE_CSV = str(Path(OUTPUT_DIR) / "review_state.csv")
# ─────────────────────────────────────────────────────────────────────────────

STATUS_ROLE = Qt.ItemDataRole.UserRole + 1

ACCENT_REVIEWED   = "#198754"
ACCENT_DIRTY      = "#ffc107"
ACCENT_UNREVIEWED = "#ced4da"

APP_STYLE = """
QMainWindow, QWidget {
    background-color: #f0f2f5;
    font-family: 'Segoe UI';
    font-size: 13px;
    color: #212121;
}
QSplitter::handle {
    background: #dee2e6;
    width: 2px;
}
#leftPanel {
    background: #ffffff;
    border-right: 1px solid #e0e0e0;
}
QListWidget {
    background: #ffffff;
    border: none;
    outline: none;
    padding: 0;
}
#rightPanel {
    background: #f0f2f5;
}
#playerCard {
    background: #1a1d23;
    border-radius: 10px;
}
QTextEdit {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 12px;
    font-size: 15px;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
}
QPushButton {
    background-color: #0d6efd;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton:hover    { background-color: #0b5ed7; }
QPushButton:pressed  { background-color: #0a58ca; }
QPushButton:disabled { background-color: #ced4da; color: #6c757d; }
#playBtn {
    background-color: transparent;
    border-radius: 18px;
    font-size: 15px;
    color: #ffffff;
    padding: 0px;
    border: 2px solid #495057;
}
#playBtn:hover   { background-color: #2d3139; border-color: #adb5bd; }
#playBtn:pressed { background-color: #111318; }
#playBtn:disabled { border-color: #343a40; color: #495057; }
#reviewBtn { background-color: #198754; }
#reviewBtn:hover   { background-color: #157347; }
#reviewBtn:pressed { background-color: #146c43; }
QLabel { color: #212121; }
#sectionLabel {
    font-weight: 700;
    font-size: 10px;
    color: #6c757d;
    letter-spacing: 1.5px;
    padding: 10px 14px 4px 14px;
}
#fileLabel { color: #6c757d; font-size: 12px; }
#timeLabel { color: #adb5bd; font-family: 'Consolas'; font-size: 12px; }
#legendLabel { font-size: 11px; color: #6c757d; }
"""


# ── Waveform widget ───────────────────────────────────────────────────────────

class WaveformWidget(QWidget):
    """Displays a waveform and emits seek_requested(ms) on click/drag."""

    seek_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars: list[float] = []
        self._duration_ms: int  = 0
        self._position_ms: int  = 0
        self._hover_x: int      = -1
        self._dragging: bool    = False
        self.setMinimumHeight(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def load_wav(self, path: str):
        try:
            self._bars = _read_waveform(path)
        except Exception:
            self._bars = []
        self.update()

    def clear(self):
        self._bars       = []
        self._duration_ms = 0
        self._position_ms = 0
        self.update()

    def set_duration(self, ms: int):
        self._duration_ms = ms
        self.update()

    def set_position(self, ms: int):
        self._position_ms = ms
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, QColor("#1a1d23"))

        if not self._bars:
            painter.setPen(QColor("#495057"))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "No audio loaded")
            painter.end()
            return

        n        = len(self._bars)
        bar_w    = w / n
        mid      = h / 2
        progress = self._position_ms / self._duration_ms if self._duration_ms > 0 else 0
        prog_x   = progress * w

        for i, amp in enumerate(self._bars):
            x     = i * bar_w
            bh    = max(2.0, amp * (h - 12))
            y     = mid - bh / 2
            color = QColor("#0d6efd") if x < prog_x else QColor("#3a3f4b")
            painter.fillRect(QRectF(x + 0.5, y, max(1.0, bar_w - 1.0), bh), color)

        # Playhead line
        if prog_x > 0:
            painter.setPen(QPen(QColor("#ffffff"), 1.5))
            painter.drawLine(QPointF(prog_x, 0), QPointF(prog_x, h))

        # Hover indicator + time label
        if self._hover_x >= 0 and self._duration_ms > 0:
            painter.setPen(QPen(QColor("#6c757d"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(self._hover_x, 0), QPointF(self._hover_x, h))
            hover_ms = int(self._hover_x / w * self._duration_ms) if w > 0 else 0
            painter.setPen(QColor("#e9ecef"))
            painter.setFont(QFont("Consolas", 9))
            text_x = min(float(self._hover_x + 6), float(w - 46))
            painter.drawText(QPointF(text_x, 14.0), _fmt(hover_ms))

        painter.end()

    def _emit_seek(self, x: float):
        if self._duration_ms > 0 and self.width() > 0:
            ratio = max(0.0, min(1.0, x / self.width()))
            self.seek_requested.emit(int(ratio * self._duration_ms))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._emit_seek(event.position().x())

    def mouseMoveEvent(self, event):
        self._hover_x = int(event.position().x())
        if self._dragging:
            self._emit_seek(event.position().x())
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def leaveEvent(self, _event):
        self._hover_x = -1
        self.update()


# ── Segment list delegate ─────────────────────────────────────────────────────

class SegmentDelegate(QStyledItemDelegate):
    """Draws list items with a status accent bar, bypassing stylesheet color conflicts."""

    _STATUS: dict[str, tuple[str, str]] = {
        "reviewed":   ("#eaf5eb", ACCENT_REVIEWED),
        "dirty":      ("#fffdf0", ACCENT_DIRTY),
        "unreviewed": ("#ffffff", ACCENT_UNREVIEWED),
    }

    def paint(self, painter, option, index):
        painter.save()
        rect     = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered  = bool(option.state & QStyle.StateFlag.State_MouseOver)
        status   = index.data(STATUS_ROLE) or "unreviewed"
        bg_hex, accent_hex = self._STATUS.get(status, ("#ffffff", ACCENT_UNREVIEWED))

        if selected:
            painter.fillRect(rect, QColor("#0d6efd"))
        elif hovered:
            painter.fillRect(rect, QColor("#e8f0fe"))
        else:
            painter.fillRect(rect, QColor(bg_hex))

        # Left accent bar
        if not selected:
            painter.fillRect(QRect(rect.left(), rect.top(), 4, rect.height()), QColor(accent_hex))

        # Bottom divider
        painter.setPen(QColor("#f0f0f0"))
        painter.drawLine(rect.left() + 4, rect.bottom(), rect.right(), rect.bottom())

        # Label text
        painter.setPen(QColor("#ffffff") if selected else QColor("#212121"))
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(rect.adjusted(14, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, index.data())
        painter.restore()

    def sizeHint(self, _option, _index):
        return QSize(220, 44)


# ── Main window ───────────────────────────────────────────────────────────────

class ReviewTool(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ASR Review Tool")
        self.resize(1200, 720)

        self.output_dir = Path(OUTPUT_DIR)
        self.review_state_csv = Path(REVIEW_STATE_CSV)

        self.data: dict[str, dict] = {}
        self.current_stem: str | None = None
        self._loading = False

        self._load_output_dir()
        self._build_ui()
        self._build_player()
        self._populate_list()
        self._setup_shortcuts()

    # ── Output dir I/O (wav/txt pairs) ───────────────────────────────────────

    def _load_output_dir(self):
        self.data.clear()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        reviewed_map: dict[str, bool] = {}
        if self.review_state_csv.exists():
            with open(self.review_state_csv, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    reviewed_map[row.get("stem", "")] = row.get("reviewed", "").lower() == "true"

        wav_files = sorted(self.output_dir.glob("*.wav"))
        for wav_path in wav_files:
            stem = wav_path.stem
            txt_path = self.output_dir / f"{stem}.txt"
            transcription = txt_path.read_text(encoding="utf-8") if txt_path.exists() else ""
            self.data[stem] = {
                "filename": wav_path.name,
                "transcription": transcription,
                "reviewed": reviewed_map.get(stem, False),
                "dirty": False,
            }

    def _save_review_state(self):
        rows = [
            {"stem": stem, "reviewed": str(d["reviewed"])}
            for stem, d in sorted(self.data.items())
        ]
        with open(self.review_state_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["stem", "reviewed"])
            writer.writeheader()
            writer.writerows(rows)

    def _save_current_txt(self):
        if self.current_stem is None:
            return
        d = self.data[self.current_stem]
        txt_path = self.output_dir / f"{self.current_stem}.txt"
        txt_path.write_text(d["transcription"], encoding="utf-8")
        d["dirty"] = False
        self._save_review_state()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left panel ───────────────────────────────────────────────────────
        left = QWidget()
        left.setObjectName("leftPanel")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        seg_lbl = QLabel("SEGMENTS")
        seg_lbl.setObjectName("sectionLabel")
        ll.addWidget(seg_lbl)

        self.file_list = QListWidget()
        self.file_list.setMinimumWidth(220)
        self.file_list.setMouseTracking(True)
        self.file_list.setItemDelegate(SegmentDelegate(self.file_list))
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        ll.addWidget(self.file_list)

        legend = QHBoxLayout()
        legend.setContentsMargins(14, 6, 14, 10)
        legend.setSpacing(4)
        for accent, label in [
            (ACCENT_REVIEWED,   "Reviewed"),
            (ACCENT_DIRTY,      "Unsaved"),
            (ACCENT_UNREVIEWED, "Unreviewed"),
        ]:
            dot = QLabel("▌")
            dot.setStyleSheet(f"color: {accent}; font-size: 14px;")
            lbl = QLabel(label)
            lbl.setObjectName("legendLabel")
            legend.addWidget(dot)
            legend.addWidget(lbl)
            legend.addSpacing(4)
        legend.addStretch()
        ll.addLayout(legend)

        # ── Right panel ──────────────────────────────────────────────────────
        right = QWidget()
        right.setObjectName("rightPanel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 12, 16, 12)
        rl.setSpacing(10)

        self.file_label = QLabel("Select a segment to begin")
        self.file_label.setObjectName("fileLabel")
        rl.addWidget(self.file_label)

        # Dark player card
        player_card = QWidget()
        player_card.setObjectName("playerCard")
        pc = QVBoxLayout(player_card)
        pc.setContentsMargins(14, 10, 14, 12)
        pc.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("playBtn")
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_playback)
        top_row.addWidget(self.play_btn)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("timeLabel")
        top_row.addWidget(self.time_label)
        top_row.addStretch()

        pc.addLayout(top_row)

        self.waveform = WaveformWidget()
        self.waveform.seek_requested.connect(self._seek)
        pc.addWidget(self.waveform)

        rl.addWidget(player_card)

        tx_lbl = QLabel("TRANSCRIPTION")
        tx_lbl.setObjectName("sectionLabel")
        tx_lbl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(tx_lbl)

        self.editor = QTextEdit()
        self.editor.setFont(QFont("Segoe UI", 14))
        self.editor.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.editor.textChanged.connect(self._on_text_changed)
        rl.addWidget(self.editor)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.save_btn = QPushButton("Save  (Ctrl+S)")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_current)
        btn_row.addWidget(self.save_btn)

        self.review_btn = QPushButton("✓  Mark as Reviewed")
        self.review_btn.setObjectName("reviewBtn")
        self.review_btn.setEnabled(False)
        self.review_btn.clicked.connect(self._mark_reviewed)
        btn_row.addWidget(self.review_btn)

        btn_row.addStretch()
        rl.addLayout(btn_row)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 940])

        ml = QHBoxLayout(central)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        ml.addWidget(splitter)

    def _build_player(self):
        self.player = QMediaPlayer()
        self.audio_out = QAudioOutput()
        self.player.setAudioOutput(self.audio_out)
        self.audio_out.setVolume(1.0)
        self.player.playbackStateChanged.connect(self._on_playback_state_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._save_current)

    # ── File list ─────────────────────────────────────────────────────────────

    def _populate_list(self):
        self.file_list.clear()
        wav_stems = {p.stem for p in self.output_dir.glob("*.wav")} if self.output_dir.exists() else set()
        for stem in sorted(wav_stems):
            if stem not in self.data:
                txt_path = self.output_dir / f"{stem}.txt"
                self.data[stem] = {
                    "filename": stem + ".wav",
                    "transcription": txt_path.read_text(encoding="utf-8") if txt_path.exists() else "",
                    "reviewed": False,
                    "dirty": False,
                }
            item = QListWidgetItem(_short_label(stem))
            item.setData(Qt.ItemDataRole.UserRole, stem)
            self._set_item_status(item, stem)
            self.file_list.addItem(item)

    def _set_item_status(self, item: QListWidgetItem, stem: str):
        d = self.data.get(stem, {})
        if d.get("dirty"):
            status = "dirty"
        elif d.get("reviewed"):
            status = "reviewed"
        else:
            status = "unreviewed"
        item.setData(STATUS_ROLE, status)

    def _refresh_item(self, stem: str):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == stem:
                self._set_item_status(item, stem)
                self.file_list.update(self.file_list.indexFromItem(item))
                break

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_file_selected(self, current: QListWidgetItem, _prev: QListWidgetItem):
        if current is None:
            return
        stem = current.data(Qt.ItemDataRole.UserRole)
        if stem == self.current_stem:
            return
        self.current_stem = stem
        d = self.data[stem]

        self._loading = True
        self.editor.setPlainText(d["transcription"])
        self._loading = False

        self.file_label.setText(d["filename"])
        self.save_btn.setEnabled(d["dirty"])
        self.review_btn.setEnabled(True)
        self._apply_editor_bg(d["dirty"])

        self.player.stop()
        self.waveform.clear()
        wav_path = self.output_dir / (stem + ".wav")
        if wav_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(wav_path)))
            self.waveform.load_wav(str(wav_path))
            self.play_btn.setEnabled(True)
        else:
            self.player.setSource(QUrl())
            self.time_label.setText("No WAV")
            self.play_btn.setEnabled(False)

    # ── Editor ────────────────────────────────────────────────────────────────

    def _on_text_changed(self):
        if self._loading or self.current_stem is None:
            return
        d = self.data[self.current_stem]
        d["transcription"] = self.editor.toPlainText()
        d["dirty"] = True
        self.save_btn.setEnabled(True)
        self._apply_editor_bg(True)
        self._refresh_item(self.current_stem)

    def _apply_editor_bg(self, dirty: bool):
        bg = "#fffde7" if dirty else "#ffffff"
        self.editor.setStyleSheet(f"QTextEdit {{ background-color: {bg}; color: #212121; }}")

    # ── Save / review ─────────────────────────────────────────────────────────

    def _save_current(self):
        if self.current_stem is None:
            return
        self._save_current_txt()
        self.save_btn.setEnabled(False)
        self._apply_editor_bg(False)
        self._refresh_item(self.current_stem)

    def _mark_reviewed(self):
        if self.current_stem is None:
            return
        d = self.data[self.current_stem]
        d["reviewed"] = True
        self._save_current_txt()
        self.save_btn.setEnabled(False)
        self._apply_editor_bg(False)
        self._refresh_item(self.current_stem)

    # ── Player ────────────────────────────────────────────────────────────────

    def _toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _seek(self, ms: int):
        self.player.setPosition(ms)

    def _on_playback_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("⏸" if playing else "▶")

    def _on_duration_changed(self, ms: int):
        self.waveform.set_duration(ms)
        self.time_label.setText(f"0:00 / {_fmt(ms)}")

    def _on_position_changed(self, ms: int):
        self.waveform.set_position(ms)
        self.time_label.setText(f"{_fmt(ms)} / {_fmt(self.player.duration())}")

    # ── Keyboard & close ──────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not self.editor.hasFocus():
            self._toggle_playback()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        dirty = [s for s, d in self.data.items() if d["dirty"]]
        if not dirty:
            event.accept()
            return
        reply = QMessageBox.question(
            self, "Unsaved Changes",
            f"You have {len(dirty)} unsaved file(s). Save before closing?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Save all dirty transcripts to their .txt files.
            for stem, d in self.data.items():
                if d["dirty"]:
                    txt_path = self.output_dir / f"{stem}.txt"
                    txt_path.write_text(d["transcription"], encoding="utf-8")
                    d["dirty"] = False
            self._save_review_state()
            event.accept()
        elif reply == QMessageBox.StandardButton.No:
            event.accept()
        else:
            event.ignore()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def _short_label(stem: str) -> str:
    parts = stem.split("-")
    if len(parts) >= 3 and parts[-1].startswith("seg"):
        def _ts(raw: str) -> str:
            return raw.rsplit(".", 1)[0].replace(".", ":")
        return f"{parts[-1]}    {_ts(parts[-3])} – {_ts(parts[-2])}"
    return stem


def _read_waveform(wav_path: str, n_bars: int = 200) -> list[float]:
    with _wave.open(wav_path, "rb") as wf:
        n_frames     = wf.getnframes()
        sample_width = wf.getsampwidth()
        n_channels   = wf.getnchannels()
        raw          = wf.readframes(n_frames)

    if sample_width == 2:
        samples: list[int] = list(_array.array("h", raw))
    elif sample_width == 1:
        samples = [b - 128 for b in raw]
    else:
        return [0.0] * n_bars

    if n_channels > 1:
        samples = samples[::n_channels]

    if not samples:
        return [0.0] * n_bars

    max_val    = max(abs(max(samples)), abs(min(samples)), 1)
    chunk_size = max(1, len(samples) // n_bars)
    bars: list[float] = []
    for i in range(n_bars):
        chunk = samples[i * chunk_size : (i + 1) * chunk_size]
        if chunk:
            rms = (sum(s * s for s in chunk) / len(chunk)) ** 0.5
            bars.append(rms / max_val)
        else:
            bars.append(0.0)
    return bars


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    window = ReviewTool()
    window.show()
    sys.exit(app.exec())
