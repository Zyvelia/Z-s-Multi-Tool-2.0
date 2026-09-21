from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pages.catalog_theme import resolve_catalog_theme


class _FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        x, y = rect.x(), rect.y()
        line_h = 0
        space = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if next_x - space > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + space
                next_x = x + hint.width() + space
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class ToolCard(QFrame):
    open_clicked = Signal(str)
    hide_clicked = Signal(str)
    drag_finished = Signal(str, str)

    def __init__(self, tool, accent, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.tool = tool
        self.name = tool.get("name", "")
        self._accent = accent
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        # Keep cards in the same grid row visually consistent.  A
        # QGridLayout otherwise lets each card use its own natural height,
        # which makes short descriptions (such as Notes) look much shorter
        # than cards with long descriptions.
        self.setFixedHeight(220)
        self.setMinimumWidth(220)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        top = QHBoxLayout()
        grip = QLabel("::")
        grip.setObjectName("Muted")
        top.addWidget(grip)
        top.addStretch(1)
        hide = QPushButton("x")
        hide.setObjectName("HideBtn")
        hide.clicked.connect(lambda: self.hide_clicked.emit(self.name))
        top.addWidget(hide)
        root.addLayout(top)

        icon = tool.get("icon", "")
        title = QLabel(f"{icon}  {self.name}".strip())
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        root.addWidget(title)

        desc = QLabel(tool.get("desc", "No description"))
        desc.setObjectName("CardDesc")
        desc.setWordWrap(True)
        root.addWidget(desc)
        root.addStretch(1)

        cat = QLabel((tool.get("category") or "Other").upper())
        cat.setObjectName("CardCat")
        root.addWidget(cat)

        open_btn = QPushButton("Open")
        open_btn.setObjectName("OpenBtn")
        open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        open_btn.clicked.connect(lambda: self.open_clicked.emit(self.name))
        root.addWidget(open_btn)

        self._drag_start = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        if event.button() == Qt.MouseButton.LeftButton:
            w = QApplication.widgetAt(event.globalPosition().toPoint())
            card = w
            while card is not None and not isinstance(card, ToolCard):
                card = card.parent()
            if isinstance(card, ToolCard) and card.name != self.name:
                self.drag_finished.emit(self.name, card.name)
        super().mouseReleaseEvent(event)


class CatalogView(QWidget):
    def __init__(self, settings, plugin_manager, page_manager, parent=None):
        super().__init__(parent)
        self.setObjectName("CatalogRoot")
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.page_manager = page_manager
        self.category = "All"
        self._search = ""
        self._cards = {}
        self._pills = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 16)
        layout.setSpacing(10)

        self.subtitle = QLabel("Loading tools…")
        self.subtitle.setObjectName("Subtitle")
        layout.addWidget(self.subtitle)

        self._pill_host = QWidget()
        self._pill_layout = _FlowLayout(self._pill_host, spacing=8)
        self._pill_host.setLayout(self._pill_layout)
        layout.addWidget(self._pill_host)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 4, 8, 4)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(16)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._grid_host)
        layout.addWidget(self._scroll, 1)

        self._build_pills()
        self.render()

    def apply_theme(self, theme_id=None):
        self.render()

    def set_search(self, text):
        self._search = (text or "").strip().lower()
        self.render()

    def set_category(self, category):
        self.category = category
        for cat, btn in self._pills.items():
            btn.setChecked(cat == category)
        self.render()

    def on_show(self):
        self._build_pills()
        self.render()

    def _visible_tools(self):
        tools_by_name = {t.get("name"): t for t in self.plugin_manager.get_tools()}
        tools = [tools_by_name[n] for n in self._ordered_tool_names() if n in tools_by_name]
        hidden = set(self.settings.get("hidden_tools") or [])
        tools = [t for t in tools if t.get("name") not in hidden]
        total = len(tools)
        if self.category != "All":
            tools = [t for t in tools if t.get("category") == self.category]
        if self._search:
            tools = [
                t for t in tools
                if self._search in (t.get("name") or "").lower()
                or self._search in (t.get("desc") or "").lower()
            ]
        return tools, total

    def _ordered_tool_names(self):
        all_names = [t.get("name") for t in self.plugin_manager.get_tools()]
        known = set(all_names)
        saved = [n for n in (self.settings.get("tool_order") or []) if n in known]
        saved += [n for n in all_names if n not in saved]
        return saved

    def _build_pills(self):
        while self._pill_layout.count():
            item = self._pill_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._pills.clear()

        hidden = set(self.settings.get("hidden_tools") or [])
        visible = [t for t in self.plugin_manager.get_tools() if t.get("name") not in hidden]
        counts = {}
        for tool in visible:
            cat = tool.get("category", "Other")
            counts[cat] = counts.get(cat, 0) + 1
        ordered = ["All"] + sorted(set(counts) - {"All"})
        for cat in ordered:
            count = len(visible) if cat == "All" else counts.get(cat, 0)
            btn = QPushButton(f"{cat}  ·  {count}")
            btn.setObjectName("Pill")
            btn.setCheckable(True)
            btn.setChecked(cat == self.category)
            btn.clicked.connect(lambda _=False, c=cat: self.set_category(c))
            self._pill_layout.addWidget(btn)
            self._pills[cat] = btn

    def render(self):
        tools, total = self._visible_tools()
        self.subtitle.setText(
            f"{len(tools)} of {total} tool{'s' if total != 1 else ''} available"
        )

        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        if not tools:
            if self._search or self.category != "All":
                empty = QLabel("No tools match your search")
                empty.setObjectName("Muted")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._grid.addWidget(empty, 0, 0, 1, 3)
                return

            # The catalog is empty only when there are no installed tools.
            # Give a new/empty installation a direct path to the marketplace.
            empty_panel = QFrame()
            empty_panel.setObjectName("Panel")
            empty_layout = QVBoxLayout(empty_panel)
            empty_layout.setContentsMargins(28, 28, 28, 28)
            empty_layout.setSpacing(10)

            title = QLabel("No modules installed")
            title.setObjectName("CardTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(title)

            message = QLabel(
                "You don't have any modules installed yet. "
                "Open the Marketplace to browse and download modules."
            )
            message.setObjectName("Muted")
            message.setWordWrap(True)
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(message)

            download = QPushButton("Browse Marketplace")
            download.setObjectName("Primary")
            download.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            download.clicked.connect(
                lambda: self.page_manager.show_page("marketplace")
            )
            empty_layout.addWidget(download, alignment=Qt.AlignmentFlag.AlignCenter)

            self._grid.addWidget(empty_panel, 0, 0, 1, 3)
            return

        bundle = resolve_catalog_theme(self.settings.get("catalog_theme"))
        hues = list(bundle.t.ACCENT_HUES)
        cols = 3
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)
        for i, tool in enumerate(tools):
            name = tool.get("name", "")
            card = self._cards.get(name)
            if card is None:
                accent = hues[sum(ord(c) for c in name) % len(hues)]
                card = ToolCard(tool, accent)
                card.open_clicked.connect(self._open)
                card.hide_clicked.connect(self._hide)
                card.drag_finished.connect(self._reorder)
                self._cards[name] = card
            self._grid.addWidget(
                card, i // cols, i % cols,
                alignment=Qt.AlignmentFlag.AlignTop,
            )
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)
        self._grid.setRowStretch((len(tools) - 1) // cols + 1, 1)

    def _open(self, name):
        self.page_manager.show_page(name)

    def _hide(self, name):
        hidden = list(self.settings.get("hidden_tools") or [])
        if name not in hidden:
            hidden.append(name)
            self.settings.set("hidden_tools", hidden)
        self._build_pills()
        self.render()

    def _reorder(self, dragged, target):
        tools, _ = self._visible_tools()
        visible = [t.get("name") for t in tools]
        if dragged not in visible or target not in visible:
            return
        visible.remove(dragged)
        visible.insert(visible.index(target), dragged)
        full = self._ordered_tool_names()
        visible_set = set(visible)
        it = iter(visible)
        merged = [next(it) if n in visible_set else n for n in full]
        self.settings.set("tool_order", merged)
        self.render()
