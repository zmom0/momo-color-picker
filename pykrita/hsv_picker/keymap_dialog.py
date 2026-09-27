# -*- coding: utf-8 -*-
"""「按键功能」自定义按键表（R14）。

表格三列：**区域 | 输入 | 动作**。
  · 「输入」cell 点开小编辑器：鼠标键（左/中/右）+ 修饰键（无 / Shift / Ctrl / Alt /
    Ctrl+Shift / Shift+Alt / Ctrl+Alt / Ctrl+Shift+Alt）；
  · 「动作」cell 是该区域的动作下拉（清单随区域变）；
  · 每区域末尾一行「＋ 新增输入」；底部「恢复默认」；
  · 同区域内同一「修饰键 + 鼠标键」不允许重复（拒绝并提示）；
  · 任何改动即时生效（回调宿主 `on_change` 写设置 + 灌进控件）。

数据层（区域/输入/动作清单与默认值）在 `keymap_core`，本模块只做 Qt 界面。
"""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout,
                             QHeaderView, QLabel, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout)

try:
    from . import i18n
    from . import keymap_core as kc
except ImportError:
    import i18n
    import keymap_core as kc

ROW_H = 26


def _zh():
    try:
        return bool(i18n.is_zh())
    except Exception:
        return True


class InputEditor(QDialog):
    """鼠标键 + 修饰键的小编辑器（与 Krita「画布快捷键」截图一致）。"""

    def __init__(self, parent=None, mods="none", btn="left"):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("选择输入", "Choose input"))
        self.setModal(True)
        zh = _zh()
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel(i18n.t("鼠标键", "Mouse button"), self))
        self.cmb_btn = QComboBox(self)
        for bid, lzh, len_ in kc.BUTTONS:
            self.cmb_btn.addItem(lzh if zh else len_, bid)
        row.addWidget(self.cmb_btn)
        row.addWidget(QLabel(i18n.t("修饰键", "Modifier"), self))
        self.cmb_mod = QComboBox(self)
        for mid, lzh, len_ in kc.MODS:
            self.cmb_mod.addItem(lzh if zh else len_, mid)
        row.addWidget(self.cmb_mod)
        root.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton(i18n.t("确定", "OK"), self)
        ok.clicked.connect(self.accept)
        cancel = QPushButton(i18n.t("取消", "Cancel"), self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        root.addLayout(buttons)
        for combo, value in ((self.cmb_btn, btn), (self.cmb_mod, mods)):
            idx = combo.findData(value)
            combo.setCurrentIndex(max(0, idx))

    def get_input(self):
        return (str(self.cmb_mod.currentData()), str(self.cmb_btn.currentData()))


class KeymapDialog(QDialog):
    """非模态自定义按键表；由 HsvPickerPanel 持有并复用。

    R18：打开时继承「弹出面板」的实际置顶状态（`apply_effective_top`），
    运行中切换置顶会由面板侧实时刷新窗口标志。
    """

    def __init__(self, parent=None, on_change=None):
        super().__init__(parent)
        self._on_change = on_change
        self.keymap = kc.default_keymap()
        self.setWindowTitle(i18n.t("按键功能", "Key functions"))
        self.setModal(False)
        self.setMinimumSize(660, 480)
        self.resize(720, 660)
        root = QVBoxLayout(self)
        self.lbl_hint = QLabel(i18n.t(
            "点「输入」修改鼠标键与修饰键，点「动作」下拉改功能；改完立即生效并持久化。"
            "同一区域内同一「修饰键+鼠标键」不能重复。",
            "Click Input to change the mouse button and modifier, click the Action cell to "
            "choose the function. Changes take effect and are stored immediately. The same "
            "modifier+button cannot repeat within one area."), self)
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)

        self.table = QTableWidget(self)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setWordWrap(False)
        vheader = self.table.verticalHeader()
        vheader.setVisible(False)
        vheader.setSectionResizeMode(QHeaderView.Fixed)
        vheader.setDefaultSectionSize(ROW_H)
        vheader.setMinimumSectionSize(18)
        vheader.setMaximumSectionSize(ROW_H)      # 行高固定 26px（不被单元格控件撑大）
        root.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.btn_reset = QPushButton(i18n.t("恢复默认", "Restore defaults"), self)
        self.btn_reset.clicked.connect(self._on_reset)
        bottom.addWidget(self.btn_reset)
        bottom.addStretch(1)
        root.addLayout(bottom)
        self.rebuild()

    def apply_effective_top(self, on_top):
        """R18：按弹出面板的**实际生效**置顶状态刷新本对话框窗口标志。

        只增删 `WindowStaysOnTopHint`，不动其它标志；已打开时立即重显以生效。
        """
        cur = int(self.windowFlags())
        mask = int(Qt.WindowStaysOnTopHint)
        want = (cur | mask) if on_top else (cur & ~mask)
        if want == cur:
            return
        was_visible = self.isVisible()
        self.setWindowFlags(Qt.WindowFlags(want))
        if was_visible:
            self.show()
            self.raise_()

    # ---------------------------------------------------------------- 数据 <-> 表格
    def set_keymap(self, keymap):
        """外部灌入一份表（会规范化）；不触发 on_change。"""
        self.keymap = kc.normalize(keymap)
        self.rebuild()

    def keymap_rows(self):
        """当前表的扁平行列表（自检用）：每项 (区域, 修饰键, 鼠标键, 动作)。"""
        out = []
        for area in kc.AREA_IDS:
            for mods, btn, act in self.keymap.get(area, []):
                out.append((area, mods, btn, act))
        return out

    def lookup(self, area, btn, mods):
        return kc.lookup(self.keymap, area, btn, mods)

    def rebuild(self):
        """按当前 keymap 重建整张表（含每区域的「＋ 新增输入」行）。"""
        zh = _zh()
        specs = []
        for area in kc.AREA_IDS:
            for mods, btn, act in self.keymap.get(area, []):
                specs.append((area, mods, btn, act, False))
            specs.append((area, None, None, None, True))
        self.table.clear()
        self.table.setColumnCount(3)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setRowCount(len(specs))
        self.table.setHorizontalHeaderLabels(
            [i18n.t("区域", "Area"), i18n.t("输入", "Input"), i18n.t("动作", "Action")])
        for r, (area, mods, btn, act, is_add) in enumerate(specs):
            self.table.setRowHeight(r, ROW_H)
            self.table.setItem(r, 0, QTableWidgetItem(kc.area_label(area, zh)))
            if is_add:
                add = QPushButton(i18n.t("＋ 新增输入", "+ Add input"), self.table)
                add.setFixedHeight(max(16, ROW_H - 4))
                add.clicked.connect(lambda _c=False, a=area: self._on_add(a))
                self.table.setCellWidget(r, 1, add)
                self.table.setItem(r, 2, QTableWidgetItem(""))
                continue
            pick = QPushButton(kc.input_label(mods, btn, zh), self.table)
            pick.setFixedHeight(max(16, ROW_H - 4))
            pick.clicked.connect(
                lambda _c=False, a=area, m=mods, b=btn: self._on_edit_input(a, m, b))
            self.table.setCellWidget(r, 1, pick)
            combo = QComboBox(self.table)
            combo.setFixedHeight(max(16, ROW_H - 4))
            for aid, alzh, alen in kc.ACTIONS.get(area, ()):
                combo.addItem(alzh if zh else alen, aid)
            idx = combo.findData(act)
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)
            combo.currentIndexChanged.connect(
                lambda _i, a=area, m=mods, b=btn, c=combo: self._on_action(a, m, b, c.currentData()))
            self.table.setCellWidget(r, 2, combo)


    # ---------------------------------------------------------------- 交互
    def _notify(self):
        if self._on_change is not None:
            try:
                self._on_change(self.keymap)
            except Exception:
                pass

    def _warn_duplicate(self, area, mods, btn):
        QMessageBox.warning(
            self, i18n.t("按键功能", "Key functions"),
            i18n.t("「%s」区域内「%s」已被占用，请换一个输入。",
                   "Input \"%s\" is already used in area \"%s\"; choose another.")
            % (kc.input_label(mods, btn, _zh()), kc.area_label(area, _zh())))

    def change_action(self, area, mods, btn, action):
        """把某输入的动作改成 action（表格与自检共用入口）。"""
        if kc.find_action(self.keymap, area, btn, mods) is None:
            return False
        kc.set_action(self.keymap, area, mods, btn, action)
        self.rebuild()
        self._notify()
        return True

    def add_input(self, area, mods, btn):
        """新增一行输入；已存在（同区域同输入）返回 False，不弹窗。"""
        if kc.find_action(self.keymap, area, btn, mods) is not None:
            return False
        self.keymap.setdefault(area, []).append((mods, btn, "none"))
        self.rebuild()
        self._notify()
        return True

    def reset_defaults(self):
        """恢复默认表并即时生效。"""
        self.keymap = kc.default_keymap()
        self.rebuild()
        self._notify()

    def _on_action(self, area, mods, btn, action):
        if action is None:
            return
        kc.set_action(self.keymap, area, mods, btn, action)
        self._notify()

    def _schedule_rebuild(self):
        """延到下一次事件循环再重建：避免在按钮的 clicked 信号里
        删掉正在发信号的那个单元格控件（否则可能访问已释放对象）。"""
        QTimer.singleShot(0, self.rebuild)

    def _on_add(self, area):
        editor = InputEditor(self)
        if editor.exec_() != QDialog.Accepted:
            return
        mods, btn = editor.get_input()
        if kc.find_action(self.keymap, area, btn, mods) is not None:
            self._warn_duplicate(area, mods, btn)
            return
        self.keymap.setdefault(area, []).append((mods, btn, "none"))
        self._notify()
        self._schedule_rebuild()

    def _on_edit_input(self, area, old_mods, old_btn):
        editor = InputEditor(self, mods=old_mods, btn=old_btn)
        if editor.exec_() != QDialog.Accepted:
            return
        mods, btn = editor.get_input()
        if (mods, btn) == (old_mods, old_btn):
            return
        if kc.find_action(self.keymap, area, btn, mods) is not None:
            self._warn_duplicate(area, mods, btn)
            return
        rows = self.keymap.get(area, [])
        for i, (m, b, a) in enumerate(rows):
            if (m, b) == (old_mods, old_btn):
                rows[i] = (mods, btn, a)
                break
        self._notify()
        self._schedule_rebuild()

    def _on_reset(self):
        ans = QMessageBox.question(
            self, i18n.t("恢复默认", "Restore defaults"),
            i18n.t("把所有区域的输入与动作恢复为默认值？", "Restore all areas to the default inputs and actions?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans == QMessageBox.Yes:
            self.keymap = kc.default_keymap()
            self._notify()
            self._schedule_rebuild()
