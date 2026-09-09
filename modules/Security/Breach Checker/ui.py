"""Qt Security Center — HIBP password/email checks plus vault audit list."""

from __future__ import annotations

import importlib
import re
import threading
import time
import webbrowser

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

hibp_api = importlib.import_module("modules.Security.Breach Checker.hibp_api")
security = importlib.import_module("modules.Security.Breach Checker.security")


def _restyle(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


class BreachCheckerPage(QWidget):
    def __init__(self, parent, manager):
        super().__init__(parent)
        self.manager = manager
        self.api_key = security.InMemorySecret()
        self._breach_cache = {}
        self._scanning = False

        root = QVBoxLayout(self)
        title = QLabel("Security Center")
        title.setObjectName("AccentTitle")
        hint = QLabel("HIBP checks + Secure Vault audit")
        hint.setObjectName("Muted")
        root.addWidget(title)
        root.addWidget(hint)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        tabs.addTab(self._build_password_tab(), "Password check")
        tabs.addTab(self._build_email_tab(), "Email lookup")
        tabs.addTab(self._build_audit_tab(), "Vault audit")

    def on_show(self):
        self._refresh_audit()

    def _build_password_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        intro = QLabel(
            "Checks a password against known breach dumps using the Pwned Passwords "
            "k-anonymity API — only a 5-character hash prefix ever leaves this device. "
            "No API key needed."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        row = QHBoxLayout()
        self.pw_entry = QLineEdit()
        self.pw_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_entry.setPlaceholderText("Enter a password to check")
        self.pw_entry.returnPressed.connect(self._check_password)
        self.pw_show = QCheckBox("Show")
        self.pw_show.toggled.connect(
            lambda on: self.pw_entry.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        row.addWidget(self.pw_entry, 1)
        row.addWidget(self.pw_show)
        lay.addLayout(row)

        btn_row = QHBoxLayout()
        self.pw_btn = QPushButton("Check password")
        self.pw_btn.setObjectName("Primary")
        self.pw_btn.clicked.connect(self._check_password)
        self.pw_status = QLabel("")
        self.pw_status.setObjectName("Muted")
        btn_row.addWidget(self.pw_btn)
        btn_row.addWidget(self.pw_status, 1)
        lay.addLayout(btn_row)

        card = QFrame()
        card.setObjectName("Panel")
        cl = QVBoxLayout(card)
        self.pw_title = QLabel("No password checked yet")
        self.pw_title.setObjectName("Muted")
        self.pw_detail = QLabel("")
        self.pw_detail.setObjectName("Muted")
        self.pw_detail.setWordWrap(True)
        cl.addWidget(self.pw_title)
        cl.addWidget(self.pw_detail)
        lay.addWidget(card)
        lay.addStretch(1)
        return page

    def _check_password(self):
        password = self.pw_entry.text()
        if not password:
            self.pw_status.setText("Enter a password first.")
            self.pw_status.setObjectName("Danger")
            _restyle(self.pw_status)
            return
        self.pw_btn.setEnabled(False)
        self.pw_btn.setText("Checking…")
        self.pw_status.setObjectName("Muted")
        self.pw_status.setText("Contacting Pwned Passwords API…")

        def worker():
            try:
                count = hibp_api.check_password(password)
                error = None
            except hibp_api.HIBPError as exc:
                count = None
                error = str(exc)
            QTimer.singleShot(0, lambda: self._on_password_result(count, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_password_result(self, count, error):
        self.pw_btn.setEnabled(True)
        self.pw_btn.setText("Check password")
        if error:
            self.pw_status.setText("Failed")
            self.pw_status.setObjectName("Danger")
            self.pw_title.setText("Lookup failed")
            self.pw_title.setObjectName("Danger")
            self.pw_detail.setText(error)
            _restyle(self.pw_status)
            _restyle(self.pw_title)
            return
        self.pw_status.setText("Done")
        self.pw_status.setObjectName("Success")
        _restyle(self.pw_status)
        if count == 0:
            self.pw_title.setText("Not found in any known breach")
            self.pw_title.setObjectName("Success")
            self.pw_detail.setText(
                "This password wasn't found in the Pwned Passwords dataset. "
                "That doesn't guarantee it's strong — just that it hasn't shown "
                "up in a breach dump HIBP has indexed yet."
            )
        else:
            self.pw_title.setText(
                f"Seen in {count:,} breach{'es' if count != 1 else ''}"
            )
            self.pw_title.setObjectName("Danger")
            self.pw_detail.setText(
                "This password has appeared in known data breaches and should be "
                "considered compromised. Stop using it anywhere."
            )
        _restyle(self.pw_title)

    def _build_email_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        intro = QLabel(
            "Checks an email address against HIBP's breach database. This endpoint "
            "requires your own HIBP API key — kept in memory for this session only."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        key_row = QHBoxLayout()
        self.key_entry = QLineEdit()
        self.key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_entry.setPlaceholderText("HIBP API key")
        get_key = QPushButton("Get a key")
        get_key.clicked.connect(lambda: webbrowser.open("https://haveibeenpwned.com/API/Key"))
        key_row.addWidget(self.key_entry, 1)
        key_row.addWidget(get_key)
        lay.addLayout(key_row)

        self.email_entry = QLineEdit()
        self.email_entry.setPlaceholderText("you@example.com")
        self.email_entry.returnPressed.connect(self._check_email)
        lay.addWidget(self.email_entry)

        btn_row = QHBoxLayout()
        self.email_btn = QPushButton("Check email")
        self.email_btn.setObjectName("Primary")
        self.email_btn.clicked.connect(self._check_email)
        self.email_status = QLabel("")
        self.email_status.setObjectName("Muted")
        btn_row.addWidget(self.email_btn)
        btn_row.addWidget(self.email_status, 1)
        lay.addLayout(btn_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.email_host = QWidget()
        self.email_lay = QVBoxLayout(self.email_host)
        scroll.setWidget(self.email_host)
        lay.addWidget(scroll, 1)
        self._email_placeholder("No email checked yet.")
        return page

    def _clear_email(self):
        while self.email_lay.count():
            item = self.email_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _email_placeholder(self, text, danger=False):
        self._clear_email()
        lab = QLabel(text)
        lab.setObjectName("Danger" if danger else "Muted")
        lab.setWordWrap(True)
        self.email_lay.addWidget(lab)
        self.email_lay.addStretch(1)

    def _check_email(self):
        email = self.email_entry.text().strip()
        key = self.key_entry.text().strip()
        if not email:
            self.email_status.setText("Enter an email first.")
            self.email_status.setObjectName("Danger")
            _restyle(self.email_status)
            return
        if not key:
            self.email_status.setText("An HIBP API key is required.")
            self.email_status.setObjectName("Danger")
            _restyle(self.email_status)
            return
        self.api_key.set(key)
        self.email_btn.setEnabled(False)
        self.email_btn.setText("Checking…")
        self.email_status.setObjectName("Muted")
        self.email_status.setText("Contacting HIBP…")
        self._email_placeholder("Checking…")

        def worker():
            try:
                breaches = hibp_api.check_account(email, self.api_key.get())
                error = None
            except hibp_api.HIBPError as exc:
                breaches = None
                error = str(exc)
            QTimer.singleShot(0, lambda: self._on_email_result(breaches, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_email_result(self, breaches, error):
        self.email_btn.setEnabled(True)
        self.email_btn.setText("Check email")
        if error:
            self.email_status.setText("Failed")
            self.email_status.setObjectName("Danger")
            _restyle(self.email_status)
            self._email_placeholder(error, danger=True)
            return
        if not breaches:
            self.email_status.setText("Done")
            self.email_status.setObjectName("Success")
            _restyle(self.email_status)
            self._email_placeholder("No known breaches found for this address.")
            return
        self.email_status.setText(
            f"Found {len(breaches)} breach{'es' if len(breaches) != 1 else ''}"
        )
        self.email_status.setObjectName("Danger")
        _restyle(self.email_status)
        self._clear_email()
        for breach in breaches:
            self._render_breach_card(breach)
        self.email_lay.addStretch(1)

    def _render_breach_card(self, breach: dict):
        name = breach.get("Title") or breach.get("Name") or "Unknown breach"
        domain = breach.get("Domain") or ""
        date = breach.get("BreachDate") or "Unknown date"
        classes = breach.get("DataClasses") or []
        description = _strip_html(breach.get("Description") or "")
        card = QFrame()
        card.setObjectName("Panel")
        cl = QVBoxLayout(card)
        title = QLabel(name if not domain else f"{name}  ({domain})")
        title.setObjectName("CardTitle")
        cl.addWidget(title)
        if not breach.get("IsVerified", True):
            unv = QLabel("UNVERIFIED")
            unv.setObjectName("Muted")
            cl.addWidget(unv)
        date_lab = QLabel(f"Breach date: {date}")
        date_lab.setObjectName("Muted")
        cl.addWidget(date_lab)
        if classes:
            exposed = QLabel("Exposed data: " + ", ".join(classes))
            exposed.setObjectName("Danger")
            exposed.setWordWrap(True)
            cl.addWidget(exposed)
        if description:
            desc = QLabel(description)
            desc.setObjectName("Muted")
            desc.setWordWrap(True)
            cl.addWidget(desc)
        self.email_lay.addWidget(card)

    def _build_audit_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        top = QHBoxLayout()
        self.audit_summary = QLabel("")
        self.audit_summary.setObjectName("Muted")
        self.audit_summary.setWordWrap(True)
        scan = QPushButton("Scan for leaks")
        scan.setObjectName("Primary")
        scan.clicked.connect(self._scan_leaks)
        self._scan_btn = scan
        top.addWidget(self.audit_summary, 1)
        top.addWidget(scan)
        lay.addLayout(top)
        self.audit_status = QLabel("")
        self.audit_status.setObjectName("Muted")
        lay.addWidget(self.audit_status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.audit_host = QWidget()
        self.audit_lay = QVBoxLayout(self.audit_host)
        scroll.setWidget(self.audit_host)
        lay.addWidget(scroll, 1)
        self._refresh_audit()
        return page

    def _clear_audit(self):
        while self.audit_lay.count():
            item = self.audit_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _vault_ready(self):
        auth = self.manager.container.auth_service
        if not auth.is_initialized():
            return False, "No vault yet. Create a master password in Secure Vault first."
        if auth.is_locked():
            return False, "Vault is locked. Unlock Secure Vault to list weak, reused, and leaked passwords."
        return True, ""

    def _refresh_audit(self):
        self._clear_audit()
        ok, message = self._vault_ready()
        if not ok:
            self.audit_summary.setText(message)
            self._scan_btn.setEnabled(False)
            lab = QLabel(message)
            lab.setObjectName("Muted")
            lab.setWordWrap(True)
            self.audit_lay.addWidget(lab)
            self.audit_lay.addStretch(1)
            return
        self._scan_btn.setEnabled(True)
        vault = self.manager.container.vault_service
        audit = vault.audit_summary()
        leaked = sum(1 for c in self._breach_cache.values() if c > 0)
        extra = f" · {leaked} leaked" if self._breach_cache else ""
        self.audit_summary.setText(
            f"{audit['total']} passwords · {audit['weak_count']} weak · "
            f"{audit['reused_count']} reused{extra}"
        )
        entries = {e["id"]: e for e in vault.get_entries()}
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
        if not tagged:
            empty = QLabel("No issues found — your vault looks healthy.")
            empty.setObjectName("Muted")
            self.audit_lay.addWidget(empty)
            self.audit_lay.addStretch(1)
            return
        for entry, tags in tagged.values():
            row = QFrame()
            row.setObjectName("Panel")
            rl = QVBoxLayout(row)
            site = QLabel(entry.get("site") or "Untitled")
            site.setObjectName("CardTitle")
            user = QLabel(entry.get("username") or "—")
            user.setObjectName("Muted")
            tag_lab = QLabel(" · ".join(tags))
            tag_lab.setObjectName("Danger")
            tag_lab.setWordWrap(True)
            rl.addWidget(site)
            rl.addWidget(user)
            rl.addWidget(tag_lab)
            self.audit_lay.addWidget(row)
        self.audit_lay.addStretch(1)

    def _scan_leaks(self):
        ok, message = self._vault_ready()
        if not ok:
            self.audit_status.setText(message)
            return
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.setEnabled(False)
        self.audit_status.setText("Scanning passwords against Have I Been Pwned…")
        vault = self.manager.container.vault_service

        def worker():
            entries = vault.get_entries()
            total = len(entries)
            for i, entry in enumerate(entries):
                try:
                    self._breach_cache[entry["id"]] = hibp_api.check_password(entry["password"])
                except hibp_api.HIBPError as exc:
                    QTimer.singleShot(0, lambda msg=str(exc): self.audit_status.setText(msg))
                    break
                except Exception:
                    self._breach_cache[entry["id"]] = 0
                if i < total - 1:
                    time.sleep(0.25)
                QTimer.singleShot(
                    0,
                    lambda n=i + 1, t=total: self.audit_status.setText(f"Scanning… {n}/{t}"),
                )
            QTimer.singleShot(0, self._scan_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _scan_finished(self):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        leaked = sum(1 for c in self._breach_cache.values() if c > 0)
        self.audit_status.setText(f"Scan complete — {leaked} password(s) found in known breaches.")
        self._refresh_audit()
