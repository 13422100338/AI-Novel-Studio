import QtQuick
import "../components"

OverviewPlaceholderPage {
    objectName: "auditPage"
    title: "审校"
    countLabel: "当前章节审校问题"
    countText: Facade.auditCountText
    description: "审校工作台、证据定位与修复将在后续 Wave 接入现有服务；当前仅显示只读数量概览。"
}

