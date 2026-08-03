import QtQuick
import "../components"

OverviewPlaceholderPage {
    objectName: "memoryPage"
    title: "记忆"
    countLabel: "当前章节记忆"
    countText: Facade.memoryCountText
    description: "记忆库、整理与待确认项将在后续 Wave 接入现有服务；当前仅显示只读数量概览。"
}

