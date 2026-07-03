# Checklist

- [x] "上一步"按钮应用蓝色样式(背景 #0D6EFD、白字、min-height 44px、min-width 120px、圆角 6px、hover #0b5ed7)
- [x] "上一步"与"下一步"按钮样式完全一致(均使用 `_NAV_BTN_STYLE` 类常量)
- [x] 按钮文字动态变化逻辑不受影响(第一字符"返回导入"、最后字符"进入横校")
- [x] `_recalc_layout` 水平边距改为 `-2`(仅扣除滚动区边框)
- [x] `_recalc_layout` 垂直边距改为 `0`(不再扣除 `-60` 同级布局高度)
- [x] 一行排满再换行(QGridLayout 按 `page_idx // cols`、`page_idx % cols` 填充)
- [x] 一页排满再换页(`page_size = cols * rows`)
- [x] 原图预览区顶部新增工具栏,含"显示其他字框"复选框
- [x] 勾选复选框后,预览图上以蓝框(#0d6efd, 1px, cosmetic)标出同行全部其他字符 bbox
- [x] 蓝框作为 `pixmap_item` 子项,随预览切换自动清除
- [x] 取消勾选后,预览图仅显示当前字红框
- [x] 切换选中切片时,蓝框按当前复选框状态自动渲染
- [x] `python -m py_compile ui\vertical_check_window.py` 通过
- [x] Grep 确认无 `- 40`/`- 60` 残留,`prev_step_btn` 与 `next_button` 均引用 `_NAV_BTN_STYLE`
- [x] QCheckBox.stateChanged、QGraphicsRectItem.setParentItem API 使用符合 PyQt5 文档
