"""Qt Folder Generator — search games, preview tree, generate folders."""

from __future__ import annotations

import importlib
import os
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core import paths

_db_mod = importlib.import_module("modules.Files.Folder Generator.game_database")
_tpl_mod = importlib.import_module("modules.Files.Folder Generator.template_loader")
_gen_mod = importlib.import_module("modules.Files.Folder Generator.generator")
_tree_mod = importlib.import_module("modules.Files.Folder Generator.tree_preview")
GameDatabase = _db_mod.GameDatabase
TemplateLoader = _tpl_mod.TemplateLoader
FolderStructureGenerator = _gen_mod.FolderStructureGenerator
render_tree = _tree_mod.render_tree


class FolderStructureGeneratorPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.database_path = paths.seed_from_resource(
            paths.data_path("folder_gen", "games.json"),
            "modules", "folder_gen", "games.json",
        )
        bundled = os.path.join(os.path.dirname(_db_mod.__file__), "games.json")
        if not os.path.isfile(self.database_path) and os.path.isfile(bundled):
            self.database_path = bundled
        self._default_stub_path = os.path.join(os.path.dirname(_db_mod.__file__), "assets", "mGba.exe")
        self._games = []
        self._visible = []
        self._selected = None
        self._generating = False

        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Folder Structure Generator")
        title.setObjectName("AccentTitle")
        self.header_status = QLabel("Loading database…")
        self.header_status.setObjectName("Muted")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.header_status)
        root.addLayout(header)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to filter games…")
        self.search.textChanged.connect(self._on_search)
        root.addWidget(self.search)

        game_row = QHBoxLayout()
        self.game_combo = QComboBox()
        self.game_combo.currentTextChanged.connect(self._on_game_selected)
        self.meta = QLabel("")
        self.meta.setObjectName("Muted")
        game_row.addWidget(self.game_combo, 1)
        game_row.addWidget(self.meta, 1)
        root.addLayout(game_row)

        out_panel = QFrame()
        out_panel.setObjectName("Panel")
        ol = QVBoxLayout(out_panel)
        cap = QLabel("Output folder")
        cap.setObjectName("Muted")
        ol.addWidget(cap)
        out_row = QHBoxLayout()
        self.output = QLineEdit()
        self.output.setPlaceholderText(r"e.g. D:\Launchers")
        self.output.textChanged.connect(self._update_preview)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.output, 1)
        out_row.addWidget(browse)
        ol.addLayout(out_row)
        stub_row = QHBoxLayout()
        self.stub = QLineEdit()
        if os.path.isfile(self._default_stub_path):
            self.stub.setText(self._default_stub_path)
        self.stub.setPlaceholderText("Stub exe (optional — copied and renamed)")
        stub_browse = QPushButton("Browse stub")
        stub_browse.clicked.connect(self._browse_stub)
        stub_row.addWidget(self.stub, 1)
        stub_row.addWidget(stub_browse)
        ol.addLayout(stub_row)
        opt_row = QHBoxLayout()
        self.create_file = QCheckBox("Create placeholder executable")
        self.create_file.setChecked(True)
        self.overwrite = QCheckBox("Overwrite if it already exists")
        opt_row.addWidget(self.create_file)
        opt_row.addWidget(self.overwrite)
        opt_row.addStretch(1)
        ol.addLayout(opt_row)
        root.addWidget(out_panel)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        prev_title = QLabel("Preview")
        prev_title.setObjectName("CardTitle")
        ll.addWidget(prev_title)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        ll.addWidget(self.preview, 1)
        self.create_btn = QPushButton("Create Folder Structure")
        self.create_btn.setObjectName("Primary")
        self.create_btn.clicked.connect(self._on_create)
        ll.addWidget(self.create_btn)

        right = QWidget()
        rl = QVBoxLayout(right)
        st_title = QLabel("Status")
        st_title.setObjectName("CardTitle")
        rl.addWidget(st_title)
        self.status_box = QPlainTextEdit()
        self.status_box.setReadOnly(True)
        rl.addWidget(self.status_box, 1)
        split.addWidget(left)
        split.addWidget(right)
        root.addWidget(split, 1)
        self._load_database()

    def _load_database(self):
        games, warnings = GameDatabase(self.database_path).load()
        self._games = games
        self._visible = games
        for warning in warnings:
            self._append_log(f"⚠ {warning}")
        templates_dir = os.path.join(os.path.dirname(_db_mod.__file__), "templates")
        _templates, terrors = TemplateLoader(templates_dir).load_all()
        for filename, err in terrors:
            self._append_log(f"⚠ {filename}: {err}")
        self._refresh_game_menu()
        self.header_status.setText(f"{len(games)} game(s) loaded" if games else "No games found")

    def _refresh_game_menu(self):
        names = [g.name for g in self._visible]
        current = self._selected.name if self._selected else ""
        self.game_combo.blockSignals(True)
        self.game_combo.clear()
        self.game_combo.addItems(names)
        self.game_combo.blockSignals(False)
        if not names:
            self._selected = None
            self.meta.setText("")
            self._update_preview()
            return
        target = current if current in names else names[0]
        self.game_combo.setCurrentText(target)
        self._on_game_selected(target)

    def _on_search(self, text: str):
        query = text.strip().lower()
        self._visible = [g for g in self._games if query in g.name.lower()] if query else list(self._games)
        self._refresh_game_menu()

    def _on_game_selected(self, name: str):
        self._selected = next((g for g in self._games if g.name == name), None)
        if not self._selected:
            self.meta.setText("")
        else:
            parts = [v for v in (self._selected.category, self._selected.developer, self._selected.publisher, self._selected.platform) if v]
            self.meta.setText("  •  ".join(parts))
        self._update_preview()

    def _update_preview(self):
        self.preview.setPlainText(render_tree(self._selected, self.output.text()))

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder")
        if folder:
            self.output.setText(folder)

    def _browse_stub(self):
        path, _ = QFileDialog.getOpenFileName(self, "Stub executable", filter="Executable (*.exe);;All files (*.*)")
        if path:
            self.stub.setText(path)

    def _on_create(self):
        if self._generating:
            return
        if not self._selected:
            self._append_log("✕ No game selected.")
            return
        output_root = self.output.text().strip()
        if not output_root:
            self._append_log("✕ Please choose an output folder first.")
            return
        if not os.path.isdir(output_root):
            self._append_log(f"✕ Output folder does not exist: {output_root}")
            return
        self.status_box.clear()
        self._generating = True
        self.create_btn.setEnabled(False)
        self.create_btn.setText("Working…")
        self._append_log(f"Creating '{self._selected.name}' in {output_root}")
        generator = FolderStructureGenerator(
            game=self._selected,
            output_root=output_root,
            create_placeholder_file=self.create_file.isChecked(),
            overwrite_file=self.overwrite.isChecked(),
            stub_exe_path=self.stub.text().strip() or None,
        )

        def work():
            logs = []

            def progress(message: str):
                logs.append(message)

            try:
                result = generator.generate(progress_callback=progress)
                QTimer.singleShot(0, lambda: self._on_done(logs, result, None))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._on_done(logs, None, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, logs, result, fatal):
        for message in logs:
            self._append_log(message)
        self._generating = False
        self.create_btn.setEnabled(True)
        self.create_btn.setText("Create Folder Structure")
        if fatal:
            self._append_log(f"✕ Unexpected error: {fatal}")
            return
        self._append_log(f"✓ Created {result.folders_created} folder(s)")
        if result.file_created and result.used_stub:
            self._append_log("✓ Copied and renamed stub executable")
        elif result.file_created:
            self._append_log("✓ Created empty placeholder executable file")
        if result.file_skipped:
            self._append_log("⚠ Skipped existing executable file")
        for error in result.errors:
            self._append_log(f"✕ {error}")
        self._append_log("✓ Finished" if result.success else "✕ Finished with errors")

    def _append_log(self, message: str):
        self.status_box.appendPlainText(message)
