import QtQuick
import "../components"

OverviewPlaceholderPage {
    objectName: "charactersPage"
    title: "人物"
    countLabel: "当前章节人物"
    countText: Facade.characterCountText
    description: "人物列表、状态时间线与身份冲突将在后续 Wave 接入现有服务；当前仅显示只读数量概览。"
}

