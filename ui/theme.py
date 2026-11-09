"""视觉规范：颜色、字号、全局样式表。

沿用产品文档 §4.8 的设计 token，保证桌面端和之前的设计稿是同一套语言。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont


def asset(name: str) -> str:
    """打包成 exe 后资源在 _MEIPASS/ui 下，源码运行时在 ui/ 同级。"""
    here = Path(__file__).resolve().parent
    for base in (Path(getattr(sys, "_MEIPASS", here)), here):
        for cand in (base / "ui" / name, base / name):
            if cand.exists():
                return cand.as_posix()
    return (here / name).as_posix()


CHECK_ICON = asset("check.png")

# ---------------- 颜色 ----------------
INK = "#0E0F12"          # 主文字 / 主按钮底
INK_SOFT = "#3A3F47"
MUTED = "#71767F"        # 次要文字
FAINT = "#9AA0A8"        # 弱化文字
LINE = "#ECEDEF"         # 分割线 / 描边
BG = "#F7F8FA"           # 窗口底
CARD = "#FFFFFF"
ACCENT = "#FF5A36"       # 强调橙（评分、硬伤）
ACCENT_SOFT = "#FFF1EC"  # 橙色浅底（提示胶囊）
GOLD = "#FFB020"         # 星级金
GREEN = "#1F9D55"

C_INK = QColor(INK)
C_MUTED = QColor(MUTED)
C_FAINT = QColor(FAINT)
C_LINE = QColor(LINE)
C_BG = QColor(BG)
C_CARD = QColor(CARD)
C_ACCENT = QColor(ACCENT)
C_GOLD = QColor(GOLD)

# ---------------- 字体 ----------------
FONT_FAMILY = "Microsoft YaHei UI"
FS_TITLE = 21
FS_BODY = 13
FS_SMALL = 12
FS_TINY = 11


def font(size: int = FS_BODY, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY, size)
    f.setBold(bold)
    return f


QSS = f"""
QWidget {{
    font-family: "{FONT_FAMILY}";
    font-size: {FS_BODY}px;
    color: {INK};
}}
QMainWindow, #Root {{ background: {BG}; }}

/* ---------- 顶部栏 ---------- */
#TopBar {{ background: {CARD}; border-bottom: 1px solid {LINE}; }}
#AppTitle {{ font-size: {FS_TITLE}px; font-weight: 600; }}
#PathLabel {{ color: {MUTED}; font-size: {FS_SMALL}px; }}
#StatChip {{
    color: {MUTED}; font-size: {FS_SMALL}px;
    background: {BG}; border-radius: 9px; padding: 4px 10px;
}}
#WarnChip {{
    color: {ACCENT}; font-size: {FS_SMALL}px;
    background: {ACCENT_SOFT}; border-radius: 9px; padding: 4px 10px;
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    border: none; border-radius: 14px; padding: 8px 16px;
    background: {LINE}; color: {INK};
}}
QPushButton:hover {{ background: #E2E4E8; }}
QPushButton:pressed {{ background: #D8DADF; }}
QPushButton:disabled {{ color: {FAINT}; background: #F2F3F5; }}

QPushButton#Primary {{
    background: {INK}; color: #FFFFFF; font-weight: 600; padding: 9px 20px;
}}
QPushButton#Primary:hover {{ background: #24262C; }}
QPushButton#Primary:pressed {{ background: #000000; }}
QPushButton#Primary:disabled {{ background: #C9CCD2; color: #FFFFFF; }}

QPushButton#Accent {{
    background: {ACCENT}; color: #FFFFFF; font-weight: 600; padding: 9px 20px;
}}
QPushButton#Accent:hover {{ background: #FF6E4E; }}

/* 一键全部归档：比单档按钮更重，撑满整行 */
QPushButton#AllPrimary {{
    background: {ACCENT}; color: #FFFFFF; font-weight: 700; padding: 13px 18px;
    border-radius: 12px; font-size: 14px;
}}
QPushButton#AllPrimary:hover {{ background: #FF6E4E; }}
QPushButton#AllPrimary:pressed {{ background: #E64B29; }}
QPushButton#AllPrimary:disabled {{ background: #E8EAED; color: {FAINT}; font-weight: 600; }}

QPushButton#Ghost {{
    background: transparent; color: {MUTED}; padding: 8px 10px;
}}
QPushButton#Ghost:hover {{ background: {LINE}; color: {INK}; }}

/* 顶栏「更换」小胶囊按钮 */
QPushButton#SwitchBtn {{
    background: {CARD}; color: {MUTED}; border: 1px solid {LINE};
    border-radius: 11px; padding: 0px 10px; font-size: {FS_TINY}px;
}}
QPushButton#SwitchBtn:hover {{ background: {LINE}; color: {INK}; border-color: {LINE}; }}

/* ---------- 侧栏 ---------- */
#SideBar {{ background: {CARD}; border-right: 1px solid {LINE}; }}
#SideTitle {{
    color: {FAINT}; font-size: {FS_TINY}px; font-weight: 600;
    letter-spacing: 1px; padding: 6px 14px 2px 14px;
}}
QPushButton#NavItem {{
    text-align: left; background: transparent; border-radius: 10px;
    padding: 8px 12px; color: {INK_SOFT};
}}
QPushButton#NavItem:hover {{ background: {BG}; }}
QPushButton#NavItem:checked {{ background: {INK}; color: #FFFFFF; font-weight: 600; }}
QPushButton#NavItem:checked:hover {{ background: #24262C; }}

/* ---------- 网格 ---------- */
QListView {{
    background: transparent; border: none; outline: none;
    padding: 6px;
}}
QListView::item {{ background: transparent; }}
QListView::item:selected {{ background: transparent; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #D3D6DB; border-radius: 4px; min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{ background: #B9BDC4; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: #D3D6DB; border-radius: 4px; min-width: 40px;
}}

/* ---------- 底部状态条 ---------- */
#StatusBar {{ background: {CARD}; border-top: 1px solid {LINE}; }}
#StatusText {{ color: {MUTED}; font-size: {FS_SMALL}px; }}
QProgressBar {{
    border: none; background: {LINE}; border-radius: 3px;
    height: 6px; text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

/* ---------- 空状态 ---------- */
#EmptyTitle {{ font-size: 26px; font-weight: 600; }}
#EmptyHint {{ color: {MUTED}; font-size: 13px; }}

/* ---------- 对话框 ---------- */
QDialog {{ background: {BG}; }}
QLabel#DialogTitle {{ font-size: 17px; font-weight: 600; }}
QCheckBox {{ color: {INK_SOFT}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid #CFD3D9; background: #FFFFFF;
}}
QCheckBox::indicator:checked {{
    background: {INK}; border: 1px solid {INK};
    image: url({CHECK_ICON});
}}
"""
