"""Qt Secure Vault — lock screen + password / authenticator dashboard."""

from __future__ import annotations

import importlib
import importlib.util
import threading
import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.qt.module_shell import find_qt_module_shell
from core.qt.remote_common import VaultRemoteSettings
from core.services.auth_service import AuthService
from core.services.totp_service import generate_code

_emergency = importlib.import_module("modules.Security.Secure Vault.emergency_kit")
export_emergency_kit = _emergency.export_emergency_kit

_hibp_path = Path(__file__).resolve().parents[3] / "modules" / "Security" / "Breach Checker" / "hibp_api.py"
_spec = importlib.util.spec_from_file_location("vault_hibp_api", _hibp_path)
_hibp = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_hibp)
check_password = _hibp.check_password
HIBPError = _hibp.HIBPError

PasswordGenerator = importlib.import_module(
    "modules.Security.Secure Vault.generator"
).PasswordGenerator

MIN_PASSWORD_LENGTH = 8
STRENGTH_COLORS = ["#b33939", "#e0803f", "#e0c53f", "#8bd15a", "#2ecc71"]
DEFAULT_CATEGORIES = ["General", "Email", "Gaming", "Work", "Banking", "Social", "Alt Accounts"]


class VaultLockScreen(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.auth = manager.container.auth_service
        self.alert = manager.container.alert_service
        self.hw = manager.container.hardware_key_service
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(440)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 28, 32, 28)
        eyebrow = QLabel("END-TO-END ENCRYPTED")
        eyebrow.setObjectName("CardCat")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Security Vault")
        title.setObjectName("AccentTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        first = not self.auth.is_initialized()
        hint = QLabel(
            "Choose a master password to protect your vault."
            if first else
            "Enter your master password to continue."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(eyebrow)
        cl.addWidget(title)
        cl.addWidget(hint)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Master password")
        self.password.returnPressed.connect(self._submit)
        cl.addWidget(self.password)

        self.strength = QProgressBar()
        self.strength.setRange(0, 4)
        self.strength.setValue(0)
        self.strength_label = QLabel(" ")
        self.strength_label.setObjectName("Muted")
        if first:
            self.password.textChanged.connect(self._update_strength)
            cl.addWidget(self.strength)
            cl.addWidget(self.strength_label)
            self.confirm = QLineEdit()
            self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm.setPlaceholderText("Confirm password")
            self.confirm.returnPressed.connect(self._submit)
            cl.addWidget(self.confirm)
            note = QLabel(
                f"Minimum {MIN_PASSWORD_LENGTH} characters. This password can't be recovered if you forget it."
            )
            note.setObjectName("Muted")
            note.setWordWrap(True)
            cl.addWidget(note)
            create = QPushButton("Create Vault")
            create.setObjectName("Primary")
            create.clicked.connect(self.create_master)
            cl.addWidget(create)
        else:
            self.confirm = None
            unlock = QPushButton("Unlock Vault")
            unlock.setObjectName("Primary")
            unlock.clicked.connect(self.unlock)
            cl.addWidget(unlock)
            self.hw_btn = QPushButton("Unlock with security key")
            self.hw_btn.clicked.connect(self.unlock_hw)
            self.hw_btn.setEnabled(self.hw.is_enabled())
            cl.addWidget(self.hw_btn)

        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.error)
        foot = QLabel(f"PBKDF2-HMAC-SHA256 · {self.auth.PBKDF2_ITERATIONS:,} rounds")
        foot.setObjectName("Muted")
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(foot)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.password.setFocus()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        return _VaultSettings(parent, manager)

    def _update_strength(self, text):
        score, label = AuthService.password_strength(text)
        self.strength.setValue(score)
        self.strength_label.setText(label if text else " ")

    def _submit(self):
        if self.auth.is_initialized():
            self.unlock()
        else:
            self.create_master()

    def create_master(self):
        self.error.setText("")
        password = self.password.text()
        confirm = self.confirm.text() if self.confirm is not None else ""
        if len(password) < MIN_PASSWORD_LENGTH:
            self.error.setText(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
            return
        if password != confirm:
            self.error.setText("Passwords do not match.")
            return
        try:
            self.auth.create_master_password(password)
        except Exception as e:
            self.error.setText(f"Couldn't create vault: {e}")
            return
        self.open_vault()

    def unlock(self):
        if self.auth.verify_master_password(self.password.text()):
            self.alert.local_unlock_attempt(True)
            self.open_vault()
        else:
            self.alert.local_unlock_attempt(False)
            self.error.setText("Incorrect password.")
            self.password.clear()
            self.password.setFocus()

    def unlock_hw(self):
        self.error.setText("")
        try:
            if self.hw.verify_and_unlock():
                self.alert.local_unlock_attempt(True)
                self.open_vault()
            else:
                self.alert.local_unlock_attempt(False)
                self.error.setText("Security key verification failed.")
        except Exception as exc:
            self.alert.local_unlock_attempt(False)
            self.error.setText(str(exc))

    def open_vault(self):
        shell = find_qt_module_shell(self)
        if shell is not None:
            shell.open_vault_dashboard(VaultDashboard)


class VaultDashboard(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.vault = manager.container.vault_service
        self.totp = manager.container.totp_service
        self.auth = manager.container.auth_service
        self.show_favorites = False
        self._overlay = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 12)
        header = QHBoxLayout()
        title = QLabel("Security Vault")
        title.setObjectName("AccentTitle")
        header.addWidget(title)
        header.addStretch(1)
        fav = QPushButton("Favorites")
        fav.setCheckable(True)
        fav.toggled.connect(self._toggle_fav)
        add = QPushButton("Add entry")
        add.setObjectName("Primary")
        add.clicked.connect(lambda: self._edit_entry(None))
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export)
        import_btn = QPushButton("Import")
        import_btn.clicked.connect(self._import)
        kit = QPushButton("Emergency kit")
        kit.clicked.connect(self._export_kit)
        header.addWidget(fav)
        header.addWidget(add)
        header.addWidget(export_btn)
        header.addWidget(import_btn)
        header.addWidget(kit)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.pass_host = QWidget()
        self.pass_lay = QVBoxLayout(self.pass_host)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.textChanged.connect(self.render)
        self.cat = QComboBox()
        self.cat.addItem("All")
        self.cat.currentTextChanged.connect(self.render)
        filt = QHBoxLayout()
        filt.addWidget(self.search, 1)
        filt.addWidget(self.cat)
        self.pass_lay.addLayout(filt)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        scroll.setWidget(self.list_host)
        self.pass_lay.addWidget(scroll, 1)
        self.tabs.addTab(self.pass_host, "Passwords")

        self.auth_host = QWidget()
        al = QVBoxLayout(self.auth_host)
        add_t = QPushButton("Add authenticator")
        add_t.clicked.connect(self._add_totp)
        al.addWidget(add_t, alignment=Qt.AlignmentFlag.AlignLeft)
        self.totp_list = QVBoxLayout()
        al.addLayout(self.totp_list)
        al.addStretch(1)
        self.tabs.addTab(self.auth_host, "Authenticator")

        self.audit_host = QWidget()
        audit_lay = QVBoxLayout(self.audit_host)
        score_row = QHBoxLayout()
        self.audit_score = QLabel("Score: —")
        self.audit_score.setObjectName("AccentTitle")
        self.audit_summary = QLabel("")
        self.audit_summary.setObjectName("Muted")
        self.audit_summary.setWordWrap(True)
        scan = QPushButton("Scan breaches")
        scan.clicked.connect(self._start_breach_scan)
        refresh_audit = QPushButton("Refresh")
        refresh_audit.clicked.connect(self._render_audit)
        score_row.addWidget(self.audit_score)
        score_row.addWidget(self.audit_summary, 1)
        score_row.addWidget(scan)
        score_row.addWidget(refresh_audit)
        audit_lay.addLayout(score_row)
        self.audit_status = QLabel("")
        self.audit_status.setObjectName("Muted")
        audit_lay.addWidget(self.audit_status)
        audit_scroll = QScrollArea()
        audit_scroll.setWidgetResizable(True)
        self.audit_list = QWidget()
        self.audit_list_lay = QVBoxLayout(self.audit_list)
        audit_scroll.setWidget(self.audit_list)
        audit_lay.addWidget(audit_scroll, 1)
        self.tabs.addTab(self.audit_host, "Audit")
        self._breach_cache = {}
        self._scanning = False
        root.addWidget(self.tabs, 1)

        self._lock_timer = QTimer(self)
        self._lock_timer.setInterval(15000)
        self._lock_timer.timeout.connect(self._auto_lock)
        self._lock_timer.start()
        self._totp_timer = QTimer(self)
        self._totp_timer.setInterval(1000)
        self._totp_timer.timeout.connect(self._tick_totp)
        self._totp_timer.start()
        self.render()

    @staticmethod
    def build_qt_module_settings(parent, manager):
        return _VaultSettings(parent, manager)

    def on_show(self):
        if self.auth.is_locked():
            self._show_overlay()
        else:
            self._hide_overlay()
            self.render()

    def on_hide(self):
        self._lock_timer.stop()
        self._totp_timer.stop()

    def _toggle_fav(self, on):
        self.show_favorites = bool(on)
        self.render()

    def _vault_foreground(self):
        current = getattr(self.manager, "current", None)
        return current is self or getattr(current, "_inner", None) is self

    def _auto_lock(self):
        if self._vault_foreground() and self._overlay is None and self.auth.is_locked():
            self._show_overlay()

    def _show_overlay(self):
        if self._overlay is not None:
            return
        self._overlay = QFrame(self)
        self._overlay.setObjectName("Card")
        self._overlay.setGeometry(self.rect())
        lay = QVBoxLayout(self._overlay)
        lay.addStretch(1)
        box = QVBoxLayout()
        lab = QLabel("Vault locked")
        lab.setObjectName("AccentTitle")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay_pw = QLineEdit()
        self._overlay_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self._overlay_pw.setPlaceholderText("Master password")
        self._overlay_pw.returnPressed.connect(self._overlay_unlock)
        btn = QPushButton("Unlock")
        btn.setObjectName("Primary")
        btn.clicked.connect(self._overlay_unlock)
        box.addWidget(lab)
        box.addWidget(self._overlay_pw)
        box.addWidget(btn)
        wrap = QWidget()
        wrap.setMaximumWidth(360)
        wrap.setLayout(box)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(wrap)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self._overlay.show()
        self._overlay.raise_()

    def _hide_overlay(self):
        if self._overlay is not None:
            self._overlay.deleteLater()
            self._overlay = None

    def _overlay_unlock(self):
        if self.auth.verify_master_password(self._overlay_pw.text()):
            self._hide_overlay()
            self.render()
        else:
            self._overlay_pw.clear()

    def render(self):
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        cats = set(DEFAULT_CATEGORIES)
        entries = self.vault.get_entries()
        for e in entries:
            cats.add(e.get("category") or "General")
        current = self.cat.currentText()
        self.cat.blockSignals(True)
        self.cat.clear()
        self.cat.addItem("All")
        for c in sorted(cats):
            self.cat.addItem(c)
        idx = self.cat.findText(current)
        self.cat.setCurrentIndex(idx if idx >= 0 else 0)
        self.cat.blockSignals(False)

        q = (self.search.text() or "").lower()
        cat = self.cat.currentText()
        shown = 0
        for e in entries:
            if self.show_favorites and not e.get("favorite"):
                continue
            if cat != "All" and (e.get("category") or "General") != cat:
                continue
            blob = f"{e.get('site','')} {e.get('username','')} {e.get('url','')}".lower()
            if q and q not in blob:
                continue
            self.list_lay.addWidget(self._card(e))
            shown += 1
        if not shown:
            empty = QLabel("No entries yet.")
            empty.setObjectName("Muted")
            self.list_lay.addWidget(empty)
        self.list_lay.addStretch(1)
        self._render_totp()
        self._render_audit()

    def _card(self, entry):
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        top = QHBoxLayout()
        site = QLabel(entry.get("site") or "Untitled")
        site.setObjectName("CardTitle")
        cat = QLabel(entry.get("category") or "General")
        cat.setObjectName("CardCat")
        top.addWidget(site, 1)
        top.addWidget(cat)
        lay.addLayout(top)
        user = QLabel(entry.get("username") or "")
        user.setObjectName("Muted")
        lay.addWidget(user)
        pw = QLineEdit(entry.get("password") or "")
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        pw.setReadOnly(True)
        row = QHBoxLayout()
        row.addWidget(pw, 1)
        star = QPushButton("★" if entry.get("favorite") else "☆")
        star.setFixedWidth(36)
        star.clicked.connect(lambda e=entry: self._toggle_favorite(e))
        row.addWidget(star)
        show = QPushButton("Show")
        show.clicked.connect(lambda: pw.setEchoMode(
            QLineEdit.EchoMode.Normal if pw.echoMode() == QLineEdit.EchoMode.Password
            else QLineEdit.EchoMode.Password
        ))
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda: self._copy(entry.get("password") or ""))
        edit = QPushButton("Edit")
        edit.clicked.connect(lambda e=entry: self._edit_entry(e))
        delete = QPushButton("Delete")
        delete.setObjectName("Danger")
        delete.clicked.connect(lambda e=entry: self._delete(e))
        row.addWidget(show)
        row.addWidget(copy)
        row.addWidget(edit)
        row.addWidget(delete)
        lay.addLayout(row)
        url = entry.get("url") or ""
        if url:
            open_url = QPushButton("Open URL")
            open_url.clicked.connect(lambda u=url: webbrowser.open(u))
            lay.addWidget(open_url, alignment=Qt.AlignmentFlag.AlignLeft)
        return frame

    def _toggle_favorite(self, entry):
        self.vault.toggle_favorite(entry["id"])
        self.render()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export vault", "vault_backup.enc",
            "Encrypted vault (*.enc);;JSON (*.json)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".json"):
                self.vault.export_json(path)
            else:
                self.vault.export_encrypted(path)
            QMessageBox.information(self, "Export", f"Saved to {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import vault", "",
            "Vault backup (*.enc *.json);;Encrypted vault (*.enc);;JSON (*.json)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".enc"):
                self.vault.import_encrypted(path)
            else:
                self.vault.import_json(path)
            self.render()
            QMessageBox.information(self, "Import", "Imported.")
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))

    def _export_kit(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose folder for Emergency Kit")
        if not folder:
            return
        try:
            export_emergency_kit(folder, self.vault, self.totp)
            QMessageBox.information(
                self, "Emergency Kit",
                f"Saved to:\n{folder}\n\nKeep README.txt and the .enc files offline and safe.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _render_audit(self):
        self._clear_layout(self.audit_list_lay)
        audit = self.vault.audit_summary()
        score = audit["score"]
        self.audit_score.setText(f"Score: {score}/100")
        breached = sum(1 for c in self._breach_cache.values() if c > 0)
        extra = f" · {breached} found in breaches" if self._breach_cache else ""
        self.audit_summary.setText(
            f"{audit['total']} passwords · {audit['weak_count']} weak · "
            f"{audit['reused_count']} reused{extra}"
        )
        issues = []
        entries = {e["id"]: e for e in self.vault.get_entries()}
        tagged = {}
        for eid in audit["weak_ids"]:
            entry = entries.get(eid)
            if entry:
                tagged[eid] = (entry, ["Weak password"])
        for eid in audit["reused_ids"]:
            entry = entries.get(eid)
            if not entry:
                continue
            if eid in tagged:
                tagged[eid][1].append("Password reused elsewhere")
            else:
                tagged[eid] = (entry, ["Password reused elsewhere"])
        for eid, count in self._breach_cache.items():
            if count <= 0:
                continue
            entry = entries.get(eid)
            if not entry:
                continue
            tag = f"In {count:,} breaches"
            if eid in tagged:
                tagged[eid][1].append(tag)
            else:
                tagged[eid] = (entry, [tag])
        issues = list(tagged.values())
        if not issues:
            empty = QLabel("No issues found — your vault looks healthy.")
            empty.setObjectName("Muted")
            self.audit_list_lay.addWidget(empty)
        for entry, tags in issues:
            row = QFrame()
            row.setObjectName("Card")
            rl = QHBoxLayout(row)
            left = QVBoxLayout()
            site = QLabel(entry.get("site") or "Untitled")
            site.setObjectName("CardTitle")
            user = QLabel(entry.get("username") or "—")
            user.setObjectName("Muted")
            tag_lab = QLabel(" · ".join(tags))
            tag_lab.setObjectName("Error")
            left.addWidget(site)
            left.addWidget(user)
            left.addWidget(tag_lab)
            fix = QPushButton("Fix")
            fix.setObjectName("Primary")
            fix.clicked.connect(lambda _=False, e=entry: self._edit_entry(e))
            rl.addLayout(left, 1)
            rl.addWidget(fix)
            self.audit_list_lay.addWidget(row)
        self.audit_list_lay.addStretch(1)

    def _start_breach_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self.audit_status.setText("Scanning passwords against Have I Been Pwned…")

        def worker():
            entries = self.vault.get_entries()
            total = len(entries)
            for i, entry in enumerate(entries):
                try:
                    self._breach_cache[entry["id"]] = check_password(entry["password"])
                except HIBPError as exc:
                    QTimer.singleShot(0, lambda msg=str(exc): self.audit_status.setText(msg))
                    break
                except Exception:
                    self._breach_cache[entry["id"]] = 0
                if i < total - 1:
                    time.sleep(0.25)
                QTimer.singleShot(0, lambda n=i + 1, t=total: self.audit_status.setText(f"Scanning… {n}/{t}"))
            QTimer.singleShot(0, self._scan_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _scan_finished(self):
        self._scanning = False
        breached = sum(1 for c in self._breach_cache.values() if c > 0)
        self.audit_status.setText(f"Scan complete — {breached} password(s) found in known breaches.")
        self._render_audit()

    def _copy(self, text):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.auth.touch()

    def _delete(self, entry):
        if QMessageBox.question(self, "Delete", f"Delete {entry.get('site')}?") != QMessageBox.StandardButton.Yes:
            return
        self.vault.delete_entry(entry["id"])
        self.render()

    def _edit_entry(self, entry):
        dlg = QDialog(self)
        dlg.setWindowTitle("Vault entry")
        form = QFormLayout(dlg)
        site = QLineEdit((entry or {}).get("site") or "")
        user = QLineEdit((entry or {}).get("username") or "")
        pw = QLineEdit((entry or {}).get("password") or "")
        url = QLineEdit((entry or {}).get("url") or "")
        notes = QLineEdit((entry or {}).get("notes") or "")
        cat = QComboBox()
        cat.setEditable(True)
        cat.addItems(DEFAULT_CATEGORIES)
        cat.setCurrentText((entry or {}).get("category") or "General")
        gen = QPushButton("Generate")
        gen.clicked.connect(lambda: pw.setText(PasswordGenerator.generate()))
        pw_row = QHBoxLayout()
        pw_row.addWidget(pw, 1)
        pw_row.addWidget(gen)
        form.addRow("Site", site)
        form.addRow("Username", user)
        form.addRow("Password", pw_row)
        form.addRow("Category", cat)
        form.addRow("URL", url)
        form.addRow("Notes", notes)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        args = dict(
            site=site.text(), username=user.text(), password=pw.text(),
            category=cat.currentText(), url=url.text(), notes=notes.text(),
        )
        if entry:
            self.vault.update_entry(entry["id"], **args)
        else:
            self.vault.add_entry(**args)
        self.auth.touch()
        self.render()

    def _add_totp(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add authenticator")
        form = QFormLayout(dlg)
        name = QLineEdit()
        secret = QLineEdit()
        issuer = QLineEdit()
        form.addRow("Name", name)
        form.addRow("Secret", secret)
        form.addRow("Issuer", issuer)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.totp.add_entry(name.text(), secret.text(), issuer.text())
        except Exception as e:
            QMessageBox.warning(self, "Authenticator", str(e))
        self._render_totp()

    def _render_totp(self):
        while self.totp_list.count():
            item = self.totp_list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for e in self.totp.get_entries():
            row = QFrame()
            row.setObjectName("Panel")
            rl = QHBoxLayout(row)
            left = QVBoxLayout()
            title = QLabel(e.get("name") or "Account")
            title.setObjectName("CardTitle")
            issuer = QLabel(e.get("issuer") or "")
            issuer.setObjectName("Muted")
            left.addWidget(title)
            left.addWidget(issuer)
            code = QLabel("")
            code.setObjectName("AccentTitle")
            code.setProperty("secret", e.get("secret") or "")
            delete = QPushButton("Delete")
            delete.setObjectName("Danger")
            delete.clicked.connect(lambda _=False, i=e.get("id"): self._del_totp(i))
            rl.addLayout(left, 1)
            rl.addWidget(code)
            rl.addWidget(delete)
            self.totp_list.addWidget(row)
        self._tick_totp()

    def _del_totp(self, entry_id):
        self.totp.delete_entry(entry_id)
        self._render_totp()

    def _tick_totp(self):
        for i in range(self.totp_list.count()):
            w = self.totp_list.itemAt(i).widget()
            if w is None:
                continue
            for lab in w.findChildren(QLabel):
                secret = lab.property("secret")
                if secret:
                    try:
                        lab.setText(generate_code(secret))
                    except Exception:
                        lab.setText("------")


class _VaultSettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        tabs = QTabWidget()
        tabs.addTab(VaultRemoteSettings(tabs, manager), "Remote access")
        tabs.addTab(_HardwareKeySettings(tabs, manager), "Security key")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(tabs)


class _HardwareKeySettings(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.auth = manager.container.auth_service
        self.hw = manager.container.hardware_key_service
        lay = QVBoxLayout(self)
        title = QLabel("Security key (optional)")
        title.setObjectName("CardTitle")
        hint = QLabel(
            "Use a FIDO2 USB key (YubiKey, etc.) to unlock the vault instead of typing your master password."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        row = QHBoxLayout()
        register = QPushButton("Register security key")
        register.setObjectName("Primary")
        register.clicked.connect(self._register)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(register)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        lay.addWidget(title)
        lay.addWidget(hint)
        lay.addWidget(self.status)
        lay.addLayout(row)
        lay.addStretch(1)
        self._refresh()

    def _refresh(self):
        self.status.setText(self.hw.status_message())
        self.remove_btn.setEnabled(self.hw.is_enabled())

    def _confirm_master(self):
        if not self.auth.is_initialized():
            QMessageBox.warning(self, "Secure Vault", "Create a master password first.")
            return False
        pwd, ok = QInputDialog.getText(
            self, "Confirm master password",
            "Enter your master password to change security key settings:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return False
        if not self.auth.verify_master_password(pwd):
            QMessageBox.warning(self, "Secure Vault", "Incorrect master password.")
            return False
        return True

    def _register(self):
        if not self._confirm_master():
            return
        try:
            self.hw.register_key()
            QMessageBox.information(
                self, "Security key registered",
                "Your key is registered. Use “Unlock with security key” on the vault lock screen.",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Registration failed", str(exc))
        self._refresh()

    def _remove(self):
        if not self._confirm_master():
            return
        if QMessageBox.question(
            self, "Remove security key",
            "Remove registered key unlock? You will need your master password to unlock.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.hw.disable()
        self._refresh()
