from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.marketplace.client import MarketplaceClient
from core.marketplace.reload_app import apply_to_app


class _Job(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.finished_ok.emit(self._fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class MarketplaceView(QWidget):
    def __init__(self, settings, plugin_manager, page_manager, parent=None):
        super().__init__(parent)
        self.setObjectName("MarketplaceRoot")
        self.settings = settings
        self.plugin_manager = plugin_manager
        self.page_manager = page_manager
        self.client = MarketplaceClient(settings)
        self._filter = "all"
        self._query = ""
        self._rows = []
        self._job = None
        self._busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(20, 16, 20, 20)
        self._body.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        self._build_header()
        self._build_toolbar()
        self._cards_host = QWidget()
        self._cards = QVBoxLayout(self._cards_host)
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(10)
        self._body.addWidget(self._cards_host)
        self._body.addStretch(1)

    def on_show(self):
        if not self._busy:
            self.refresh()

    def _panel(self):
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(8)
        return frame, lay

    def _build_header(self):
        header, lay = self._panel()
        row = QHBoxLayout()
        title = QLabel("Marketplace")
        title.setObjectName("AccentTitle")
        row.addWidget(title)
        row.addStretch(1)
        back = QPushButton("Back")
        back.clicked.connect(lambda: self.page_manager.show_page("catalog"))
        row.addWidget(back)
        lay.addLayout(row)
        hint = QLabel(
            "Install and update tools without a new Z's Multi Tool release. "
            "Publish assigns the next build number automatically — you never pick 1.2.0."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)
        self._body.addWidget(header)

    def _build_toolbar(self):
        bar, lay = self._panel()
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search modules…")
        self.search.textChanged.connect(self._on_search)
        search_row.addWidget(self.search, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        update_all = QPushButton("Update all")
        update_all.setObjectName("Primary")
        update_all.clicked.connect(self._update_all)
        search_row.addWidget(refresh)
        search_row.addWidget(update_all)
        lay.addLayout(search_row)

        pills = QHBoxLayout()
        self._pills = {}
        for key, label in (
            ("all", "All"),
            ("installed", "Installed"),
            ("updates", "Updates"),
            ("new", "New"),
            ("publish", "Publish"),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            pills.addWidget(btn)
            self._pills[key] = btn
        pills.addStretch(1)
        lay.addLayout(pills)
        self._body.addWidget(bar)

    def _set_filter(self, key):
        self._filter = key
        for name, btn in self._pills.items():
            btn.setChecked(name == key)
        self._render()

    def _on_search(self, text):
        self._query = (text or "").strip().lower()
        self._render()

    def refresh(self):
        try:
            self._rows = self.client.rows(self.plugin_manager.get_tools())
        except Exception as exc:
            self._rows = []
            self._status.setText(str(exc))
            return
        extra = self.client.last_error
        updates = sum(1 for r in self._rows if r.get("status") == "update")
        new = sum(1 for r in self._rows if r.get("status") == "new")
        parts = [f"{len(self._rows)} modules in the catalog"]
        if updates:
            parts.append(f"{updates} update{'s' if updates != 1 else ''} available")
        if new:
            parts.append(f"{new} new")
        if extra:
            parts.append(extra)
        self._status.setText(" · ".join(parts))
        self._render()

    def _visible_rows(self):
        rows = []
        for row in self._rows:
            if self._filter == "installed" and row["origin"] == "none":
                continue
            if self._filter == "updates" and not row.get("can_update"):
                continue
            if self._filter == "new" and row.get("status") != "new":
                continue
            if self._filter == "publish" and not row.get("can_publish"):
                continue
            if self._query:
                blob = " ".join((
                    row.get("name") or "",
                    row.get("desc") or "",
                    row.get("category") or "",
                    row.get("id") or "",
                )).lower()
                if self._query not in blob:
                    continue
            rows.append(row)
        return rows

    def _clear_cards(self):
        while self._cards.count():
            item = self._cards.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render(self):
        self._clear_cards()
        rows = self._visible_rows()
        if not rows:
            empty = QLabel("No modules match this filter.")
            empty.setObjectName("Muted")
            self._cards.addWidget(empty)
            return
        for row in rows:
            self._cards.addWidget(self._card(row))

    def _card(self, row: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel(f"{row.get('icon') or ''}  {row.get('name')}".strip())
        title.setObjectName("CardTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        badge = QLabel(self._badge(row))
        badge.setObjectName(self._badge_object(row))
        top.addWidget(badge)
        lay.addLayout(top)

        desc = QLabel(row.get("desc") or "No description")
        desc.setObjectName("CardDesc")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        meta = QLabel(
            f"{(row.get('category') or 'Other').upper()}  ·  "
            f"{row.get('latest_label')}  ·  "
            f"Installed: {row.get('installed_label')}  ·  "
            f"{row.get('publisher')}"
        )
        meta.setObjectName("Muted")
        meta.setWordWrap(True)
        lay.addWidget(meta)

        actions = QHBoxLayout()
        if row.get("can_install"):
            actions.addWidget(self._action("Install", lambda r=row: self._run_install(r), primary=True))
        if row.get("can_update"):
            actions.addWidget(self._action("Update", lambda r=row: self._run_install(r), primary=True))
        if row.get("can_uninstall"):
            actions.addWidget(self._action("Uninstall", lambda r=row: self._run_uninstall(r), danger=True))
        if row.get("can_rollback"):
            actions.addWidget(self._action("Roll back", lambda r=row: self._run_rollback(r)))
        if row.get("can_publish"):
            actions.addWidget(self._action("Publish next build", lambda r=row: self._run_publish(r)))
        if row.get("included") and not row.get("can_update") and not row.get("can_install"):
            note = QLabel("Included with the app")
            note.setObjectName("Muted")
            actions.addWidget(note)
        actions.addStretch(1)
        lay.addLayout(actions)
        return card

    def _badge(self, row):
        return {
            "update": "Update available",
            "new": "New",
            "installed": "Installed",
            "included": "Included",
        }.get(row.get("status"), row.get("status") or "")

    def _badge_object(self, row):
        if row.get("status") == "update":
            return "Warn"
        if row.get("status") == "new":
            return "Success"
        return "Muted"

    def _action(self, text, cb, primary=False, danger=False):
        btn = QPushButton(text)
        if primary:
            btn.setObjectName("Primary")
        if danger:
            btn.setObjectName("Danger")
        btn.clicked.connect(lambda _checked=False, fn=cb: fn())
        return btn

    def _set_busy(self, message: str):
        self._busy = True
        self._status.setText(message)
        self.setEnabled(False)

    def _clear_busy(self):
        self._busy = False
        self.setEnabled(True)
        self._job = None

    def _start(self, message: str, fn, on_ok):
        if self._job is not None and self._job.isRunning():
            return
        self._set_busy(message)
        job = _Job(fn)
        self._job = job

        def ok(result):
            self._clear_busy()
            on_ok(result)

        def fail(err):
            self._clear_busy()
            QMessageBox.warning(self, "Marketplace", err)
            self.refresh()

        job.finished_ok.connect(ok)
        job.failed.connect(fail)
        job.start()

    def _run_install(self, row):
        self._start(
            f"Installing {row['name']}…",
            lambda: self.client.install(row["id"]),
            lambda rec: self._done(f"{row['name']} is now on {rec.get('label')}.", rec, [row["name"]]),
        )

    def _run_uninstall(self, row):
        from core.marketplace.discover import list_bundled_tools

        box = QMessageBox(self)
        box.setWindowTitle("Uninstall module")
        if any(t["id"] == row["id"] for t in list_bundled_tools()):
            box.setText(
                f"Remove the marketplace copy of {row['name']}? "
                "The version included with Z's Multi Tool will stay available."
            )
        else:
            box.setText(f"Uninstall {row['name']}? It will disappear from the catalog.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self._start(
            f"Uninstalling {row['name']}…",
            lambda: self.client.uninstall(row["id"]),
            lambda rec: self._done(f"{row['name']} removed.", rec, [row["name"]]),
        )

    def _run_rollback(self, row):
        builds = [b for b in self.client.history_builds(row["id"]) if b < (row.get("installed_build") or 0)]
        if not builds:
            QMessageBox.information(self, "Marketplace", "No previous build is saved.")
            return
        pick = QMessageBox(self)
        pick.setWindowTitle("Roll back")
        pick.setText(f"Restore the last saved build of {row['name']} (Build {builds[-1]})?")
        pick.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if pick.exec() != QMessageBox.StandardButton.Yes:
            return
        self._start(
            f"Rolling back {row['name']}…",
            lambda: self.client.rollback(row["id"], builds[-1]),
            lambda rec: self._done(f"{row['name']} restored to {rec.get('label')}.", rec, [row["name"]]),
        )

    def _run_publish(self, row):
        self._start(
            f"Publishing next build of {row['name']}…",
            lambda: self.client.publish(row["id"]),
            lambda result: self._published(row, result),
        )

    def _published(self, row, result):
        manifest = (result or {}).get("manifest") or {}
        QMessageBox.information(
            self,
            "Published",
            f"{row['name']} is now {manifest.get('label') or 'a new build'}.\n"
            "Users will see Update available without a new Z's Multi Tool release.",
        )
        self.refresh()

    def _update_all(self):
        pending = [r for r in self._rows if r.get("can_update")]
        if not pending:
            QMessageBox.information(self, "Marketplace", "Every module is already current.")
            return
        names = [r["name"] for r in pending]
        self._start(
            f"Updating {len(pending)} module{'s' if len(pending) != 1 else ''}…",
            lambda: self.client.update_all(self.plugin_manager.get_tools()),
            lambda recs: self._done(
                f"Updated {len(recs)} module{'s' if len(recs) != 1 else ''}.",
                recs[-1] if recs else None,
                names,
            ),
        )

    def _done(self, message, rec, names):
        apply_to_app(
            self.page_manager,
            changed_relpaths=[rec.get("relpath")] if rec and rec.get("relpath") else [],
            changed_names=names,
        )
        self.refresh()
        self._status.setText(message)
