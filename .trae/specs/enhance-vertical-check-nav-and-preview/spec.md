# 纵校窗口导航增强与整行预览 Spec

## Why

纵校窗口当前的导航按钮布局不符合高效校对工作流:返回按钮在左侧字符列表上方占用空间,切片展示区底部缺少"上一步"能力;字符列表无快速跳转;单选切片时无方向键导航;原图预览仅显示行局部裁剪而非整行上下文。本次增强解决这四个效率痛点。

## What Changes

- **BREAKING**:删除字符列表上方的"返回上一步"按钮,在切片展示区底部左侧放置"上一步"按钮(第一字符时变体为"返回导入")
- 切片展示区底部右侧"下一步"按钮在最后一个字符时文字变为"进入横校"
- 字符列表顶部原"返回上一步"位置放置字符跳转输入框 + 确认按钮,支持回车确认
- 单选切片时支持上下左右方向键导航(当前页内循环),取消 Enter 键等于下一步的快捷方式
- 原图预览改为显示所属 PDF 整行长条(全页宽度),复用横校 `_make_slice_pixmap` 算法

## Impact

- Affected specs: adapt-python-win7-vertical-check(纵校基础功能)
- Affected code: `d:\hx\software2\ui\vertical_check_window.py`(唯一修改文件)
- 复用参考: `d:\hx\software2\ui\horizontal_check_window.py` 的 `_make_slice_pixmap`(L475-506)全宽裁剪算法

## ADDED Requirements

### Requirement: 上一步按钮与动态文字

系统 SHALL 在切片展示区底部左侧放置"上一步"按钮。当当前字符为列表第一项时,按钮文字显示"返回导入",点击后发射 `back_signal` 返回导入阶段;否则按钮文字显示"上一步",点击后先 flush 当前字符组挂起修改,再切换到上一个字符。

#### Scenario: 非第一字符点上一步
- **WHEN** 用户在非第一字符集合点击"上一步"
- **THEN** 先 flush 当前字符组挂起修改,再切换到上一个字符集合

#### Scenario: 第一字符点上一步
- **WHEN** 用户在第一字符集合点击"上一步"(按钮显示"返回导入")
- **THEN** 发射 back_signal,返回导入阶段

### Requirement: 下一步按钮动态文字

系统 SHALL 在最后一个字符集合时将"下一步"按钮文字改为"进入横校";非最后一项时显示"下一步"。

#### Scenario: 最后一字符
- **WHEN** 用户在最后一个字符集合
- **THEN** "下一步"按钮文字显示"进入横校"

### Requirement: 字符跳转输入框

系统 SHALL 在字符列表顶部放置 QLineEdit 输入框与"确认"按钮。用户输入字符后点击确认或按回车,系统跳转到对应字符集合;若字符列表中无对应字符,弹窗提示"没有找到字符: X"。

#### Scenario: 跳转存在字符
- **WHEN** 用户输入已存在字符并确认
- **THEN** 切换到该字符集合

#### Scenario: 跳转不存在字符
- **WHEN** 用户输入不存在的字符并确认
- **THEN** 弹出 QMessageBox 提示未找到

### Requirement: 单选切片方向键导航

系统 SHALL 在仅选中一个切片时支持上下左右方向键导航。导航在当前页可见切片内循环:向某方向到头再按则循环到另一侧。系统 SHALL 取消 Enter/Return 键触发"下一步"的快捷方式(Space 保留)。

#### Scenario: 单选方向键导航
- **GIVEN** 仅选中一个切片
- **WHEN** 用户按上/下/左/右方向键
- **THEN** 选中切换到当前页对应方向的相邻切片,到头循环

#### Scenario: 多选或未选方向键
- **GIVEN** 选中 0 个或多个切片
- **WHEN** 用户按方向键
- **THEN** 不触发导航(交由默认处理)

### Requirement: 整行 PDF 长条预览

系统 SHALL 在原图预览区显示选中切片所属 PDF 整行的全宽长条(从页面左边界到右边界,y 范围为行 bbox ± 20px padding),并用红框标出当前字符位置。算法复用横校 `_make_slice_pixmap`。

#### Scenario: 显示整行长条
- **WHEN** 用户选中一个切片
- **THEN** 原图预览显示该切片所属行的全宽长条,红框居中标出字符位置

## MODIFIED Requirements

### Requirement: 纵校原图预览

原图预览从"行局部矩形裁剪"改为"整行全宽长条裁剪",x 范围固定为 [0, page_width],y 范围为 line_bbox[1]-20 到 line_bbox[3]+20。红框坐标相应调整为相对长条的偏移。

## Assumptions & Decisions

1. **返回导入不 flush**:返回导入阶段意味着放弃当前纵校会话(main.py deleteLater vert_widget),未 flush 的修改丢失符合预期。
2. **方向键仅当前页**:导航范围限于当前可见页的 page_slices,不跨页。跨页导航复杂且用户可通过"上一页/下一页"按钮实现。
3. **方向键 wrap 用模运算**:Up/Down 用 ±cols 步长,Left/Right 用 ±1 步长,统一用 `new_idx = (page_idx + delta) % len(page_slices)` 实现循环。即使最后行不满,模运算保证落到有效位置。
4. **Space 保留为下一步**:用户仅要求取消 Enter=下一步,Space 保留。
5. **跳转输入框不清空**:确认后保留输入内容,用户可连续点确认(虽无变化)。简单实现。
6. **整行长条无 line_box 回退**:若 OCR results 中找不到 line_box,用 char bbox 的 y 范围 ± padding 作为回退,x 仍全宽。
7. **_on_back 方法删除**:prev_step_btn 在 row==0 时直接 emit back_signal,_on_back 不再需要。back_signal 保留。
8. **按钮文字更新集中在 _update_nav_button_texts**:在 _update_slice_display 末尾调用,覆盖所有切换场景。
