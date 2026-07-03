# 精修文字错位修复与纵校优化 Spec

## Why
精修界面 MovableTextItem 中文字与框错位（文字出现在框右下角），纵校界面有多余的偏移量调整功能和切片宽度不一致的问题。

## What Changes
- 修复精修 MovableTextItem 文字与框的错位问题
- 移除纵校右键菜单中的"调整位置"功能
- 纵校切片按比例缩放到与行文本宽度一致

## Impact
- Affected code: `ui/refine_window.py`, `ui/vertical_check_window.py`

## ADDED Requirements

### Requirement: 纵校切片宽度与行文本一致
纵校界面浮现在行文本上的原 PDF 切片 SHALL 按比例缩放，使其宽度与对应行文本的显示宽度一致。

#### Scenario: 切片宽度匹配行文本
- **WHEN** 鼠标悬停在某行文字上显示切片
- **THEN** 切片按比例缩放，宽度等于该行文本的显示宽度（bbox宽度 × zoom_level）
- **AND** 切片高度按相同比例缩放，保持原始宽高比

## MODIFIED Requirements

### Requirement: 精修文字项文字与框对齐
MovableTextItem 中的文字 SHALL 精确居中在框内，不出现偏移。根因：QGraphicsTextItem 默认有 document margin（约4px），导致文字从 (0,0) 位置绘制时向右下偏移。修复方案：设置 `document().setDocumentMargin(0)` 并调整文字位置使其垂直居中。

### Requirement: 纵校右键菜单精简
纵校界面的右键菜单 SHALL 只保留"修改文字"和"忽略/删除"两个选项，移除"调整位置"选项及其实现代码。

## REMOVED Requirements

### Requirement: 纵校调整位置功能
**Reason**: 精修环节已提供拖拽移动功能，纵校中的偏移量调整不再需要
**Migration**: 用户可在精修环节通过拖拽工具调整文字位置
