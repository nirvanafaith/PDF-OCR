"""撤销/重做命令集合。

定义纵校、横校、精修三阶段的 QUndoCommand 子类。
每个命令类只调用窗口对象的辅助方法（_apply_xxx），
实际窗口的 _apply_xxx 实现由窗口侧（Phase 3）完成。

约定：
    - 命令在被 QUndoStack.push() 调用时首次执行 redo()，
      因此窗口的 _apply_xxx 方法在命令构造时不会被调用，
      仅在 redo/undo 时调用。
    - 各命令类提供唯一 COMMAND_ID 常量，id() 返回该常量；
      mergeWith() 默认返回 False（不合并）。
"""

from PyQt5.QtWidgets import QUndoCommand


# ==================== 纵校命令 ====================


class ModifyCharCommand(QUndoCommand):
    """纵校：修改字符文本。

    将指定索引的切片文本由 old_char 改为 new_char。
    依赖窗口的 _apply_char_modify(char_index, new_char) 方法。
    """

    COMMAND_ID = 1001

    def __init__(self, vertical_window, char_index, old_char, new_char, parent=None):
        super().__init__(parent)
        self.vertical_window = vertical_window
        self.char_index = char_index
        self.old_char = old_char
        self.new_char = new_char
        self.setText(f"修改字符 '{old_char}' → '{new_char}'")

    def redo(self):
        self.vertical_window._apply_char_modify(self.char_index, self.new_char)

    def undo(self):
        self.vertical_window._apply_char_modify(self.char_index, self.old_char)

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


class DeleteSliceCommand(QUndoCommand):
    """纵校：删除切片。

    删除某字符集合下指定索引的切片，undo 时按原数据原位插回。
    依赖窗口的 _apply_delete_slice(char_text, slice_index) 与
    _apply_insert_slice(char_text, slice_index, slice_data) 方法。
    """

    COMMAND_ID = 1002

    def __init__(self, vertical_window, char_text, slice_index, slice_data, parent=None):
        super().__init__(parent)
        self.vertical_window = vertical_window
        self.char_text = char_text
        self.slice_index = slice_index
        self.slice_data = slice_data
        self.setText(f"删除切片 [{char_text}][{slice_index}]")

    def redo(self):
        self.vertical_window._apply_delete_slice(self.char_text, self.slice_index)

    def undo(self):
        self.vertical_window._apply_insert_slice(
            self.char_text, self.slice_index, self.slice_data
        )

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


class ModifyRedBoxCommand(QUndoCommand):
    """纵校：红框拖拽/缩放。

    在指定行上调整红框矩形，undo 时恢复原矩形。
    依赖窗口的 _apply_red_box(line_index, rect) 方法。
    rect 可为 QRectF/QRect 或可序列化的 [x, y, w, h]/[x1, y1, x2, y2]。
    """

    COMMAND_ID = 1003

    def __init__(self, vertical_window, line_index, old_rect, new_rect, parent=None):
        super().__init__(parent)
        self.vertical_window = vertical_window
        self.line_index = line_index
        self.old_rect = old_rect
        self.new_rect = new_rect
        self.setText("调整红框")

    def redo(self):
        self.vertical_window._apply_red_box(self.line_index, self.new_rect)

    def undo(self):
        self.vertical_window._apply_red_box(self.line_index, self.old_rect)

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


class MoveSliceCommand(QUndoCommand):
    """纵校：切片移动到新字符集合。

    将切片从 old_char_text[slice_index] 移动到 new_char_text 集合。
    首次 redo 时由窗口的 _apply_move_slice(old_char_text, slice_index, new_char_text)
    返回新位置索引并记录；undo 时按记录的新位置索引移回原字符集合。

    依赖窗口的 _apply_move_slice(src_char, src_index, dst_char) 方法，
    该方法 SHALL 返回切片在目标集合中的新索引（int）。
    """

    COMMAND_ID = 1004

    def __init__(self, vertical_window, old_char_text, slice_index, new_char_text,
                 slice_data=None, parent=None):
        super().__init__(parent)
        self.vertical_window = vertical_window
        self.old_char_text = old_char_text
        self.slice_index = slice_index
        self.new_char_text = new_char_text
        self.slice_data = slice_data  # 预留：必要时用于恢复
        # 当前在原集合中的位置：首次 redo 用初始 slice_index；
        # undo 后会被更新为切片被 append 回原集合后的新位置，供下次 redo 使用
        self._old_slice_index = slice_index
        self._new_slice_index = None  # redo 时由窗口返回并记录

        self.setText(f"移动切片 '{old_char_text}' → '{new_char_text}'")

    def redo(self):
        # 从原集合当前位置移到目标集合，记录目标集合新位置
        # 首次 redo 时 _old_slice_index 即初始 slice_index；
        # undo 后再次 redo 时 _old_slice_index 已更新为 undo 回移后的新位置
        self._new_slice_index = self.vertical_window._apply_move_slice(
            self.old_char_text, self._old_slice_index, self.new_char_text
        )

    def undo(self):
        # 从目标集合移回原集合，记录原集合新位置（通常是 append 到末尾）
        self._old_slice_index = self.vertical_window._apply_move_slice(
            self.new_char_text, self._new_slice_index, self.old_char_text
        )

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


# ==================== 横校命令 ====================


class ModifyLineTextCommand(QUndoCommand):
    """横校：修改行文本。

    将指定行索引的文本由 old_text 改为 new_text。
    依赖窗口的 _apply_modify_line_text(line_index, text) 方法。
    """

    COMMAND_ID = 2001

    def __init__(self, horizontal_window, line_index, old_text, new_text, parent=None):
        super().__init__(parent)
        self.horizontal_window = horizontal_window
        self.line_index = line_index
        self.old_text = old_text
        self.new_text = new_text
        self.setText("修改行文本")

    def redo(self):
        self.horizontal_window._apply_modify_line_text(self.line_index, self.new_text)

    def undo(self):
        self.horizontal_window._apply_modify_line_text(self.line_index, self.old_text)

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


class ToggleIgnoreCommand(QUndoCommand):
    """横校：忽略/取消忽略切换。

    切换指定行索引的忽略状态。
    依赖窗口的 _apply_toggle_ignore(line_index, ignored) 方法。
    """

    COMMAND_ID = 2002

    def __init__(self, horizontal_window, line_index, old_ignored, new_ignored, parent=None):
        super().__init__(parent)
        self.horizontal_window = horizontal_window
        self.line_index = line_index
        self.old_ignored = old_ignored
        self.new_ignored = new_ignored
        self.setText("切换忽略状态")

    def redo(self):
        self.horizontal_window._apply_toggle_ignore(self.line_index, self.new_ignored)

    def undo(self):
        self.horizontal_window._apply_toggle_ignore(self.line_index, self.old_ignored)

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


class RelocateLineFrameCommand(QUndoCommand):
    """横校：重新定位行框。

    将指定行索引的边界框由 old_box 改为 new_box。
    依赖窗口的 _apply_relocate_line(line_index, box) 方法。
    """

    COMMAND_ID = 2003

    def __init__(self, horizontal_window, line_index, old_box, new_box, parent=None):
        super().__init__(parent)
        self.horizontal_window = horizontal_window
        self.line_index = line_index
        self.old_box = old_box
        self.new_box = new_box
        self.setText("重新定位行框")

    def redo(self):
        self.horizontal_window._apply_relocate_line(self.line_index, self.new_box)

    def undo(self):
        self.horizontal_window._apply_relocate_line(self.line_index, self.old_box)

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


# ==================== 精修命令 ====================


class MoveTextItemCommand(QUndoCommand):
    """精修：移动文字项。

    将指定 item_id 的文字项位置由 old_pos 改为 new_pos。
    依赖窗口的 _apply_move_item(item_id, pos) 方法。
    """

    COMMAND_ID = 3001

    def __init__(self, refine_window, item_id, old_pos, new_pos, parent=None):
        super().__init__(parent)
        self.refine_window = refine_window
        self.item_id = item_id
        self.old_pos = old_pos
        self.new_pos = new_pos
        self.setText("移动文字项")

    def redo(self):
        self.refine_window._apply_move_item(self.item_id, self.new_pos)

    def undo(self):
        self.refine_window._apply_move_item(self.item_id, self.old_pos)

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


class ResizeTextItemCommand(QUndoCommand):
    """精修：缩放文字项。

    将指定 item_id 的文字项字号与矩形由旧值改为新值。
    依赖窗口的 _apply_resize_item(item_id, font_size, rect) 方法。
    """

    COMMAND_ID = 3002

    def __init__(self, refine_window, item_id, old_font_size, new_font_size,
                 old_rect, new_rect, parent=None):
        super().__init__(parent)
        self.refine_window = refine_window
        self.item_id = item_id
        self.old_font_size = old_font_size
        self.new_font_size = new_font_size
        self.old_rect = old_rect
        self.new_rect = new_rect
        self.setText("缩放文字项")

    def redo(self):
        self.refine_window._apply_resize_item(
            self.item_id, self.new_font_size, self.new_rect
        )

    def undo(self):
        self.refine_window._apply_resize_item(
            self.item_id, self.old_font_size, self.old_rect
        )

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


class DeleteTextItemCommand(QUndoCommand):
    """精修：删除文字项。

    删除指定 item_id 的文字项，undo 时按原数据重新添加。
    依赖窗口的 _apply_delete_item(item_id) 与
    _apply_add_item(item_id, item_data) 方法。
    """

    COMMAND_ID = 3003

    def __init__(self, refine_window, item_id, item_data, parent=None):
        super().__init__(parent)
        self.refine_window = refine_window
        self.item_id = item_id
        self.item_data = item_data
        self.setText("删除文字项")

    def redo(self):
        self.refine_window._apply_delete_item(self.item_id)

    def undo(self):
        self.refine_window._apply_add_item(self.item_id, self.item_data)

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False


class AddTextItemCommand(QUndoCommand):
    """精修：新增文字项。

    新增指定 item_id 的文字项，undo 时删除。
    依赖窗口的 _apply_add_item(item_id, item_data) 与
    _apply_delete_item(item_id) 方法。
    """

    COMMAND_ID = 3004

    def __init__(self, refine_window, item_id, item_data, parent=None):
        super().__init__(parent)
        self.refine_window = refine_window
        self.item_id = item_id
        self.item_data = item_data
        self.setText("新增文字项")

    def redo(self):
        self.refine_window._apply_add_item(self.item_id, self.item_data)

    def undo(self):
        self.refine_window._apply_delete_item(self.item_id)

    def id(self):
        return self.COMMAND_ID

    def mergeWith(self, other):
        return False
