"""Panels you can move, tab together, undock, close and open again, and workspaces that
remember how they are laid out, the way Adobe Premiere Pro does it:

  * every part of the window is a panel with its name in a tab at the top;
  * drag a tab onto another panel to put them together, onto the edge of one to split it, or
    out of the window to float it;
  * the menu beside the name (or a right click on a tab) closes, undocks or maximises a panel,
    and so does a double click (maximise) or the ` key;
  * a workspace is a named layout. Changes to it are remembered, Reset goes back to how it
    was saved, and any layout can be saved as a workspace of its own.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QByteArray, QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QDockWidget, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QListWidget, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy, QTabBar, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)
from shiboken6 import getCppPointer, isValid

from . import theme

LAYOUT_VERSION = 1          # bumped when the panels change, so old layouts are not restored

# key, name on the tab, what the panel is for
PANELS = (
    ("outputs", "Outputs", "Your sound outputs and their speakers. Tick an output to use it."),
    ("room", "Room", "Where every speaker sits around you"),
    ("now", "Now playing", "What the PC is playing"),
    ("speaker", "Speaker", "The selected speaker: its role, level, delay and sound"),
    ("output", "Output", "The selected output: its device, channels and timing"),
    ("sound", "Sound", "Upmixing, bass and the sound of all speakers together"),
    ("lights", "Lights", "RGB lights that follow the sound"),
    ("effects", "Effects", "SimHub, bass shakers and extra sound sources"),
    ("tones", "Tone generator", "Tones from 1 Hz to 20,000 Hz, beeps and patterns"),
    ("fun", "Fun", "Sound effects for everything the PC plays"),
    ("errors", "Errors", "Anything that keeps the sound from your speakers"),
    ("controls", "Controls", "Keys, controllers and Stream Deck links for actions"),
    ("settings", "Settings", "How SpeakerWeave starts, looks and behaves"),
    ("performance", "Performance", "Processor, memory and how well the sound keeps up"),
)
TITLES = {key: title for key, title, _ in PANELS}

INSPECTOR = ("speaker", "output", "sound", "lights", "effects")

# A layout is a tree. A leaf is a tuple of panel keys tabbed together (the first in front). A
# split is ("h", [(weight, node), ...]) for side by side or ("v", ...) for one above the
# other. Panels a workspace leaves out are closed, and open next to the Room when asked for.
BUILT_IN = {
    "Setup": ("h", [(22, ("v", [(5, ("outputs",)), (1, ("now",))])),
                    (48, ("room",)),
                    (30, INSPECTOR)]),
    "Tune": ("h", [(24, ("v", [(3, ("outputs",)), (2, ("output", "lights"))])),
                   (46, ("room",)),
                   (30, ("v", [(1, ("speaker",)), (1, ("sound", "effects", "tones"))]))]),
    "Play": ("h", [(62, ("v", [(9, ("room",)), (1, ("now",))])),
                   (38, ("fun", "effects", "tones"))]),
    "Classic": ("v", [(12, ("h", [(19, ("outputs",)), (50, ("room",)), (31, INSPECTOR)])),
                      (1, ("now",))]),
}
DEFAULT_WORKSPACE = "Setup"
WORKSPACE_TIPS = {
    "Setup": "Outputs, the room and the selected speaker side by side: for setting up",
    "Tune": "The selected speaker and the sound next to the room: for timing and levels",
    "Play": "The room, Fun and Now playing: while you play or watch",
    "Classic": "The layout SpeakerWeave had before panels",
}
HOME = "room"               # closed panels open as a tab beside this one
GROWS_ACROSS = ("room", "now", "fun", "settings", "controls", "errors", "performance")
STAYS_LOW = ("now",)


class WorkspaceStore:
    """The workspaces, kept in workspaces.json beside the settings: the one in use, the ones
    you saved, and every workspace's layout as saved and as last left."""

    def __init__(self, path: str = ""):
        self.path = path
        self.workspace = DEFAULT_WORKSPACE
        self.workspace_custom: list = []        # names of the workspaces you saved, in order
        self.workspace_saved: dict = {}         # name -> its layout as saved
        self.workspace_layouts: dict = {}       # name -> its layout as last left

    @staticmethod
    def load(path: str) -> "WorkspaceStore":
        store = WorkspaceStore(path)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return store
        if not isinstance(data, dict):
            return store
        name = data.get("workspace")
        if isinstance(name, str) and name.strip():
            store.workspace = name
        custom = data.get("custom")
        if isinstance(custom, list):
            store.workspace_custom = list(dict.fromkeys(
                str(n) for n in custom if isinstance(n, str) and n.strip() and n not in BUILT_IN))[:30]
        for key, attr in (("saved", "workspace_saved"), ("layouts", "workspace_layouts")):
            value = data.get(key)
            if isinstance(value, dict):
                setattr(store, attr, {str(k): v for k, v in value.items() if isinstance(v, str)})
        return store

    def save(self) -> None:
        if not self.path:
            return
        data = {"workspace": self.workspace, "custom": self.workspace_custom,
                "saved": self.workspace_saved, "layouts": self.workspace_layouts}
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass


def _encode(data: QByteArray) -> str:
    return bytes(data.toBase64()).decode("ascii")


def _decode(text: str) -> QByteArray:
    return QByteArray.fromBase64(str(text or "").encode("ascii"))


def _leaves(node):
    if isinstance(node, tuple) and node and node[0] in ("h", "v") and isinstance(node[1], list):
        for _weight, child in node[1]:
            yield from _leaves(child)
    else:
        yield node


def layout_keys(node) -> list:
    return [key for leaf in _leaves(node) for key in leaf]


# ------------------------------------------------------------------ small drawn icons
def menu_icon(color: str = None, size: int = 14) -> QIcon:
    """Three short lines: the panel menu, as in Premiere."""
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2.0)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color or theme.DIM), 1.4, Qt.SolidLine, Qt.RoundCap))
    for y in (4.5, 7.0, 9.5):
        p.drawLine(QPointF(3.5, y), QPointF(size - 3.5, y))
    p.end()
    return QIcon(pix)


def pin_icon(pinned: bool, color: str = None, size: int = 16) -> QIcon:
    """A drawing pin: upright when pinned, lying over when not."""
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2.0)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color or theme.DIM)
    p.translate(size / 2, size / 2)
    if not pinned:
        p.rotate(-90)
    p.translate(-size / 2, -size / 2)
    p.setPen(QPen(c, 1.3))
    p.setBrush(c if pinned else Qt.NoBrush)
    head = QPainterPath()
    head.addRoundedRect(QRectF(5.5, 2.0, 5.0, 6.0), 1.0, 1.0)
    p.drawPath(head)
    p.drawLine(QPointF(3.5, 8.5), QPointF(12.5, 8.5))
    p.setPen(QPen(c, 1.3, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(8.0, 8.5), QPointF(8.0, 14.0))
    p.end()
    return QIcon(pix)


def _menu_button(on_click) -> QToolButton:
    button = QToolButton()
    button.setObjectName("panelMenu")
    button.setIcon(menu_icon())
    button.setIconSize(QSize(14, 14))
    button.setAutoRaise(True)
    button.setCursor(Qt.ArrowCursor)
    button.setFocusPolicy(Qt.NoFocus)
    button.setToolTip("Panel menu: close, undock or maximise this panel")
    button.clicked.connect(on_click)
    return button


# ------------------------------------------------------------------ one panel
class PanelHeader(QWidget):
    """The name of a panel on its own, drawn like a tab, with the panel menu beside it.
    Dragging it moves the panel (the dock handles the mouse presses this lets through)."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setObjectName("panelHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(28)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(0)
        self.title = QLabel(panel.windowTitle())
        self.title.setObjectName("panelTitle")
        row.addWidget(self.title)
        self.menu_btn = _menu_button(lambda: panel.manager.show_panel_menu(panel, self.menu_btn))
        row.addWidget(self.menu_btn)
        row.addStretch(1)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.panel.manager.toggle_maximised(self.panel)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.panel.manager.show_panel_menu(self.panel, None, event.globalPos())


class Panel(QDockWidget):
    def restyle(self) -> None:
        # what a scrolling area holds fills itself with the window colour: inside a panel
        # the panel's own colour shows instead
        for area in self.body.findChildren(QScrollArea):
            area.viewport().setAutoFillBackground(False)
            if area.widget() is not None:
                area.widget().setAutoFillBackground(False)
        self.header.menu_btn.setIcon(menu_icon())

    def __init__(self, manager, key: str, title: str, tip: str, widget: QWidget, scroll: bool):
        super().__init__(title)
        self.manager = manager
        self.key = key
        self.content = widget
        self.setObjectName("panel_" + key)
        self.setToolTip("")
        self.setWhatsThis(tip)
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)
        body = QFrame()
        body.setObjectName("panelBody")
        self.body = body
        col = QVBoxLayout(body)
        col.setContentsMargins(6, 6, 6, 6)
        col.setSpacing(0)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            area.setWidget(widget)
            self.scroll = area
            col.addWidget(area)
        else:
            self.scroll = None
            col.addWidget(widget)
        self.setWidget(body)
        self.header = PanelHeader(self)
        self.blank = QWidget()                      # no header while the panel is in a tab group
        self.blank.setFixedHeight(0)
        self.setTitleBarWidget(self.header)
        # a bigger window goes to the room map first; Now playing stays a strip
        across = QSizePolicy.Expanding if key in GROWS_ACROSS else QSizePolicy.Preferred
        down = QSizePolicy.Preferred if key in STAYS_LOW else QSizePolicy.Expanding
        self.setSizePolicy(across, down)
        self.restyle()
        # a title the panel shows itself is said by the tab already
        for label in widget.findChildren(QLabel, "title"):
            if label.text().strip().lower() == title.lower():
                label.hide()


# ------------------------------------------------------------------ the workspaces
class Workspaces(QObject):
    """All panels of one window, and the workspaces that lay them out."""
    changed = Signal()                  # the list of workspaces, or the one in use, changed
    panelShown = Signal(str)            # a panel came to the front of its group
    refreshed = Signal()                # panels were moved, opened, closed or brought forward

    def __init__(self, host: QMainWindow, path: str = ""):
        super().__init__(host)
        self.host = host
        self.settings = WorkspaceStore.load(path) if path else WorkspaceStore()
        self._save = self.settings.save
        self.panels: dict[str, Panel] = {}
        self._max_state = None          # the layout before a panel was maximised
        self._max_panel = None
        self._sizes = []                # splits to size once the window has its size
        self._refresh_due = False
        self._hooked: set = set()
        self._remember_timer = QTimer(self)
        self._remember_timer.setSingleShot(True)
        self._remember_timer.setInterval(1500)
        self._remember_timer.timeout.connect(self.remember)
        host.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks
                            | QMainWindow.AllowTabbedDocks | QMainWindow.GroupedDragging)
        host.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        host.setDocumentMode(True)
        host.tabifiedDockWidgetActivated.connect(lambda _d: self._changed())

    # ---------------------------------------------------------- panels
    def add(self, key: str, widget: QWidget, scroll: bool = False) -> Panel:
        title, tip = next((t, tip) for k, t, tip in PANELS if k == key)
        panel = Panel(self, key, title, tip, widget, scroll)
        self.panels[key] = panel
        panel.topLevelChanged.connect(lambda _f: self._changed())
        panel.dockLocationChanged.connect(lambda _a: self._changed())
        panel.visibilityChanged.connect(lambda on, p=panel: self._visibility(p, on))
        self.host.addDockWidget(Qt.LeftDockWidgetArea, panel)
        panel.hide()
        return panel

    def panel(self, key: str):
        return self.panels.get(key)

    def is_open(self, key: str) -> bool:
        panel = self.panels.get(key)
        return panel is not None and not panel.isHidden()

    def in_front(self, key: str) -> bool:
        """Open and not hidden behind another tab of its group."""
        panel = self.panels.get(key)
        if panel is None or panel.isHidden():
            return False
        if panel.isFloating():
            return True
        found = self._tab_of(panel)
        if found is None:
            return True
        bar, index = found
        return bar.currentIndex() == index

    def open(self, key: str) -> Panel:
        """Shows a panel where it was last, in front of its group. A panel that was never
        placed opens as a tab beside the room."""
        panel = self.panels.get(key)
        if panel is None:
            return None
        if self._max_state is not None and panel is not self._max_panel:
            self.restore_maximised()
        if panel.isHidden():
            if self.host.dockWidgetArea(panel) == Qt.NoDockWidgetArea and not panel.isFloating():
                home = self.panels.get(HOME)
                if home is not None and home is not panel and not home.isFloating():
                    self.host.tabifyDockWidget(home, panel)
                else:
                    self.host.addDockWidget(Qt.RightDockWidgetArea, panel)
            panel.show()
        panel.raise_()
        self._changed()
        return panel

    def close_panel(self, key: str) -> None:
        panel = self.panels.get(key)
        if panel is not None:
            panel.close()

    def toggle(self, key: str, on: bool) -> None:
        if on:
            self.open(key)
        else:
            self.close_panel(key)

    def undock(self, panel: Panel) -> None:
        size = panel.size()
        panel.setFloating(True)
        panel.resize(max(360, size.width()), max(300, size.height()))
        pos = QCursor.pos()
        panel.move(pos.x() - 40, pos.y() - 12)

    def close_others(self, panel: Panel) -> None:
        for other in self.host.tabifiedDockWidgets(panel):
            if not other.isHidden():
                other.close()

    def panel_at_cursor(self):
        widget = QApplication.widgetAt(QCursor.pos()) or QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, Panel) and widget.manager is self:
                return widget
            if isinstance(widget, QTabBar) and self._is_dock_bar(widget):
                index = widget.tabAt(widget.mapFromGlobal(QCursor.pos()))
                return self._panel_of(widget, index)
            widget = widget.parentWidget()
        return None

    # ---------------------------------------------------------- maximising
    @property
    def maximised(self):
        return self._max_panel

    def toggle_maximised(self, panel=None) -> None:
        if self._max_state is not None:
            self.restore_maximised()
            return
        panel = panel or self.panel_at_cursor()
        if panel is None or panel.isFloating() or panel.isHidden():
            return
        self._max_state = self.host.saveState(LAYOUT_VERSION)
        self._max_panel = panel
        for other in self.panels.values():
            if other is not panel and not other.isHidden() and not other.isFloating():
                other.hide()
        panel.raise_()
        self._changed()

    def restore_maximised(self) -> None:
        state, self._max_state, self._max_panel = self._max_state, None, None
        if state is not None:
            self.host.restoreState(state, LAYOUT_VERSION)
        self._changed()

    # ---------------------------------------------------------- the panel menu
    def panel_menu(self, panel: Panel, menu: QMenu = None) -> QMenu:
        menu = menu or QMenu(self.host)
        menu.addAction("Close panel", panel.close)
        if panel.isFloating():
            menu.addAction("Dock panel", lambda: panel.setFloating(False))
        else:
            menu.addAction("Undock panel", lambda: self.undock(panel))
        others = [o for o in self.host.tabifiedDockWidgets(panel) if not o.isHidden()]
        action = menu.addAction("Close other panels in group", lambda: self.close_others(panel))
        action.setEnabled(bool(others) and not panel.isFloating())
        menu.addSeparator()
        if self._max_state is not None:
            action = menu.addAction("Restore panel size", self.restore_maximised)
        else:
            action = menu.addAction("Maximise panel", lambda: self.toggle_maximised(panel))
            action.setEnabled(not panel.isFloating())
        action.setShortcut("`")
        return menu

    def show_panel_menu(self, panel: Panel, button=None, at=None) -> None:
        menu = self.panel_menu(panel)
        if at is None:
            anchor = button if button is not None and isValid(button) else panel
            at = anchor.mapToGlobal(anchor.rect().bottomLeft())
        menu.exec(at)
        menu.deleteLater()

    # ---------------------------------------------------------- tabs and headers
    def _changed(self) -> None:
        if not self._refresh_due:
            self._refresh_due = True
            QTimer.singleShot(0, self._refresh)
        if self._max_state is None:
            self._remember_timer.start()

    def _visibility(self, panel: Panel, on: bool) -> None:
        self._changed()
        if on:
            self.panelShown.emit(panel.key)

    def _is_dock_bar(self, bar) -> bool:
        parent = bar.parent()
        return parent is self.host or (parent is not None
                                       and parent.metaObject().className() == "QDockWidgetGroupWindow"
                                       and parent.parent() is self.host)

    def _bars(self) -> list:
        return [bar for bar in self.host.findChildren(QTabBar)
                if self._is_dock_bar(bar) and not bar.isHidden() and bar.count()]

    def _panel_of(self, bar, index: int):
        if index < 0 or index >= bar.count():
            return None
        data = bar.tabData(index)
        for panel in self.panels.values():
            if getCppPointer(panel)[0] == data:
                return panel
        return None

    def _tab_of(self, panel: Panel):
        """The tab bar and tab of a panel in a group of two or more (Qt can leave an unused
        bar behind with one tab: a panel on its own has no tab)."""
        pointer = getCppPointer(panel)[0]
        found = None
        for bar in self._bars():
            if bar.count() < 2:
                continue
            for i in range(bar.count()):
                if bar.tabData(i) == pointer and (found is None or bar.count() > found[0].count()):
                    found = (bar, i)
        return found

    def _tab_menu(self, bar, button) -> None:
        for i in range(bar.count()):
            if bar.tabButton(i, QTabBar.RightSide) is button:
                panel = self._panel_of(bar, i)
                if panel is not None:
                    self.show_panel_menu(panel, button)
                return

    def _refresh(self) -> None:
        self._refresh_due = False
        if not isValid(self.host):
            return
        for panel in self.panels.values():
            tabbed = not panel.isFloating() and any(
                not other.isHidden() for other in self.host.tabifiedDockWidgets(panel))
            want = panel.blank if tabbed else panel.header
            if panel.titleBarWidget() is not want:
                panel.setTitleBarWidget(want)
        for bar in self._bars():
            if bar.count() < 2:
                continue
            key = getCppPointer(bar)[0]
            if key not in self._hooked:
                self._hooked.add(key)
                bar.setExpanding(False)
                bar.setElideMode(Qt.ElideRight)
                bar.installEventFilter(self)
                bar.currentChanged.connect(lambda _i: self._changed())
                bar.destroyed.connect(lambda _o=None, k=key: self._hooked.discard(k))
            current = bar.currentIndex()
            for i in range(bar.count()):
                button = bar.tabButton(i, QTabBar.RightSide)
                if i == current and button is None:
                    made = _menu_button(lambda _c=False, b=bar: None)
                    made.clicked.disconnect()
                    made.clicked.connect(lambda _c=False, b=bar, m=made: self._tab_menu(b, m))
                    bar.setTabButton(i, QTabBar.RightSide, made)
                elif i != current and button is not None:
                    bar.setTabButton(i, QTabBar.RightSide, None)
                    button.deleteLater()
        self.refreshed.emit()

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.ContextMenu and isinstance(obj, QTabBar):
            panel = self._panel_of(obj, obj.tabAt(event.pos()))
            if panel is not None:
                self.show_panel_menu(panel, None, event.globalPos())
                return True
        elif kind == QEvent.MouseButtonDblClick and isinstance(obj, QTabBar):
            panel = self._panel_of(obj, obj.tabAt(event.position().toPoint()))
            if panel is not None:
                self.toggle_maximised(panel)
                return True
        return super().eventFilter(obj, event)

    def restyle(self) -> None:
        icon = menu_icon()
        for panel in self.panels.values():
            panel.restyle()
        for bar in self._bars():
            for i in range(bar.count()):
                button = bar.tabButton(i, QTabBar.RightSide)
                if isinstance(button, QToolButton):
                    button.setIcon(icon)

    # ---------------------------------------------------------- building a layout
    def arrange(self, tree) -> None:
        """Lays the panels out as the tree says. The rest are closed, placed beside the room."""
        host = self.host
        self._max_state = self._max_panel = None
        for panel in self.panels.values():
            if panel.isFloating():
                panel.setFloating(False)
            host.removeDockWidget(panel)
        placed = [key for key in layout_keys(tree) if key in self.panels]
        tree = self._only(tree, set(placed))
        self._sizes = []
        if tree is None:
            return
        first = self.panels[next(iter(_leaves(tree)))[0]]
        host.addDockWidget(Qt.LeftDockWidgetArea, first)
        first.show()
        self._build(tree)
        fronts = [self.panels[leaf[0]] for leaf in _leaves(tree)]
        home = self.panels.get(HOME) if HOME in placed else first
        for key, panel in self.panels.items():
            if key not in placed:
                host.tabifyDockWidget(home, panel)
                panel.hide()
        for panel in fronts:
            panel.raise_()
        self.apply_sizes()
        self._changed()

    def _only(self, node, keep: set):
        """The tree without the panels this window does not have."""
        if isinstance(node, tuple) and node and node[0] in ("h", "v") and isinstance(node[1], list):
            kids = [(w, self._only(child, keep)) for w, child in node[1]]
            kids = [(w, child) for w, child in kids if child is not None]
            if not kids:
                return None
            return kids[0][1] if len(kids) == 1 else (node[0], kids)
        leaf = tuple(key for key in node if key in keep)
        return leaf or None

    def _first(self, node) -> Panel:
        return self.panels[next(iter(_leaves(node)))[0]]

    def _build(self, node) -> None:
        host = self.host
        if node and node[0] in ("h", "v") and isinstance(node[1], list):
            orient = Qt.Horizontal if node[0] == "h" else Qt.Vertical
            kids = node[1]
            for (_w, before), (_w2, child) in zip(kids, kids[1:]):
                panel = self._first(child)
                host.splitDockWidget(self._first(before), panel, orient)
                panel.show()
            self._sizes.append(([self._first(child) for _w, child in kids], [w for w, _c in kids], orient))
            for _w, child in kids:
                self._build(child)
            return
        anchor = self.panels[node[0]]
        for key in node[1:]:
            host.tabifyDockWidget(anchor, self.panels[key])
            self.panels[key].show()

    def apply_sizes(self) -> None:
        """Gives the splits of a fresh layout their proportions (only possible once the
        window has a size, so it runs again when the window first shows)."""
        width = max(400, self.host.width())
        height = max(300, self.host.height())
        for docks, weights, orient in self._sizes:
            total = float(sum(weights)) or 1.0
            span = width if orient == Qt.Horizontal else height
            self.host.resizeDocks(docks, [max(60, int(span * w / total)) for w in weights], orient)

    def shown(self) -> None:
        """The window is on screen with its real size."""
        if self._sizes:
            self.apply_sizes()
            QTimer.singleShot(0, self._sized)

    def _sized(self) -> None:
        self.apply_sizes()
        self._sizes = []

    # ---------------------------------------------------------- workspaces
    def names(self) -> list:
        return list(BUILT_IN) + [n for n in self.settings.workspace_custom if n not in BUILT_IN]

    @property
    def current(self) -> str:
        name = self.settings.workspace
        return name if name in self.names() else DEFAULT_WORKSPACE

    def state(self) -> QByteArray:
        return self._max_state if self._max_state is not None else self.host.saveState(LAYOUT_VERSION)

    def remember(self) -> None:
        """Keeps the layout as it is now for the workspace in use."""
        self._remember_timer.stop()
        self.settings.workspace_layouts[self.current] = _encode(self.state())
        self._save()

    def start(self) -> None:
        """Lays the window out as it was left."""
        name = self.current
        self.settings.workspace = name
        kept = self.settings.workspace_layouts.get(name)
        if not (kept and self._restore(kept)):
            self._lay_out_saved(name)

    def _restore(self, text: str) -> bool:
        for panel in self.panels.values():
            panel.hide()
        ok = self.host.restoreState(_decode(text), LAYOUT_VERSION)
        self._sizes = []
        self._changed()
        return bool(ok)

    def _lay_out_saved(self, name: str) -> None:
        saved = self.settings.workspace_saved.get(name)
        if saved and self._restore(saved):
            return
        self.arrange(BUILT_IN.get(name, BUILT_IN[DEFAULT_WORKSPACE]))

    def switch(self, name: str) -> None:
        if name not in self.names():
            return
        if self._max_state is not None:
            self.restore_maximised()
        if name != self.current:
            self.remember()
        self.settings.workspace = name
        kept = self.settings.workspace_layouts.get(name)
        if not (kept and self._restore(kept)):
            self._lay_out_saved(name)
        self.remember()
        self.changed.emit()

    def reset(self) -> None:
        """Back to the layout as the workspace was saved."""
        if self._max_state is not None:
            self.restore_maximised()
        self._lay_out_saved(self.current)
        self.remember()
        self.changed.emit()

    def original(self) -> None:
        """A built in workspace back to how SpeakerWeave first laid it out."""
        name = self.current
        self.settings.workspace_saved.pop(name, None)
        self.arrange(BUILT_IN.get(name, BUILT_IN[DEFAULT_WORKSPACE]))
        self.remember()
        self.changed.emit()

    def save_changes(self) -> None:
        if self._max_state is not None:
            self.restore_maximised()
        self.settings.workspace_saved[self.current] = _encode(self.state())
        self.remember()

    def save_as(self, name: str) -> bool:
        name = " ".join(str(name or "").split())[:40]
        if not name or name in self.names():
            return False
        if self._max_state is not None:
            self.restore_maximised()
        self.remember()
        state = _encode(self.state())
        self.settings.workspace_custom.append(name)
        self.settings.workspace_saved[name] = state
        self.settings.workspace_layouts[name] = state
        self.settings.workspace = name
        self._save()
        self.changed.emit()
        return True

    def rename(self, old: str, new: str) -> bool:
        new = " ".join(str(new or "").split())[:40]
        if old in BUILT_IN or old not in self.names() or not new or new in self.names():
            return False
        s = self.settings
        s.workspace_custom = [new if n == old else n for n in s.workspace_custom]
        for store in (s.workspace_saved, s.workspace_layouts):
            if old in store:
                store[new] = store.pop(old)
        if s.workspace == old:
            s.workspace = new
        self._save()
        self.changed.emit()
        return True

    def delete(self, name: str) -> bool:
        if name in BUILT_IN or name not in self.names():
            return False
        s = self.settings
        s.workspace_custom = [n for n in s.workspace_custom if n != name]
        s.workspace_saved.pop(name, None)
        s.workspace_layouts.pop(name, None)
        if s.workspace == name:
            s.workspace = DEFAULT_WORKSPACE
            kept = s.workspace_layouts.get(DEFAULT_WORKSPACE)
            if not (kept and self._restore(kept)):
                self._lay_out_saved(DEFAULT_WORKSPACE)
        self._save()
        self.changed.emit()
        return True

    # ---------------------------------------------------------- menus
    def fill_workspace_menu(self, menu: QMenu, parent: QWidget) -> None:
        menu.clear()
        for name in self.names():
            action = menu.addAction(name, lambda n=name: self.switch(n))
            action.setCheckable(True)
            action.setChecked(name == self.current)
            if name in WORKSPACE_TIPS:
                action.setToolTip(WORKSPACE_TIPS[name])
        menu.addSeparator()
        menu.addAction("Reset to saved layout", self.reset)
        menu.addAction("Save changes to this workspace", self.save_changes)
        if self.current in BUILT_IN and self.current in self.settings.workspace_saved:
            menu.addAction("Back to the original layout", self.original)
        menu.addAction("Save as new workspace...", lambda: self.ask_save_as(parent))
        edit = menu.addAction("Edit workspaces...", lambda: EditWorkspaces(self, parent).exec())
        edit.setEnabled(bool(self.settings.workspace_custom))

    def fill_panel_menu(self, menu: QMenu) -> None:
        for key, title, tip in PANELS:
            panel = self.panels.get(key)
            if panel is None:
                continue
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not panel.isHidden())
            action.setToolTip(tip)
            action.toggled.connect(lambda on, k=key: self.toggle(k, on))

    def ask_save_as(self, parent: QWidget) -> None:
        name, ok = QInputDialog.getText(parent, "Save as new workspace",
                                        "A name for this layout of panels:")
        if not ok:
            return
        if not self.save_as(name):
            QMessageBox.information(parent, "Save as new workspace",
                                    "That name is empty or already used by a workspace.")


class EditWorkspaces(QDialog):
    """Renames or deletes the workspaces you made."""

    def __init__(self, workspaces: Workspaces, parent=None):
        super().__init__(parent)
        self.workspaces = workspaces
        self.setWindowTitle("Edit workspaces")
        col = QVBoxLayout(self)
        note = QLabel("The workspaces you saved. Setup, Tune, Play and Classic come with SpeakerWeave "
                      "and stay.")
        note.setObjectName("dim")
        note.setWordWrap(True)
        col.addWidget(note)
        self.list = QListWidget()
        col.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.rename_btn = QPushButton("Rename...")
        self.delete_btn = QPushButton("Delete")
        row.addWidget(self.rename_btn)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        col.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self.rename_btn.clicked.connect(self._rename)
        self.delete_btn.clicked.connect(self._delete)
        self.list.currentRowChanged.connect(lambda _r: self._enable())
        self._fill()
        self.resize(360, 300)

    def _fill(self) -> None:
        self.list.clear()
        self.list.addItems(list(self.workspaces.settings.workspace_custom))
        if self.list.count():
            self.list.setCurrentRow(0)
        self._enable()

    def _enable(self) -> None:
        on = self.list.currentItem() is not None
        self.rename_btn.setEnabled(on)
        self.delete_btn.setEnabled(on)

    def _rename(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        name, ok = QInputDialog.getText(self, "Rename workspace", "New name:", text=item.text())
        if ok and not self.workspaces.rename(item.text(), name):
            QMessageBox.information(self, "Rename workspace",
                                    "That name is empty or already used by a workspace.")
        self._fill()

    def _delete(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.workspaces.delete(item.text())
        self._fill()


class WorkspaceBar(QWidget):
    """The workspaces as tabs along the top of the window, and » for the rest of the
    workspace commands."""

    def __init__(self, workspaces: Workspaces):
        super().__init__()
        self.workspaces = workspaces
        self.setObjectName("workspaceBar")
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(0)
        self.buttons: dict[str, QToolButton] = {}
        self.more = QToolButton()
        self.more.setObjectName("workspaceMore")
        self.more.setText("»")
        self.more.setToolTip("All workspaces: reset, save, or save as new")
        self.more.setPopupMode(QToolButton.InstantPopup)
        self.more.setAutoRaise(True)
        self.more_menu = QMenu(self.more)
        self.more_menu.aboutToShow.connect(
            lambda: workspaces.fill_workspace_menu(self.more_menu, self.window()))
        self.more.setMenu(self.more_menu)
        workspaces.changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.more:
                widget.hide()
                widget.deleteLater()
        self.buttons = {}
        for name in self.workspaces.names():
            button = QToolButton()
            button.setObjectName("workspaceTab")
            button.setText(name)
            button.setCheckable(True)
            button.setChecked(name == self.workspaces.current)
            button.setAutoRaise(True)
            button.setToolTip(WORKSPACE_TIPS.get(name, "A workspace you saved"))
            button.clicked.connect(lambda _c=False, n=name: self._chosen(n))
            self.row.addWidget(button)
            self.buttons[name] = button
        self.row.addWidget(self.more)
        self.updateGeometry()
        self._fit()

    def _chosen(self, name: str) -> None:
        self.workspaces.switch(name)
        for n, button in self.buttons.items():
            button.setChecked(n == self.workspaces.current)
        self._fit()

    # on a narrow window the workspaces that do not fit wait in the » menu
    def sizeHint(self) -> QSize:
        width = sum(b.sizeHint().width() for b in self.buttons.values()) + self.more.sizeHint().width()
        return QSize(width, self.more.sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        current = self.buttons.get(self.workspaces.current)
        width = self.more.sizeHint().width() + (current.sizeHint().width() if current else 0)
        return QSize(width, self.more.sizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        room = self.width() - self.more.sizeHint().width()
        current = self.workspaces.current
        used = self.buttons[current].sizeHint().width() if current in self.buttons else 0
        for name, button in self.buttons.items():
            if name == current:
                button.setVisible(True)
                continue
            width = button.sizeHint().width()
            fits = used + width <= room
            button.setVisible(fits)
            if fits:
                used += width
