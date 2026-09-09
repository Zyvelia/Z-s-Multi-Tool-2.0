"""QSS built from the same catalog theme tokens the CTk home used."""

from pages.catalog_theme import resolve_catalog_theme


def bundle_from_settings(settings):
    return resolve_catalog_theme(settings.get("catalog_theme") if settings else None)


def qss_for_bundle(bundle) -> str:
    t = bundle.t
    on = bundle.on_accent
    return f"""
    QMainWindow, QWidget#Central, QWidget#CatalogRoot, QWidget#SettingsRoot,
    QWidget#NowRoot, QWidget#MarketplaceRoot, QWidget#ToolHost, QWidget#QtToolHost, QWidget#ModuleShell,
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background-color: {t.BG};
        color: {t.TEXT};
        font-family: "Segoe UI";
    }}
    QLabel {{
        color: {t.TEXT};
        background: transparent;
    }}
    QLabel#Muted, QLabel#Subtitle {{
        color: {t.MUTED};
    }}
    QLabel#AccentTitle {{
        color: {t.ACCENT};
        font-size: 22px;
        font-weight: 700;
    }}
    QLabel#Success {{
        color: {t.SUCCESS};
        background: transparent;
    }}
    QLabel#Error {{
        color: {t.ERROR};
        background: transparent;
    }}
    QLabel#Warn {{
        color: #fb923c;
        background: transparent;
    }}
    QComboBox {{
        background-color: {t.PANEL_2};
        color: {t.TEXT};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 6px 10px;
        min-width: 70px;
    }}
    QComboBox::drop-down {{
        border: none;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t.PANEL_2};
        color: {t.TEXT};
        selection-background-color: {t.ACCENT};
        selection-color: {on};
    }}
    QLabel#CardTitle {{
        font-size: 15px;
        font-weight: 700;
        color: {t.TEXT};
    }}
    QLabel#CardDesc {{
        color: {t.MUTED};
        font-size: 12px;
    }}
    QLabel#CardCat {{
        color: {t.ACCENT};
        font-size: 10px;
        font-weight: 700;
    }}
    QLineEdit {{
        background-color: {t.PANEL_2};
        color: {t.TEXT};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 8px 12px;
        selection-background-color: {t.ACCENT};
        selection-color: {on};
    }}
    QPushButton {{
        background-color: {t.PANEL_2};
        color: {t.TEXT};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 8px 14px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {t.PANEL_HOVER};
    }}
    QPushButton#Primary, QPushButton#OpenBtn {{
        background-color: {t.ACCENT};
        color: {on};
        border: 1px solid {t.ACCENT};
        font-weight: 700;
    }}
    QPushButton#Primary:hover, QPushButton#OpenBtn:hover {{
        background-color: {t.ACCENT_HOVER};
    }}
    QPushButton#Danger {{
        background-color: {t.DANGER_BG};
        color: {t.DANGER};
        border: 1px solid {t.DANGER};
    }}
    QPushButton#Pill {{
        border-radius: 16px;
        padding: 6px 14px;
        background-color: {t.PANEL_2};
        border: 1px solid {t.BORDER};
    }}
    QPushButton#Pill:checked {{
        background-color: {t.ACCENT};
        color: {on};
        border: 1px solid {t.ACCENT};
        font-weight: 700;
    }}
    QPushButton#HideBtn {{
        min-width: 22px;
        max-width: 22px;
        min-height: 22px;
        max-height: 22px;
        padding: 0;
        border-radius: 11px;
        font-size: 11px;
        font-weight: 700;
        color: {t.MUTED};
    }}
    QPushButton#HideBtn:hover {{
        background-color: {t.DANGER_BG};
        color: {t.DANGER};
    }}
    QFrame#Card {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 14px;
    }}
    QFrame#Card:hover {{
        border: 1px solid {t.ACCENT};
    }}
    QFrame#Panel {{
        background-color: {t.PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 14px;
    }}
    QFrame#ThemeCard {{
        background-color: {t.PANEL_2};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
    }}
    QFrame#ThemeCard[selected="true"] {{
        border: 2px solid {t.ACCENT};
    }}
    QCheckBox {{
        color: {t.TEXT};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {t.BORDER};
        background: {t.PANEL_2};
        border-radius: 4px;
    }}
    QCheckBox::indicator:checked {{
        background: {t.ACCENT};
        border: 1px solid {t.ACCENT};
    }}
    QScrollBar:vertical {{
        background: {bundle.scroll_track};
        width: 10px;
        margin: 0;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {bundle.scroll_thumb};
        min-height: 32px;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {bundle.scroll_thumb_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollArea {{
        border: none;
    }}
    QTabWidget::pane {{
        border: 1px solid {t.BORDER};
        background: {t.BG};
    }}
    QTabBar::tab {{
        background: {t.PANEL_2};
        color: {t.TEXT};
        padding: 8px 14px;
        border: 1px solid {t.BORDER};
        border-bottom: none;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background: {t.ACCENT};
        color: {on};
        font-weight: 700;
    }}
    QPlainTextEdit, QTextEdit {{
        background-color: {t.PANEL_2};
        color: {t.TEXT};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        padding: 8px;
        selection-background-color: {t.ACCENT};
        selection-color: {on};
    }}
    QListWidget {{
        background-color: {t.PANEL};
        color: {t.TEXT};
        border: 1px solid {t.BORDER};
        border-radius: 8px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 8px 10px;
    }}
    QListWidget::item:selected {{
        background: {t.ACCENT};
        color: {on};
    }}
    QProgressBar {{
        background: {t.BORDER};
        border: none;
        border-radius: 2px;
        height: 6px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        background: {t.ACCENT};
        border-radius: 2px;
    }}
    """
