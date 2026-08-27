"""Security audit tab — weak/reused passwords and breach scanning."""

from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

import customtkinter as ctk

from core import theme

_hibp_path = Path(__file__).resolve().parent.parent / "Breach Checker" / "hibp_api.py"
_spec = importlib.util.spec_from_file_location("vault_hibp_api", _hibp_path)
_hibp = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_hibp)
check_password = _hibp.check_password
HIBPError = _hibp.HIBPError


class SecurityAuditTab(ctk.CTkFrame):

    def __init__(self, parent, vault_page):
        super().__init__(parent, fg_color="transparent")
        self.vault_page = vault_page
        self.vault = vault_page.vault
        self._breach_cache: dict[str, int] = {}
        self._scanning = False

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="🛡 Security Audit", font=theme.font(18, "bold"), text_color=theme.TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

        self._score_label = ctk.CTkLabel(
            header, text="Score: —", font=theme.mono(14, "bold"), text_color=theme.SUCCESS,
        )
        self._score_label.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 4))

        self._summary_label = ctk.CTkLabel(
            header, text="", font=theme.font(11), text_color=theme.MUTED, anchor="w", justify="left",
        )
        self._summary_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=3, sticky="e", padx=16, pady=12)

        self._scan_btn = ctk.CTkButton(
            actions, text="Scan breaches", width=130, height=34,
            command=self._start_breach_scan, **theme.secondary_button_style(),
        )
        self._scan_btn.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            actions, text="Refresh", width=90, height=34,
            command=self.refresh, **theme.secondary_button_style(),
        ).pack(side="left")

        self._scan_status = ctk.CTkLabel(
            header, text="", font=theme.font(10), text_color=theme.FAINT,
        )
        self._scan_status.grid(row=3, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 10))

        self._list = ctk.CTkScrollableFrame(self, fg_color=theme.PANEL, corner_radius=theme.RADIUS)
        self._list.grid(row=1, column=0, sticky="nsew")

        self.refresh()

    def get_breach_count(self, entry_id: str) -> int:
        return self._breach_cache.get(entry_id, 0)

    def refresh(self):
        if not self.winfo_exists():
            return

        for w in self._list.winfo_children():
            w.destroy()

        audit = self.vault.audit_summary()
        score = audit["score"]
        color = theme.SUCCESS
        if score < 80:
            color = "#f1c40f"
        if score < 60:
            color = theme.ERROR

        self._score_label.configure(text=f"Score: {score}/100", text_color=color)
        breached = sum(1 for c in self._breach_cache.values() if c > 0)
        self._summary_label.configure(
            text=(
                f"{audit['total']} passwords · {audit['weak_count']} weak · "
                f"{audit['reused_count']} reused"
                + (f" · {breached} found in breaches" if self._breach_cache else "")
            ),
        )

        issues: list[tuple[str, dict, list[str]]] = []
        entries = {e["id"]: e for e in self.vault.get_entries()}

        for eid in audit["weak_ids"]:
            entry = entries.get(eid)
            if entry:
                issues.append(("weak", entry, ["Weak password"]))

        for eid in audit["reused_ids"]:
            entry = entries.get(eid)
            if entry and eid not in audit["weak_ids"]:
                issues.append(("reused", entry, ["Password reused elsewhere"]))
            elif entry and eid in audit["weak_ids"]:
                for kind, ent, tags in issues:
                    if ent["id"] == eid:
                        tags.append("Password reused elsewhere")
                        break

        for eid, count in self._breach_cache.items():
            if count <= 0:
                continue
            entry = entries.get(eid)
            if not entry:
                continue
            existing = next((i for i in issues if i[1]["id"] == eid), None)
            tag = f"In {count:,} breaches"
            if existing:
                existing[2].append(tag)
            else:
                issues.append(("breached", entry, [tag]))

        if not issues:
            ctk.CTkLabel(
                self._list,
                text="No issues found — your vault looks healthy.",
                font=theme.font(13), text_color=theme.MUTED,
            ).pack(pady=40, padx=20)
            return

        for _kind, entry, tags in issues:
            self._issue_row(entry, tags)

    def _issue_row(self, entry: dict, tags: list[str]):
        row = ctk.CTkFrame(self._list, fg_color=theme.PANEL_2, corner_radius=theme.RADIUS_SM)
        row.pack(fill="x", padx=10, pady=6)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=14, pady=12)

        ctk.CTkLabel(
            info, text=entry["site"], font=theme.font(14, "bold"), text_color=theme.TEXT, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            info, text=entry.get("username") or "—", font=theme.font(11), text_color=theme.MUTED, anchor="w",
        ).pack(anchor="w", pady=(2, 4))

        tag_row = ctk.CTkFrame(info, fg_color="transparent")
        tag_row.pack(anchor="w")
        for tag in tags:
            color = theme.ERROR if "breach" in tag.lower() else "#e0803f"
            if "reused" in tag.lower():
                color = "#f1c40f"
            ctk.CTkLabel(
                tag_row, text=f" {tag} ", font=theme.font(9, "bold"),
                text_color="#0b0d10", fg_color=color, corner_radius=6,
            ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            row, text="Fix", width=70, height=32,
            command=lambda e=entry: self.vault_page.open_edit_dialog(e),
            **theme.primary_button_style(),
        ).pack(side="right", padx=14, pady=12)

    def _start_breach_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.configure(state="disabled")
        self._scan_status.configure(text="Scanning passwords against Have I Been Pwned…")

        def worker():
            entries = self.vault.get_entries()
            total = len(entries)
            for i, entry in enumerate(entries):
                try:
                    self._breach_cache[entry["id"]] = check_password(entry["password"])
                except HIBPError as exc:
                    self.after(0, lambda msg=str(exc): self._scan_status.configure(text=msg))
                    break
                except Exception:
                    self._breach_cache[entry["id"]] = 0
                if i < total - 1:
                    time.sleep(0.25)
                self.after(0, lambda n=i + 1, t=total: self._scan_status.configure(
                    text=f"Scanning… {n}/{t}",
                ))
            self.after(0, self._scan_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _scan_finished(self):
        self._scanning = False
        self._scan_btn.configure(state="normal")
        breached = sum(1 for c in self._breach_cache.values() if c > 0)
        self._scan_status.configure(
            text=f"Scan complete — {breached} password(s) found in known breaches.",
        )
        self.vault_page.set_breach_cache(self._breach_cache)
        self.refresh()
        self.vault_page.render()
