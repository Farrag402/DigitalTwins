import argparse
import sys
import csv
import json
import os
import array as _array
import wave as _wave
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, QRectF, QPointF, QRect, QSize, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QKeySequence, QShortcut, QPainter, QPen, QPainterPath,
    QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListWidget, QListWidgetItem, QTextEdit, QTextBrowser, QPushButton, QLabel,
    QSplitter, QMessageBox, QStyledItemDelegate, QStyle,
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# ── DEFAULTS (used when launched without CLI args) ────────────────────────────
_ROOT            = Path(__file__).resolve().parent.parent
_DEFAULT_CSV     = _ROOT / "Dataset" / "transcriptions.csv"
_DEFAULT_WAV_DIR = _ROOT / "Dataset" / "WAV"
# ─────────────────────────────────────────────────────────────────────────────

STATUS_ROLE = Qt.ItemDataRole.UserRole + 1

ACCENT_ACCEPTED = "#198754"
ACCENT_REJECTED = "#dc3545"
ACCENT_DIRTY    = "#ffc107"
ACCENT_PENDING  = "#ced4da"

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
QTextBrowser {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 14px;
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
#acceptBtn { background-color: #198754; }
#acceptBtn:hover   { background-color: #157347; }
#acceptBtn:pressed { background-color: #146c43; }
#rejectBtn { background-color: #dc3545; }
#rejectBtn:hover   { background-color: #bb2d3b; }
#rejectBtn:pressed { background-color: #b02a37; }
#cropBtn {
    background-color: #6c757d;
    color: #ffffff;
    border: none;
    border-radius: 5px;
    padding: 4px 14px;
    font-weight: 600;
    font-size: 12px;
}
#cropBtn:hover   { background-color: #5c636a; }
#cropBtn:pressed { background-color: #565e64; }
#cropBtn:checked { background-color: #6f42c1; }
#cropBtn:checked:hover { background-color: #5a35a8; }
#resetCropBtn {
    background-color: #495057;
    color: #ffffff;
    border: none;
    border-radius: 5px;
    padding: 4px 14px;
    font-weight: 600;
    font-size: 12px;
}
#resetCropBtn:hover { background-color: #3d4349; }
#applyBtn {
    background-color: #0d6efd;
    color: #ffffff;
    border: none;
    border-radius: 5px;
    padding: 4px 14px;
    font-weight: 600;
    font-size: 12px;
}
#applyBtn:hover    { background-color: #0b5ed7; }
#applyBtn:disabled { background-color: #343a40; color: #6c757d; }
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
#cutReasonLabel {
    font-size: 11px;
    color: #495057;
    background-color: #e9ecef;
    border-radius: 4px;
    padding: 2px 8px;
}
"""


# ── Waveform widget ───────────────────────────────────────────────────────────

class WaveformWidget(QWidget):
    """Waveform display with playhead seek, start/end trim handles, and middle cut region."""

    seek_requested     = pyqtSignal(int)        # ms
    trim_changed       = pyqtSignal(int, int)   # left_ms, right_ms
    cut_region_changed = pyqtSignal(int, int)   # start_ms, end_ms

    _HANDLE_HIT_PX = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bars: list[float] = []
        self._duration_ms: int  = 0
        self._position_ms: int  = 0
        self._hover_x: int      = -1

        # Crop state
        self._mode: str               = "seek"   # "seek" | "cut"
        self._trim_start_ms: int      = 0
        self._trim_end_ms: int | None = None     # None = full duration
        self._cut_start_ms: int | None = None
        self._cut_end_ms:   int | None = None

        # Drag state
        self._drag_target: str | None = None     # "left_handle"|"right_handle"|"cut_drag"|"seek"
        self._cut_anchor_ms: int      = 0

        self.setMinimumHeight(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_wav(self, path: str):
        try:
            self._bars = _read_waveform(path)
        except Exception:
            self._bars = []
        self.update()

    def clear(self):
        self._bars         = []
        self._duration_ms  = 0
        self._position_ms  = 0
        self._trim_start_ms = 0
        self._trim_end_ms  = None
        self._cut_start_ms = None
        self._cut_end_ms   = None
        self.update()

    def set_duration(self, ms: int):
        self._duration_ms = ms
        self.update()

    def set_position(self, ms: int):
        self._position_ms = ms
        self.update()

    def set_mode(self, mode: str):
        self._mode = mode
        if mode == "cut":
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def reset_crop(self):
        self._trim_start_ms = 0
        self._trim_end_ms   = None
        self._cut_start_ms  = None
        self._cut_end_ms    = None
        self._drag_target   = None
        self.trim_changed.emit(0, self._duration_ms)
        self.update()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_trim_end(self) -> int:
        return self._trim_end_ms if self._trim_end_ms is not None else self._duration_ms

    def _ms_to_x(self, ms: int) -> float:
        if self._duration_ms <= 0 or self.width() <= 0:
            return 0.0
        return ms / self._duration_ms * self.width()

    def _x_to_ms(self, x: float) -> int:
        if self._duration_ms <= 0 or self.width() <= 0:
            return 0
        return int(max(0.0, min(1.0, x / self.width())) * self._duration_ms)

    def _hit_handle(self, x: float) -> str | None:
        if self._duration_ms <= 0:
            return None
        if abs(x - self._ms_to_x(self._trim_start_ms)) <= self._HANDLE_HIT_PX:
            return "left_handle"
        if abs(x - self._ms_to_x(self._get_trim_end())) <= self._HANDLE_HIT_PX:
            return "right_handle"
        return None

    # ── Paint ─────────────────────────────────────────────────────────────────

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

        trim_start_x = self._ms_to_x(self._trim_start_ms)
        trim_end_x   = self._ms_to_x(self._get_trim_end())

        # Bars — dimmed outside the trim region
        for i, amp in enumerate(self._bars):
            x  = i * bar_w
            bh = max(2.0, amp * (h - 12))
            y  = mid - bh / 2
            bar_center = x + bar_w / 2
            in_trim = trim_start_x <= bar_center <= trim_end_x
            if in_trim:
                color = QColor("#0d6efd") if x < prog_x else QColor("#3a3f4b")
            else:
                color = QColor("#252830")
            painter.fillRect(QRectF(x + 0.5, y, max(1.0, bar_w - 1.0), bh), color)

        # Middle cut region overlay
        if self._cut_start_ms is not None and self._cut_end_ms is not None:
            cs_x = self._ms_to_x(self._cut_start_ms)
            ce_x = self._ms_to_x(self._cut_end_ms)
            painter.fillRect(QRectF(cs_x, 0, ce_x - cs_x, h), QColor(220, 53, 69, 70))
            painter.setPen(QPen(QColor("#dc3545"), 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(cs_x, 0), QPointF(cs_x, h))
            painter.drawLine(QPointF(ce_x, 0), QPointF(ce_x, h))

        # Playhead
        if prog_x > 0:
            painter.setPen(QPen(QColor("#ffffff"), 1.5))
            painter.drawLine(QPointF(prog_x, 0), QPointF(prog_x, h))

        # Trim handles
        if self._duration_ms > 0:
            # Left (start) handle — green
            if self._trim_start_ms > 0:
                painter.setPen(QPen(QColor("#198754"), 2))
                painter.drawLine(QPointF(trim_start_x, 0), QPointF(trim_start_x, h))
            path = QPainterPath()
            path.moveTo(trim_start_x, 4)
            path.lineTo(trim_start_x + 9, 8)
            path.lineTo(trim_start_x, 13)
            path.closeSubpath()
            painter.fillPath(path, QColor("#198754"))

            # Right (end) handle — orange
            if self._trim_end_ms is not None:
                painter.setPen(QPen(QColor("#fd7e14"), 2))
                painter.drawLine(QPointF(trim_end_x, 0), QPointF(trim_end_x, h))
            path = QPainterPath()
            path.moveTo(trim_end_x, 4)
            path.lineTo(trim_end_x - 9, 8)
            path.lineTo(trim_end_x, 13)
            path.closeSubpath()
            painter.fillPath(path, QColor("#fd7e14"))

        # Hover time tooltip
        if self._hover_x >= 0 and self._duration_ms > 0:
            painter.setPen(QPen(QColor("#6c757d"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(self._hover_x, 0), QPointF(self._hover_x, h))
            hover_ms = int(self._hover_x / w * self._duration_ms) if w > 0 else 0
            painter.setPen(QColor("#e9ecef"))
            painter.setFont(QFont("Consolas", 9))
            text_x = min(float(self._hover_x + 6), float(w - 46))
            painter.drawText(QPointF(text_x, 14.0), _fmt(hover_ms))

        painter.end()

    # ── Mouse events ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        if self._mode == "cut":
            ms = self._x_to_ms(x)
            self._drag_target   = "cut_drag"
            self._cut_anchor_ms = ms
            self._cut_start_ms  = ms
            self._cut_end_ms    = ms
            self.update()
        else:
            handle = self._hit_handle(x)
            if handle:
                self._drag_target = handle
            else:
                self._drag_target = "seek"
                self._emit_seek(x)

    def mouseMoveEvent(self, event):
        x = event.position().x()
        self._hover_x = int(x)

        if self._drag_target == "seek":
            self._emit_seek(x)

        elif self._drag_target == "left_handle":
            ms = self._x_to_ms(x)
            ms = max(0, min(ms, self._get_trim_end() - 100))
            self._trim_start_ms = ms
            self.trim_changed.emit(self._trim_start_ms, self._get_trim_end())

        elif self._drag_target == "right_handle":
            ms = self._x_to_ms(x)
            ms = max(self._trim_start_ms + 100, min(ms, self._duration_ms))
            self._trim_end_ms = ms
            self.trim_changed.emit(self._trim_start_ms, self._get_trim_end())

        elif self._drag_target == "cut_drag":
            ms = self._x_to_ms(x)
            if ms < self._cut_anchor_ms:
                self._cut_start_ms = ms
                self._cut_end_ms   = self._cut_anchor_ms
            else:
                self._cut_start_ms = self._cut_anchor_ms
                self._cut_end_ms   = ms

        elif self._mode == "seek":
            handle = self._hit_handle(x)
            self.setCursor(
                Qt.CursorShape.SizeHorCursor if handle
                else Qt.CursorShape.PointingHandCursor
            )

        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag_target == "cut_drag":
            if (self._cut_start_ms is not None
                    and self._cut_end_ms is not None
                    and self._cut_end_ms - self._cut_start_ms >= 50):
                self.cut_region_changed.emit(self._cut_start_ms, self._cut_end_ms)
            else:
                self._cut_start_ms = None
                self._cut_end_ms   = None
                self.update()
        self._drag_target = None

    def leaveEvent(self, _event):
        self._hover_x = -1
        self.update()

    def _emit_seek(self, x: float):
        if self._duration_ms > 0 and self.width() > 0:
            ratio = max(0.0, min(1.0, x / self.width()))
            self.seek_requested.emit(int(ratio * self._duration_ms))


# ── Word alignment panel ──────────────────────────────────────────────────────

class _WordBrowser(QTextBrowser):
    """
    QTextBrowser subclass that reliably detects anchor clicks via anchorAt().
    QTextBrowser.anchorClicked is unreliable with custom URL schemes set through
    setHtml(), so we intercept mouse-press and emit the signal ourselves.
    """

    href_clicked = pyqtSignal(str)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # anchorAt() needs QPoint; PyQt may give either QPoint or QPointF here.
            pos = event.pos()
            if hasattr(pos, "toPoint"):
                pos = pos.toPoint()
            href = self.anchorAt(pos)
            if href:
                self.href_clicked.emit(href)
                return
        super().mousePressEvent(event)


class WordPanel(QWidget):
    """
    Scrollable panel showing individually clickable word tokens from an alignment JSON.

    - Clicking a word that is NOT in a crop region seeks the player to that word.
    - Clicking a word that IS in a crop region toggles its link (linked = will be
      removed on Apply Crop; unlinked = kept despite being in the removed region).
    - Linked words in a removed region are highlighted red.
    - Unlinked words in a removed region are highlighted orange.
    """

    word_clicked = pyqtSignal(int)   # seek to ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self._words:     list[dict] = []
        self._linked:    list[bool] = []   # True = will be removed on crop
        self._in_region: list[bool] = []   # True = overlaps a removed time range

        self._browser = _WordBrowser()
        self._browser.setOpenLinks(False)
        self._browser.setOpenExternalLinks(False)
        self._browser.href_clicked.connect(self._on_href_clicked)
        self._browser.setMaximumHeight(90)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._browser)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_words(self, words: list[dict]):
        self._words     = words
        self._linked    = [False] * len(words)
        self._in_region = [False] * len(words)
        self._render()

    def update_crop_regions(self, removed_ranges: list[tuple[float, float]]):
        """
        Given a list of (start_s, end_s) ranges that will be removed, mark words
        that overlap any range.  Newly overlapping words are auto-linked; words that
        leave all ranges are auto-unlinked.
        """
        for i, w in enumerate(self._words):
            ws, we = w["start"], w["end"]
            in_any = any(
                ws < rng_end and we > rng_start
                for rng_start, rng_end in removed_ranges
            )
            if in_any and not self._in_region[i]:
                self._linked[i] = True      # newly enters region → auto-link
            elif not in_any:
                self._linked[i] = False     # left all regions → auto-unlink
            self._in_region[i] = in_any
        self._render()

    def get_words_to_remove(self) -> set[int]:
        return {i for i, linked in enumerate(self._linked) if linked}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _toggle_link(self, idx: int):
        if 0 <= idx < len(self._linked):
            self._linked[idx] = not self._linked[idx]
            self._render()

    def _render(self):
        parts: list[str] = []
        for i, w in enumerate(self._words):
            start_ms = int(w["start"] * 1000)
            text = w["word"]
            href = f"word://{i}/{start_ms}"
            if self._in_region[i] and self._linked[i]:
                # Will be removed on Apply Crop — red; click to unlink (unhighlight)
                style = (
                    "background:#dc3545;color:#fff;"
                    "border-radius:3px;padding:1px 5px;"
                )
            else:
                # Normal / unlinked — no highlight; click to seek OR re-link if in region
                style = "color:#212121;padding:1px 3px;"
            parts.append(
                f'<a href="{href}" style="text-decoration:none;{style}">{text}</a>'
            )
        body = "&nbsp;".join(parts)
        html = (
            '<div dir="rtl" style="'
            "font-family:'Segoe UI';font-size:13px;line-height:2.1;"
            f'">{body}</div>'
        )
        self._browser.setHtml(html)

    def _on_href_clicked(self, href: str):
        if not href:
            return
        if not href.startswith("word://"):
            return
        raw = href[len("word://"):]
        if "/" not in raw:
            return
        left, right = raw.split("/", 1)

        try:
            word_idx = int(left)
            start_ms = int(right)
        except ValueError:
            return

        if not (0 <= word_idx < len(self._in_region)):
            return
        if self._in_region[word_idx]:
            self._toggle_link(word_idx)
        else:
            self.word_clicked.emit(start_ms)


# ── Alignment-aware transcription editor ─────────────────────────────────────

class AlignedTextEdit(QTextEdit):
    """
    A single editable text box that doubles as the word-alignment view.

    When alignment data is loaded:
    - Words that fall in a crop-removed region are highlighted:
        red   = linked (will be deleted on Apply Crop)
        orange = unlinked (manually kept despite being in the region)
    - Left-clicking a highlighted word toggles its link.
    - Left-clicking a non-highlighted word seeks the player to that word's time.
    Normal keyboard editing is always available.
    """

    word_clicked = pyqtSignal(int)   # ms — emitted when a normal word is clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self._words:       list[dict]          = []
        self._char_ranges: list[tuple[int,int]] = []   # logical char (start, end)
        self._start_ms:    list[int]            = []
        self._linked:      list[bool]           = []   # True → removed on Apply Crop
        self._in_region:   list[bool]           = []   # True → overlaps a removed range

    # ── Public API ────────────────────────────────────────────────────────────

    def load_alignment(self, words: list[dict]):
        """
        Store word timestamps and compute character ranges from the current
        plain-text content.  Call AFTER setPlainText() so the text is in place.
        """
        self._words      = words
        self._linked     = [False] * len(words)
        self._in_region  = [False] * len(words)
        self._start_ms   = [int(w["start"] * 1000) for w in words]
        # Build char ranges: words are assumed joined by single spaces.
        self._char_ranges = []
        pos = 0
        for w in words:
            length = len(w["word"])
            self._char_ranges.append((pos, pos + length))
            pos += length + 1   # +1 for the space separator
        self._apply_highlights()

    def clear_alignment(self):
        self._words       = []
        self._char_ranges = []
        self._start_ms    = []
        self._linked      = []
        self._in_region   = []
        self.setExtraSelections([])

    def update_crop_regions(self, removed_ranges: list[tuple[float, float]]):
        """
        Mark words overlapping any (start_s, end_s) range in removed_ranges.
        Words newly entering a range are auto-linked; words leaving all ranges
        are auto-unlinked.
        """
        for i, w in enumerate(self._words):
            ws, we = w["start"], w["end"]
            in_any = any(ws < rng_end and we > rng_start
                         for rng_start, rng_end in removed_ranges)
            if in_any and not self._in_region[i]:
                self._linked[i] = True
            elif not in_any:
                self._linked[i] = False
            self._in_region[i] = in_any
        self._apply_highlights()

    def get_words_to_remove(self) -> set[int]:
        return {i for i, linked in enumerate(self._linked) if linked}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _word_at(self, char_pos: int) -> int | None:
        for i, (start, end) in enumerate(self._char_ranges):
            if start <= char_pos < end:
                return i
        return None

    def _apply_highlights(self):
        selections: list[QTextEdit.ExtraSelection] = []
        for i, (start, end) in enumerate(self._char_ranges):
            if not self._in_region[i]:
                continue
            fmt = QTextCharFormat()
            if self._linked[i]:
                fmt.setBackground(QColor("#dc3545"))
                fmt.setForeground(QColor("#ffffff"))
            else:
                fmt.setBackground(QColor("#fd7e14"))
                fmt.setForeground(QColor("#ffffff"))
            cur = self.textCursor()
            cur.setPosition(start)
            cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cur
            sel.format = fmt
            selections.append(sel)
        self.setExtraSelections(selections)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._char_ranges:
            char_pos = self.cursorForPosition(event.pos()).position()
            idx = self._word_at(char_pos)
            if idx is not None:
                if self._in_region[idx]:
                    self._linked[idx] = not self._linked[idx]
                    self._apply_highlights()
                    return
                else:
                    self.word_clicked.emit(self._start_ms[idx])
                    return
        super().mousePressEvent(event)


# ── Segment list delegate ─────────────────────────────────────────────────────

class SegmentDelegate(QStyledItemDelegate):
    """Draws list items with a status accent bar, bypassing stylesheet color conflicts."""

    _STATUS: dict[str, tuple[str, str]] = {
        "accepted": ("#eaf5eb", ACCENT_ACCEPTED),
        "rejected": ("#fde8e8", ACCENT_REJECTED),
        "dirty":    ("#fffdf0", ACCENT_DIRTY),
        "pending":  ("#ffffff", ACCENT_PENDING),
    }

    def paint(self, painter, option, index):
        painter.save()
        rect     = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered  = bool(option.state & QStyle.StateFlag.State_MouseOver)
        status   = index.data(STATUS_ROLE) or "pending"
        bg_hex, accent_hex = self._STATUS.get(status, ("#ffffff", ACCENT_PENDING))

        if selected:
            painter.fillRect(rect, QColor("#0d6efd"))
        elif hovered:
            painter.fillRect(rect, QColor("#e8f0fe"))
        else:
            painter.fillRect(rect, QColor(bg_hex))

        if not selected:
            painter.fillRect(QRect(rect.left(), rect.top(), 4, rect.height()), QColor(accent_hex))

        painter.setPen(QColor("#f0f0f0"))
        painter.drawLine(rect.left() + 4, rect.bottom(), rect.right(), rect.bottom())

        painter.setPen(QColor("#ffffff") if selected else QColor("#212121"))
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(rect.adjusted(14, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, index.data())
        painter.restore()

    def sizeHint(self, _option, _index):
        return QSize(220, 44)


# ── Main window ───────────────────────────────────────────────────────────────

class ReviewTool(QMainWindow):

    def __init__(self, csv_path: Path, wav_dir: Path, title: str = "ASR Review Tool"):
        super().__init__()
        self.setWindowTitle(title)
        self.resize(1200, 760)

        self.csv_path = Path(csv_path)
        self.wav_dir  = Path(wav_dir)

        self.data: dict[str, dict] = {}
        self.current_stem: str | None = None
        self._loading = False
        self._alignment: list[dict] | None = None
        self._reset_trim_on_duration: bool = False
        self._play_stop_ms: int | None = None   # auto-stop playback at this position

        self._load_csv()
        self._build_ui()
        self._build_player()
        self._populate_list()
        self._setup_shortcuts()

    # ── CSV I/O ───────────────────────────────────────────────────────────────

    def _load_csv(self):
        if not self.csv_path.exists():
            return
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                stem = Path(row["filename"]).stem
                status = row.get("status", "").lower()
                if not status and "reviewed" in row:
                    status = "accepted" if row["reviewed"].lower() == "true" else ""
                self.data[stem] = {
                    "filename":      row["filename"],
                    "transcription": row.get("transcription", ""),
                    "status":        status,
                    "cut_reason":    row.get("cut_reason", ""),
                    "dirty":         False,
                }

    def _save_csv(self):
        rows = [
            {
                "filename":      d["filename"],
                "transcription": d["transcription"],
                "status":        d["status"],
            }
            for d in self.data.values()
        ]
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["filename", "transcription", "status"])
            writer.writeheader()
            writer.writerows(rows)

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
            (ACCENT_ACCEPTED, "Accepted"),
            (ACCENT_REJECTED, "Rejected"),
            (ACCENT_DIRTY,    "Unsaved"),
            (ACCENT_PENDING,  "Pending"),
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

        file_row = QHBoxLayout()
        file_row.setSpacing(10)

        self.file_label = QLabel("Select a segment to begin")
        self.file_label.setObjectName("fileLabel")
        file_row.addWidget(self.file_label)

        self.cut_reason_label = QLabel("")
        self.cut_reason_label.setObjectName("cutReasonLabel")
        self.cut_reason_label.setVisible(False)
        file_row.addWidget(self.cut_reason_label)
        file_row.addStretch()

        rl.addLayout(file_row)

        # ── Player card ──────────────────────────────────────────────────────
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
        self.waveform.trim_changed.connect(self._on_trim_changed)
        self.waveform.cut_region_changed.connect(self._on_cut_region_changed)
        pc.addWidget(self.waveform)

        # Crop controls (inside the dark player card)
        crop_row = QHBoxLayout()
        crop_row.setSpacing(6)

        self.cut_mode_btn = QPushButton("✂  Cut Mode")
        self.cut_mode_btn.setObjectName("cropBtn")
        self.cut_mode_btn.setCheckable(True)
        self.cut_mode_btn.setEnabled(False)
        self.cut_mode_btn.toggled.connect(self._on_cut_mode_toggled)
        crop_row.addWidget(self.cut_mode_btn)

        self.reset_crop_btn = QPushButton("↺  Reset")
        self.reset_crop_btn.setObjectName("resetCropBtn")
        self.reset_crop_btn.setEnabled(False)
        self.reset_crop_btn.clicked.connect(self._on_reset_crop)
        crop_row.addWidget(self.reset_crop_btn)

        crop_row.addStretch()

        self.apply_crop_btn = QPushButton("⚡  Apply Crop")
        self.apply_crop_btn.setObjectName("applyBtn")
        self.apply_crop_btn.setEnabled(False)
        self.apply_crop_btn.clicked.connect(self._on_apply_crop)
        crop_row.addWidget(self.apply_crop_btn)

        pc.addLayout(crop_row)

        rl.addWidget(player_card)

        # ── Transcription section ─────────────────────────────────────────────
        tx_lbl = QLabel("TRANSCRIPTION")
        tx_lbl.setObjectName("sectionLabel")
        tx_lbl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(tx_lbl)

        # Clickable word tokens — visible when an alignment sidecar exists.
        # Click a red word to unlink (exclude from crop). Click it again to re-link.
        # Click a normal word to seek the player to that word's timestamp.
        self.word_panel = WordPanel()
        self.word_panel.setVisible(False)
        self.word_panel.word_clicked.connect(self._seek)
        rl.addWidget(self.word_panel)

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

        self.accept_btn = QPushButton("✓  Accept  (Ctrl+Return)")
        self.accept_btn.setObjectName("acceptBtn")
        self.accept_btn.setEnabled(False)
        self.accept_btn.clicked.connect(self._mark_accepted)
        btn_row.addWidget(self.accept_btn)

        self.reject_btn = QPushButton("✕  Reject  (Ctrl+Del)")
        self.reject_btn.setObjectName("rejectBtn")
        self.reject_btn.setEnabled(False)
        self.reject_btn.clicked.connect(self._mark_rejected)
        btn_row.addWidget(self.reject_btn)

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
        QShortcut(QKeySequence("Ctrl+S"),      self).activated.connect(self._save_current)
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(self._mark_accepted)
        QShortcut(QKeySequence("Ctrl+Delete"), self).activated.connect(self._mark_rejected)

    # ── File list ─────────────────────────────────────────────────────────────

    def _populate_list(self):
        self.file_list.clear()
        wav_stems = {p.stem for p in self.wav_dir.glob("*.wav")} if self.wav_dir.exists() else set()
        for stem in sorted(set(self.data.keys()) | wav_stems):
            if stem not in self.data:
                self.data[stem] = {
                    "filename": stem + ".wav", "transcription": "",
                    "status": "", "cut_reason": "", "dirty": False,
                }
            item = QListWidgetItem(_short_label(stem))
            item.setData(Qt.ItemDataRole.UserRole, stem)
            self._set_item_status(item, stem)
            self.file_list.addItem(item)

    def _set_item_status(self, item: QListWidgetItem, stem: str):
        d = self.data.get(stem, {})
        if d.get("dirty"):
            status = "dirty"
        elif d.get("status") == "accepted":
            status = "accepted"
        elif d.get("status") == "rejected":
            status = "rejected"
        else:
            status = "pending"
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
        cut_reason = d.get("cut_reason", "")
        if cut_reason:
            self.cut_reason_label.setText(f"✂ cut: {cut_reason}")
            self.cut_reason_label.setVisible(True)
        else:
            self.cut_reason_label.setVisible(False)

        self.save_btn.setEnabled(d["dirty"])
        self.accept_btn.setEnabled(True)
        self.reject_btn.setEnabled(True)
        self._apply_editor_bg(d["dirty"])

        # Reset crop UI state
        self.cut_mode_btn.setChecked(False)
        self.cut_mode_btn.setEnabled(False)
        self.reset_crop_btn.setEnabled(False)
        self.apply_crop_btn.setEnabled(False)
        self._reset_trim_on_duration = False

        # Clear word panel
        self._alignment = None
        self.word_panel.setVisible(False)

        self.player.stop()
        self.waveform.clear()

        wav_path = self.wav_dir / (stem + ".wav")
        if wav_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(wav_path)))
            self.waveform.load_wav(str(wav_path))
            self.play_btn.setEnabled(True)
            self.cut_mode_btn.setEnabled(True)
            self.reset_crop_btn.setEnabled(True)
            self._reset_trim_on_duration = True

            # Load alignment sidecar if present
            align_path = self.wav_dir / (stem + "_alignment.json")
            if align_path.exists():
                try:
                    with open(align_path, encoding="utf-8") as f:
                        align_data = json.load(f)
                    words = align_data.get("words", [])
                    if words:
                        self._alignment = words
                        self.word_panel.load_words(words)
                        self.word_panel.setVisible(True)
                except Exception:
                    pass
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
        self.data[self.current_stem]["dirty"] = False
        self._save_csv()
        self.save_btn.setEnabled(False)
        self._apply_editor_bg(False)
        self._refresh_item(self.current_stem)

    def _mark_accepted(self):
        if self.current_stem is None:
            return
        d = self.data[self.current_stem]
        d["status"] = "accepted"
        d["dirty"]  = False
        self._save_csv()
        self.save_btn.setEnabled(False)
        self._apply_editor_bg(False)
        self._refresh_item(self.current_stem)
        self._advance_to_next()

    def _mark_rejected(self):
        if self.current_stem is None:
            return
        d = self.data[self.current_stem]
        d["status"] = "rejected"
        d["dirty"]  = False
        self._save_csv()
        self.save_btn.setEnabled(False)
        self._apply_editor_bg(False)
        self._refresh_item(self.current_stem)
        self._advance_to_next()

    def _advance_to_next(self):
        current_row = self.file_list.currentRow()
        next_row = current_row + 1
        if next_row < self.file_list.count():
            self.file_list.setCurrentRow(next_row)

    # ── Player ────────────────────────────────────────────────────────────────

    def _toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self._play_stop_ms = None
        else:
            start_ms, stop_ms = self._get_play_region()
            if start_ms is not None:
                self.player.setPosition(start_ms)
                self._play_stop_ms = stop_ms
            else:
                self._play_stop_ms = None
            self.player.play()

    def _get_play_region(self) -> tuple[int | None, int | None]:
        """
        Return (start_ms, stop_ms) for constrained playback, or (None, None) for free play.

        Cut Mode + region defined  → preview the section being removed.
        Trim handles moved         → preview the section being kept.
        Neither                    → free play (existing behaviour).
        """
        cut_start  = self.waveform._cut_start_ms
        cut_end    = self.waveform._cut_end_ms
        trim_start = self.waveform._trim_start_ms
        trim_end   = self.waveform._get_trim_end()
        duration   = self.waveform._duration_ms

        if self.cut_mode_btn.isChecked() and cut_start is not None:
            return cut_start, cut_end

        has_trim = trim_start > 0 or (duration > 0 and trim_end < duration)
        if has_trim:
            return trim_start, trim_end

        return None, None

    def _seek(self, ms: int):
        self._play_stop_ms = None   # manual seek cancels the auto-stop region
        self.player.setPosition(ms)

    def _on_playback_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("⏸" if playing else "▶")

    def _on_duration_changed(self, ms: int):
        self.waveform.set_duration(ms)
        self.time_label.setText(f"0:00 / {_fmt(ms)}")
        if self._reset_trim_on_duration:
            self._reset_trim_on_duration = False
            self.waveform.reset_crop()
            # trim_changed emitted by reset_crop will call _on_trim_changed → _update_word_highlights

    def _on_position_changed(self, ms: int):
        self.waveform.set_position(ms)
        self.time_label.setText(f"{_fmt(ms)} / {_fmt(self.player.duration())}")
        if (self._play_stop_ms is not None
                and ms >= self._play_stop_ms
                and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState):
            self.player.pause()
            self._play_stop_ms = None

    # ── Crop controls ─────────────────────────────────────────────────────────

    def _on_cut_mode_toggled(self, checked: bool):
        self.waveform.set_mode("cut" if checked else "seek")

    def _on_trim_changed(self, left_ms: int, right_ms: int):
        duration = self.waveform._duration_ms
        has_trim = left_ms > 0 or (duration > 0 and right_ms < duration)
        has_cut  = self.waveform._cut_start_ms is not None
        self.apply_crop_btn.setEnabled(has_trim or has_cut)
        self._update_word_highlights()

    def _on_cut_region_changed(self, _start_ms: int, _end_ms: int):
        self.apply_crop_btn.setEnabled(True)
        self._update_word_highlights()

    def _on_reset_crop(self):
        self.waveform.reset_crop()
        self.cut_mode_btn.setChecked(False)
        self.apply_crop_btn.setEnabled(False)
        self._play_stop_ms = None
        # word highlights cleared via trim_changed → _on_trim_changed → _update_word_highlights

    def _update_word_highlights(self):
        if self._alignment is None or not self.word_panel.isVisible():
            return
        duration_s = self.waveform._duration_ms / 1000.0
        removed: list[tuple[float, float]] = []

        if self.waveform._trim_start_ms > 0:
            removed.append((0.0, self.waveform._trim_start_ms / 1000.0))
        trim_end_ms = self.waveform._get_trim_end()
        if self.waveform._trim_end_ms is not None and trim_end_ms < self.waveform._duration_ms:
            removed.append((trim_end_ms / 1000.0, duration_s))
        if self.waveform._cut_start_ms is not None:
            removed.append((
                self.waveform._cut_start_ms / 1000.0,
                self.waveform._cut_end_ms / 1000.0,
            ))

        self.word_panel.update_crop_regions(removed)

    def _on_apply_crop(self):
        if self.current_stem is None:
            return
        stem     = self.current_stem
        wav_path = self.wav_dir / (stem + ".wav")
        if not wav_path.exists():
            return

        trim_start_ms  = self.waveform._trim_start_ms
        trim_end_ms    = self.waveform._get_trim_end()
        cut_start_ms   = self.waveform._cut_start_ms
        cut_end_ms     = self.waveform._cut_end_ms

        # Build keep regions
        if cut_start_ms is not None and cut_end_ms is not None:
            keep_regions = [
                (trim_start_ms, cut_start_ms),
                (cut_end_ms,    trim_end_ms),
            ]
        else:
            keep_regions = [(trim_start_ms, trim_end_ms)]

        keep_regions = [(s, e) for s, e in keep_regions if e > s]
        if not keep_regions:
            QMessageBox.warning(self, "Crop", "Nothing to keep — crop region covers the entire clip.")
            return

        # Release the file from the player before writing
        self._play_stop_ms = None
        self.player.stop()
        self.player.setSource(QUrl())
        QApplication.processEvents()

        # Slice the WAV
        try:
            _slice_wav_regions(str(wav_path), str(wav_path), keep_regions)
        except Exception as e:
            QMessageBox.warning(self, "Crop Error", f"Failed to crop audio:\n{e}")
            # Reload original
            self.player.setSource(QUrl.fromLocalFile(str(wav_path)))
            return

        # Build removed ranges (seconds) from the crop controls.
        removed_ranges: list[tuple[float, float]] = []
        total_duration_s = self.waveform._duration_ms / 1000.0
        if self.waveform._trim_start_ms > 0:
            removed_ranges.append((0.0, self.waveform._trim_start_ms / 1000.0))
        if self.waveform._trim_end_ms is not None and trim_end_ms < self.waveform._duration_ms:
            removed_ranges.append((trim_end_ms / 1000.0, total_duration_s))
        if cut_start_ms is not None and cut_end_ms is not None:
            removed_ranges.append((cut_start_ms / 1000.0, cut_end_ms / 1000.0))
        removed_ranges.sort(key=lambda x: x[0])

        # Strip linked words from transcription; mark dirty so user must Save
        d = self.data[stem]
        if self._alignment:
            to_remove = self.word_panel.get_words_to_remove()
            kept = [
                w["word"] for i, w in enumerate(self._alignment)
                if i not in to_remove
            ]
            new_text = " ".join(kept)
            d["transcription"] = new_text
            self._loading = True
            self.editor.setPlainText(new_text)
            self._loading = False

            # Rebuild alignment to match the newly cropped audio so the panel
            # remains usable for a second crop pass.
            #
            # Important: keep/remove must follow the user's explicit link toggles,
            # not only geometric overlap with removed ranges.

            def _removed_before(t_s: float) -> float:
                removed = 0.0
                for r_start, r_end in removed_ranges:
                    if t_s >= r_end:
                        removed += (r_end - r_start)
                    elif r_start < t_s < r_end:
                        removed += (t_s - r_start)
                return removed

            new_alignment: list[dict] = []
            for i, w in enumerate(self._alignment):
                if i in to_remove:
                    continue
                old_start = float(w["start"])
                old_end = float(w["end"])
                shifted_start = max(0.0, old_start - _removed_before(old_start))
                shifted_end = max(shifted_start, old_end - _removed_before(old_end))
                new_alignment.append({
                    "word": w["word"],
                    "start": round(shifted_start, 3),
                    "end": round(shifted_end, 3),
                    "duration": round(max(0.0, shifted_end - shifted_start), 3),
                })

            self._alignment = new_alignment
            if new_alignment:
                self.word_panel.load_words(new_alignment)
                self.word_panel.setVisible(True)
                align_path = self.wav_dir / (stem + "_alignment.json")
                try:
                    with open(align_path, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "source_file": wav_path.name,
                                "transcript": d["transcription"],
                                "num_words": len(new_alignment),
                                "words": new_alignment,
                            },
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
                except OSError:
                    pass
            else:
                self.word_panel.setVisible(False)
                self._alignment = None
        d["dirty"] = True
        self._apply_editor_bg(True)
        self.save_btn.setEnabled(True)
        self._refresh_item(stem)

        # If no alignment existed for this clip, keep the panel hidden.
        if not self._alignment:
            self.word_panel.setVisible(False)

        # Reload player and waveform
        self.waveform.clear()
        self.waveform.load_wav(str(wav_path))
        self.player.setSource(QUrl.fromLocalFile(str(wav_path)))
        self._reset_trim_on_duration = True
        self.apply_crop_btn.setEnabled(False)
        self.cut_mode_btn.setChecked(False)

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
            self._save_csv()
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


def _slice_wav_regions(src_path: str, dst_path: str, regions_ms: list[tuple[int, int]]):
    """
    Read `src_path`, keep only the frames within `regions_ms` (list of (start_ms, end_ms)),
    concatenate them, and write the result to `dst_path`.  Writes to a temp file first so
    that src_path == dst_path is safe.
    """
    tmp_path = dst_path + ".~tmp"
    try:
        with _wave.open(src_path, "rb") as wf:
            params    = wf.getparams()
            framerate = wf.getframerate()
            n_frames  = wf.getnframes()
            frames    = b""
            for start_ms, end_ms in regions_ms:
                start_frame = max(0, int(start_ms / 1000 * framerate))
                end_frame   = min(n_frames, int(end_ms / 1000 * framerate))
                if end_frame <= start_frame:
                    continue
                wf.setpos(start_frame)
                frames += wf.readframes(end_frame - start_frame)

        with _wave.open(tmp_path, "wb") as out:
            out.setparams(params)
            out.writeframes(frames)

        os.replace(tmp_path, dst_path)

    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASR Review Tool")
    parser.add_argument(
        "--csv",
        type=Path,
        default=_DEFAULT_CSV,
        help="Path to the review CSV file (default: Dataset/transcriptions.csv)",
    )
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=_DEFAULT_WAV_DIR,
        help="Directory containing the WAV files (default: Dataset/WAV)",
    )
    parser.add_argument(
        "--title",
        default="ASR Review Tool",
        help="Window title (default: 'ASR Review Tool')",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    window = ReviewTool(csv_path=args.csv, wav_dir=args.audio_dir, title=args.title)
    window.show()
    sys.exit(app.exec())
