from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QFileDialog,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.marketplace.client import MarketplaceClient
from core.marketplace.reload_app import apply_to_app
from core.marketplace import submission


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
        self._developer_publisher = None
        self._developer_checked = False

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
            "Install and update tools without a new Z's Multi Tool release."
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
        submit = QPushButton("Submit a Module")
        submit.clicked.connect(self._submit_module)
        search_row.addWidget(refresh)
        search_row.addWidget(update_all)
        search_row.addWidget(submit)

        # Developer-only publishing is loaded dynamically. The public client
        # does not bundle the developer package, so this button is absent there.
        publisher = self._load_developer_publisher()
        if publisher is not None:
            publish = QPushButton("Publish")
            publish.setObjectName("Primary")
            publish.clicked.connect(self._publish_module)
            search_row.addWidget(publish)
        lay.addLayout(search_row)

        pills = QHBoxLayout()
        self._pills = {}
        for key, label in (
            ("all", "All"),
            ("installed", "Installed"),
            ("updates", "Updates"),
            ("new", "New"),
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
            f"Author: {row.get('author') or row.get('publisher')}  ·  Published by: {row.get('publisher')}"
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

    def _submit_module(self):
        author = submission.load_author()
        if author:
            answer = QMessageBox(self)
            answer.setWindowTitle("Module Author")
            answer.setText(f"Saved author name: {author}")
            answer.setInformativeText("Use this name for the submission, or edit it first.")
            edit = answer.addButton("Edit", QMessageBox.ButtonRole.ActionRole)
            use = answer.addButton("Use This Name", QMessageBox.ButtonRole.AcceptRole)
            answer.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            answer.exec()
            clicked = answer.clickedButton()
            if clicked is edit:
                author, ok = QInputDialog.getText(self, "Author Name", "Author name:", text=author)
                if not ok:
                    return
                try:
                    author = submission.save_author(author)
                except ValueError as exc:
                    QMessageBox.warning(self, "Submission", str(exc))
                    return
            elif clicked is not use:
                return
        else:
            author, ok = QInputDialog.getText(
                self,
                "Module Author",
                "Enter the name you want shown on the marketplace as the author:",
            )
            if not ok:
                return
            try:
                author = submission.save_author(author)
            except ValueError as exc:
                QMessageBox.warning(self, "Submission", str(exc))
                return

        folder = QFileDialog.getExistingDirectory(self, "Select Your Module Folder")
        if not folder:
            return
        name, ok = QInputDialog.getText(self, "Module Name", "Marketplace module name:", text=Path(folder).name)
        if not ok:
            return
        description, ok = QInputDialog.getMultiLineText(self, "Module Description", "Description:")
        if not ok:
            return
        category, ok = QInputDialog.getText(self, "Module Category", "Category:", text="Utilities")
        if not ok:
            return
        try:
            out = submission.create_submission(
                folder, name=name, author=author, description=description, category=category
            )
        except Exception as exc:
            QMessageBox.warning(self, "Submission", str(exc))
            return
        box = QMessageBox(self)
        box.setWindowTitle("Submission Created")
        box.setText("Your module submission is ready to send for review.")
        box.setInformativeText(str(out))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _load_developer_publisher(self):
        if self._developer_checked:
            return self._developer_publisher
        self._developer_checked = True
        try:
            import importlib
            self._developer_publisher = importlib.import_module("developer.publisher")
        except Exception:
            self._developer_publisher = None
            # DEBUG: --windowed builds have no console, so this exception was
            # previously discarded silently. Log it somewhere findable instead.
            try:
                import traceback
                from core.marketplace import dirs
                log_path = dirs.root() / "developer_import_error.log"
                log_path.write_text(traceback.format_exc(), encoding="utf-8")
            except Exception:
                pass
        return self._developer_publisher

    def _publish_module(self):
        publisher = self._load_developer_publisher()
        if publisher is None:
            QMessageBox.warning(
                self,
                "Developer Publisher",
                "The developer publisher is not available in this build.",
            )
            return

        try:
            tools = publisher.list_tools()
        except Exception as exc:
            QMessageBox.warning(self, "Developer Publisher", str(exc))
            return

        if not tools:
            QMessageBox.information(
                self,
                "Developer Publisher",
                "No modules were found in the app's modules folder.",
            )
            return

        labels = [
            f"{tool.get('meta', {}).get('name') or tool.get('id')} "
            f"({tool.get('id')})"
            for tool in tools
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Publish Module",
            "Module to publish:",
            labels,
            0,
            False,
        )
        if not ok:
            return

        selected = tools[labels.index(choice)]
        meta = dict(selected.get("meta") or {})
        default_author = meta.get("author") or meta.get("creator") or ""
        author, ok = QInputDialog.getText(
            self,
            "Module Author",
            "Author shown on the marketplace:",
            text=default_author,
        )
        if not ok:
            return
        author = author.strip()
        if not author:
            QMessageBox.warning(self, "Publish Module", "Author name cannot be empty.")
            return

        publisher_name, ok = QInputDialog.getText(
            self,
            "Publisher",
            "Publisher account/name:",
            text="official",
        )
        if not ok:
            return
        publisher_name = publisher_name.strip() or "official"

        meta["author"] = author
        selected["meta"] = meta

        try:
            result = publisher.publish_tool(selected, publisher=publisher_name)
        except Exception as exc:
            QMessageBox.critical(self, "Publish Module", str(exc))
            return

        manifest = result.get("manifest") or {}
        package_path = result.get("package") or ""
        build = manifest.get("build")
        label = manifest.get("label") or f"Build {build}"

        box = QMessageBox(self)
        box.setWindowTitle("Module Published")
        box.setText(f"{manifest.get('name') or selected.get('id')} published as {label}.")
        box.setInformativeText(
            "The local marketplace index and .zmod package were updated.\n\n"
            f"Package: {package_path}\n\n"
            "Use the publisher's marketplace export/push workflow to send the "
            "updated index and package to your GitHub marketplace."
        )
        box.exec()
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
