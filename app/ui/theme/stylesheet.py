"""The Mediary stylesheet, generated from design tokens.

One template renders both themes. Widgets opt into a variant with a Qt property
(``setProperty("variant", "primary")``) or an object name, never with inline
styling, so the whole look stays in this file.
"""

from __future__ import annotations

from app.ui.theme.tokens import Palette, Radius, Size, Space, Type, font_stack, mono_stack


def build_stylesheet(p: Palette) -> str:
    """Render the complete application stylesheet for a palette."""
    return _TEMPLATE.format(
        # colours
        app=p.app,
        sidebar=p.sidebar,
        surface=p.surface,
        elevated=p.elevated,
        inset=p.inset,
        hover=p.hover,
        active=p.active,
        selected=p.selected,
        selected_text=p.selected_text,
        border=p.border,
        border_strong=p.border_strong,
        divider=p.divider,
        text=p.text,
        text_secondary=p.text_secondary,
        text_muted=p.text_muted,
        text_inverted=p.text_inverted,
        accent=p.accent,
        accent_hover=p.accent_hover,
        accent_pressed=p.accent_pressed,
        accent_soft=p.accent_soft,
        accent_text=p.accent_text,
        success=p.success,
        success_soft=p.success_soft,
        warning=p.warning,
        warning_soft=p.warning_soft,
        danger=p.danger,
        danger_hover=p.danger_hover,
        danger_soft=p.danger_soft,
        thumb_bg=p.thumb_bg,
        scrollbar=p.scrollbar,
        scrollbar_hover=p.scrollbar_hover,
        # type
        font=font_stack(),
        mono=mono_stack(),
        t_micro=Type.micro,
        t_label=Type.label,
        t_small=Type.small,
        t_body=Type.body,
        t_medium=Type.medium,
        t_large=Type.large,
        t_title=Type.title,
        t_hero=Type.hero,
        w_medium=Type.weight_medium,
        w_semibold=Type.weight_semibold,
        w_bold=Type.weight_bold,
        tracking=Type.tracking_label,
        # metrics
        s_xs=Space.xs,
        s_sm=Space.sm,
        s_md=Space.md,
        s_lg=Space.lg,
        s_xl=Space.xl,
        r_xs=Radius.xs,
        r_sm=Radius.sm,
        r_md=Radius.md,
        r_lg=Radius.lg,
        r_xl=Radius.xl,
        h_control=Size.control_height,
        h_control_sm=Size.control_height_sm,
        h_input=Size.input_height,
    )


_TEMPLATE = """
/* ==================================================================
   Base
   ================================================================== */

QWidget {{
    font-family: {font};
    font-size: {t_body}px;
    color: {text};
    background: transparent;
}}

QMainWindow, QDialog {{
    background: {app};
}}

QToolTip {{
    background: {elevated};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: {r_sm}px;
    padding: 5px 8px;
    font-size: {t_small}px;
}}

/* ==================================================================
   Layout regions
   ================================================================== */

#Sidebar {{
    background: {sidebar};
    border-right: 1px solid {border};
}}

#ContentArea {{
    background: {surface};
}}

#TopBar {{
    background: {surface};
    border-bottom: 1px solid {border};
}}

#StatusBar {{
    background: {sidebar};
    border-top: 1px solid {border};
    color: {text_secondary};
    font-size: {t_small}px;
}}

#Panel {{
    background: {elevated};
    border: 1px solid {border};
    border-radius: {r_lg}px;
}}

#InsetPanel {{
    background: {inset};
    border: 1px solid {border};
    border-radius: {r_md}px;
}}

#Divider {{
    background: {divider};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

#VDivider {{
    background: {divider};
    max-width: 1px;
    min-width: 1px;
    border: none;
}}

/* ==================================================================
   Typography helpers
   ================================================================== */

QLabel[role="pageTitle"] {{
    font-size: {t_title}px;
    font-weight: {w_semibold};
    color: {text};
}}

QLabel[role="pageSubtitle"] {{
    font-size: {t_body}px;
    color: {text_secondary};
}}

QLabel[role="sectionLabel"] {{
    font-size: {t_label}px;
    font-weight: {w_semibold};
    color: {text_muted};
    letter-spacing: {tracking};
    text-transform: uppercase;
}}

QLabel[role="fieldLabel"] {{
    font-size: {t_label}px;
    font-weight: {w_semibold};
    color: {text_muted};
    letter-spacing: {tracking};
    text-transform: uppercase;
}}

QLabel[role="heading"] {{
    font-size: {t_large}px;
    font-weight: {w_semibold};
    color: {text};
}}

QLabel[role="itemTitle"] {{
    font-size: {t_medium}px;
    font-weight: {w_medium};
    color: {text};
}}

QLabel[role="meta"] {{
    font-size: {t_small}px;
    color: {text_secondary};
}}

QLabel[role="muted"] {{
    font-size: {t_small}px;
    color: {text_muted};
}}

QLabel[role="mono"] {{
    font-family: {mono};
    font-size: {t_small}px;
    color: {text_secondary};
}}

QLabel[role="heroTitle"] {{
    font-size: {t_hero}px;
    font-weight: {w_semibold};
    color: {text};
}}

QLabel[role="heroBody"] {{
    font-size: {t_medium}px;
    color: {text_secondary};
}}

QLabel[role="danger"] {{ color: {danger}; }}
QLabel[role="success"] {{ color: {success}; }}
QLabel[role="warning"] {{ color: {warning}; }}

/* ==================================================================
   Buttons
   ================================================================== */

QPushButton {{
    background: {elevated};
    color: {text};
    border: 1px solid {border_strong};
    border-radius: {r_sm}px;
    padding: 0 {s_md}px;
    min-height: {h_control}px;
    font-size: {t_body}px;
    font-weight: {w_medium};
}}

QPushButton:hover {{
    background: {hover};
    border-color: {border_strong};
}}

QPushButton:pressed {{
    background: {active};
}}

QPushButton:disabled {{
    color: {text_muted};
    background: {elevated};
    border-color: {border};
}}

QPushButton:focus {{
    border-color: {accent};
    outline: none;
}}

QPushButton[variant="primary"] {{
    background: {accent};
    color: {accent_text};
    border: 1px solid {accent};
    font-weight: {w_semibold};
}}
QPushButton[variant="primary"]:hover  {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {accent_pressed}; border-color: {accent_pressed}; }}
QPushButton[variant="primary"]:disabled {{
    background: {accent_soft};
    color: {text_muted};
    border-color: transparent;
}}

QPushButton[variant="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {text_secondary};
    font-weight: {w_medium};
}}
QPushButton[variant="ghost"]:hover  {{ background: {hover}; color: {text}; }}
QPushButton[variant="ghost"]:pressed {{ background: {active}; }}
QPushButton[variant="ghost"]:checked {{ background: {active}; color: {text}; }}

QPushButton[variant="subtle"] {{
    background: {inset};
    border: 1px solid {border};
    color: {text_secondary};
}}
QPushButton[variant="subtle"]:hover {{ background: {hover}; color: {text}; }}

QPushButton[variant="danger"] {{
    background: {danger};
    color: #FFFFFF;
    border: 1px solid {danger};
    font-weight: {w_semibold};
}}
QPushButton[variant="danger"]:hover {{ background: {danger_hover}; border-color: {danger_hover}; }}

QPushButton[variant="link"] {{
    background: transparent;
    border: none;
    color: {accent};
    padding: 0;
    min-height: 0;
    font-weight: {w_medium};
    text-align: left;
}}
QPushButton[variant="link"]:hover {{ color: {accent_hover}; }}

QPushButton[size="sm"] {{
    min-height: {h_control_sm}px;
    padding: 0 {s_sm}px;
    font-size: {t_small}px;
}}

QPushButton[size="lg"] {{
    min-height: 40px;
    padding: 0 {s_xl}px;
    font-size: {t_medium}px;
}}

/* Icon-only buttons */
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {r_sm}px;
    padding: {s_xs}px;
    color: {text_secondary};
}}
QToolButton:hover   {{ background: {hover}; color: {text}; }}
QToolButton:pressed {{ background: {active}; }}
QToolButton:checked {{ background: {active}; color: {accent}; }}
QToolButton:disabled {{ color: {text_muted}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ==================================================================
   Inputs
   ================================================================== */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {inset};
    border: 1px solid {border_strong};
    border-radius: {r_sm}px;
    padding: 0 {s_md}px;
    min-height: {h_input}px;
    color: {text};
    selection-background-color: {accent};
    selection-color: {accent_text};
}}

QPlainTextEdit, QTextEdit {{
    padding: {s_sm}px {s_md}px;
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {accent};
    background: {surface};
}}

QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {{
    color: {text_muted};
    background: {inset};
    border-color: {border};
}}

QLineEdit[role="search"] {{
    padding-left: 30px;
    background: {inset};
}}

QLineEdit[role="hero"] {{
    font-size: {t_medium}px;
    min-height: 44px;
    padding: 0 {s_lg}px;
    border-radius: {r_md}px;
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 18px;
    border: none;
    background: transparent;
    subcontrol-origin: border;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url(mediary:chevron-up);
    width: 10px; height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url(mediary:chevron-down);
    width: 10px; height: 10px;
}}

/* ==================================================================
   Combo boxes
   ================================================================== */

QComboBox {{
    background: {inset};
    border: 1px solid {border_strong};
    border-radius: {r_sm}px;
    padding: 0 {s_sm}px 0 {s_md}px;
    min-height: {h_input}px;
    color: {text};
}}
QComboBox:hover  {{ border-color: {border_strong}; background: {hover}; }}
QComboBox:focus  {{ border-color: {accent}; }}
QComboBox:disabled {{ color: {text_muted}; }}
QComboBox::drop-down {{
    border: none;
    width: 24px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox::down-arrow {{
    image: url(mediary:chevron-down);
    width: 10px;
    height: 10px;
}}
QComboBox::down-arrow:on, QComboBox::down-arrow:hover {{
    image: url(mediary:chevron-down-hover);
}}

QComboBox[size="sm"] {{
    min-height: {h_control_sm}px;
    max-height: {h_control_sm}px;
    font-size: {t_small}px;
    padding-left: {s_sm}px;
}}

QComboBox QAbstractItemView {{
    background: {elevated};
    border: 1px solid {border_strong};
    border-radius: {r_md}px;
    padding: {s_xs}px;
    outline: none;
    selection-background-color: {accent_soft};
    selection-color: {text};
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 0 {s_sm}px;
    border-radius: {r_xs}px;
    color: {text};
}}
QComboBox QAbstractItemView::item:hover {{ background: {hover}; }}
QComboBox QAbstractItemView::item:selected {{ background: {accent_soft}; color: {text}; }}

/* ==================================================================
   Check boxes / radios / switches
   ================================================================== */

QCheckBox, QRadioButton {{
    spacing: {s_sm}px;
    color: {text};
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {border_strong};
    background: {inset};
}}
QCheckBox::indicator {{ border-radius: {r_xs}px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url(mediary:check);
}}
QRadioButton::indicator:checked {{
    background: {accent};
    border: 4px solid {inset};
    outline: 1px solid {accent};
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {text_muted}; }}

/* ==================================================================
   Lists, trees, tables
   ================================================================== */

QListView, QTreeView, QTableView, QListWidget, QTreeWidget, QTableWidget {{
    background: transparent;
    border: none;
    outline: none;
    color: {text};
    selection-background-color: transparent;
    alternate-background-color: transparent;
}}

QListView::item, QTreeView::item {{
    border-radius: {r_sm}px;
    padding: {s_xs}px;
    color: {text};
}}
QListView::item:hover, QTreeView::item:hover {{ background: {hover}; }}
QListView::item:selected, QTreeView::item:selected {{
    background: {selected};
    color: {selected_text};
}}

QTreeView::branch {{ background: transparent; }}

QHeaderView::section {{
    background: {surface};
    color: {text_muted};
    border: none;
    border-bottom: 1px solid {border};
    padding: {s_sm}px {s_sm}px;
    font-size: {t_label}px;
    font-weight: {w_semibold};
    letter-spacing: {tracking};
    text-transform: uppercase;
}}
QHeaderView::section:hover {{ color: {text_secondary}; }}
QTableView {{ gridline-color: {divider}; }}
QTableCornerButton::section {{ background: {surface}; border: none; }}

/* ==================================================================
   Scroll areas and bars
   ================================================================== */

QScrollArea {{ border: none; background: transparent; }}
QAbstractScrollArea {{ background: transparent; }}

QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {scrollbar};
    border-radius: 5px;
    min-height: 32px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {scrollbar_hover}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {scrollbar};
    border-radius: 5px;
    min-width: 32px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: {scrollbar_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ==================================================================
   Menus
   ================================================================== */

QMenu {{
    background: {elevated};
    border: 1px solid {border_strong};
    border-radius: {r_md}px;
    padding: {s_xs}px;
    color: {text};
}}
QMenu::item {{
    padding: 6px {s_lg}px 6px {s_md}px;
    border-radius: {r_xs}px;
    min-width: 168px;
    color: {text};
}}
QMenu::item:selected {{ background: {hover}; }}
QMenu::item:disabled {{ color: {text_muted}; }}
QMenu::separator {{
    height: 1px;
    background: {divider};
    margin: {s_xs}px {s_sm}px;
}}
QMenu::icon {{ padding-left: {s_sm}px; }}

QMenuBar {{ background: {sidebar}; color: {text_secondary}; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; border-radius: {r_xs}px; }}
QMenuBar::item:selected {{ background: {hover}; color: {text}; }}

/* ==================================================================
   Progress
   ================================================================== */

QProgressBar {{
    background: {inset};
    border: none;
    border-radius: 2px;
    height: 4px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 2px;
}}
QProgressBar[state="processing"]::chunk {{ background: {warning}; }}
QProgressBar[state="complete"]::chunk   {{ background: {success}; }}
QProgressBar[state="failed"]::chunk     {{ background: {danger}; }}
QProgressBar[state="paused"]::chunk     {{ background: {text_muted}; }}

/* ==================================================================
   Tabs
   ================================================================== */

QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent;
    color: {text_secondary};
    border: none;
    border-bottom: 2px solid transparent;
    padding: {s_sm}px {s_md}px;
    margin-right: {s_md}px;
    font-size: {t_body}px;
    font-weight: {w_medium};
}}
QTabBar::tab:hover {{ color: {text}; }}
QTabBar::tab:selected {{
    color: {text};
    border-bottom-color: {accent};
    font-weight: {w_semibold};
}}

/* ==================================================================
   Sliders
   ================================================================== */

QSlider::groove:horizontal {{
    height: 3px;
    background: {border_strong};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {text};
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{ background: {accent}; }}
QSlider::groove:vertical {{ width: 3px; background: {border_strong}; border-radius: 2px; }}

/* ==================================================================
   Splitter
   ================================================================== */

QSplitter::handle {{ background: {border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background: {accent}; }}

/* ==================================================================
   Named Mediary components
   ================================================================== */

/* -- Sidebar navigation ------------------------------------------- */

#SidebarBrand {{
    color: {text};
    font-size: {t_large}px;
    font-weight: {w_bold};
    letter-spacing: -0.01em;
}}

#NavItem {{
    background: transparent;
    border: none;
    border-radius: {r_sm}px;
    padding: 0 {s_sm}px;
    text-align: left;
    color: {text_secondary};
    font-size: {t_body}px;
    font-weight: {w_medium};
    min-height: 30px;
}}
#NavItem:hover {{ background: {hover}; color: {text}; }}
#NavItem:checked {{ background: {selected}; color: {selected_text}; font-weight: {w_semibold}; }}

#NavCount {{
    color: {text_muted};
    font-size: {t_small}px;
}}

/* -- Cards --------------------------------------------------------- */

#MediaCard {{
    background: {elevated};
    border: 1px solid {border};
    border-radius: {r_lg}px;
}}
#MediaCard:hover {{
    background: {hover};
    border-color: {border_strong};
}}
#MediaCard[selected="true"] {{
    border-color: {accent};
    background: {selected};
}}
#MediaCard[playing="true"] {{
    border-color: {accent};
}}

#Thumbnail {{
    background: {thumb_bg};
    border-radius: {r_md}px;
}}

/* -- Rows ---------------------------------------------------------- */

#MediaRow, #QueueRow {{
    background: transparent;
    border-bottom: 1px solid {divider};
    border-left: 2px solid transparent;
}}
#MediaRow:hover, #QueueRow:hover {{ background: {hover}; }}
#MediaRow[selected="true"] {{
    background: {selected};
    border-left-color: {accent};
}}
/* The row currently being auditioned stays marked even after focus moves. */
#MediaRow[playing="true"] {{
    background: {accent_soft};
    border-left-color: {accent};
}}

/* -- Preview dock --------------------------------------------------- */

#PreviewBar {{
    background: {elevated};
    border-top: 1px solid {border_strong};
}}

/* -- Chips and badges ---------------------------------------------- */

#Chip {{
    background: {inset};
    border: 1px solid {border};
    border-radius: {r_sm}px;
    padding: 3px {s_sm}px;
    color: {text_secondary};
    font-size: {t_small}px;
    font-weight: {w_medium};
}}
#Chip:hover {{ background: {hover}; color: {text}; border-color: {border_strong}; }}
#Chip[active="true"] {{
    background: {accent_soft};
    border-color: {accent};
    color: {accent};
    font-weight: {w_semibold};
}}

#Badge {{
    background: {inset};
    border: 1px solid {border};
    border-radius: {r_xs}px;
    padding: 1px 6px;
    color: {text_secondary};
    font-size: {t_micro}px;
    font-weight: {w_semibold};
    letter-spacing: 0.04em;
}}
#Badge[tone="accent"]  {{ background: {accent_soft};  color: {accent};  border-color: transparent; }}
#Badge[tone="success"] {{ background: {success_soft}; color: {success}; border-color: transparent; }}
#Badge[tone="warning"] {{ background: {warning_soft}; color: {warning}; border-color: transparent; }}
#Badge[tone="danger"]  {{ background: {danger_soft};  color: {danger};  border-color: transparent; }}

#TagChip {{
    background: {accent_soft};
    border: none;
    border-radius: {r_xs}px;
    padding: 2px {s_sm}px;
    color: {accent};
    font-size: {t_small}px;
    font-weight: {w_medium};
}}

/* -- Toolbar ------------------------------------------------------- */

#Toolbar {{
    background: {surface};
    border-bottom: 1px solid {border};
}}

#SegmentedControl {{
    background: {inset};
    border: 1px solid {border};
    border-radius: {r_sm}px;
    padding: 2px;
}}
#SegmentButton {{
    background: transparent;
    border: none;
    border-radius: {r_xs}px;
    padding: 0 {s_sm}px;
    min-height: 24px;
    color: {text_secondary};
    font-size: {t_small}px;
    font-weight: {w_medium};
}}
#SegmentButton:hover {{ color: {text}; }}
#SegmentButton:checked {{
    background: {elevated};
    color: {text};
    font-weight: {w_semibold};
}}

/* -- Empty states -------------------------------------------------- */

#EmptyState {{ background: transparent; }}
#EmptyStateIcon {{
    background: {inset};
    border: 1px solid {border};
    border-radius: {r_xl}px;
}}

/* -- Detail inspector ---------------------------------------------- */

#Inspector {{
    background: {sidebar};
    border-left: 1px solid {border};
}}
#InspectorSection {{
    background: transparent;
    border: none;
    border-top: 1px solid {divider};
    text-align: left;
    padding: {s_md}px 0 {s_sm}px 0;
    color: {text_muted};
    font-size: {t_label}px;
    font-weight: {w_semibold};
    letter-spacing: {tracking};
}}
#InspectorSection:hover {{ color: {text_secondary}; }}

#PreviewCanvas {{
    background: {thumb_bg};
    border: none;
}}

/* -- Notices ------------------------------------------------------- */

#Notice {{
    background: {inset};
    border: 1px solid {border};
    border-left: 3px solid {text_muted};
    border-radius: {r_sm}px;
    padding: {s_md}px;
}}
#Notice[tone="info"]    {{ border-left-color: {accent}; }}
#Notice[tone="success"] {{ border-left-color: {success}; }}
#Notice[tone="warning"] {{ border-left-color: {warning}; }}
#Notice[tone="danger"]  {{ border-left-color: {danger}; }}

#Toast {{
    background: {elevated};
    border: 1px solid {border_strong};
    border-radius: {r_md}px;
}}

/* -- Settings ------------------------------------------------------ */

#SettingsGroup {{
    background: {elevated};
    border: 1px solid {border};
    border-radius: {r_lg}px;
}}
#SettingRow {{
    background: transparent;
    border-bottom: 1px solid {divider};
}}
#SettingRow[last="true"] {{ border-bottom: none; }}

/* -- Onboarding ---------------------------------------------------- */

#OnboardingPane {{ background: {surface}; }}
#OnboardingSide {{
    background: {sidebar};
    border-right: 1px solid {border};
}}
#StepDot {{
    background: {border_strong};
    border-radius: 3px;
    min-width: 6px; max-width: 6px;
    min-height: 6px; max-height: 6px;
}}
#StepDot[active="true"] {{ background: {accent}; }}
"""
