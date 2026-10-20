import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    objectName: "auditPage"
    readonly property bool readOnly: Facade.codexEnabled

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 12

        Text {
            text: root.readOnly ? "审校 · 历史只读" : "审校"
            font.pixelSize: 17
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            StatusChip {
                objectName: "auditPageCount"
                label: "当前章节审校问题"
                value: Facade.auditCountText
                tone: "accent"
            }
            Item { Layout.fillWidth: true }
            AppButton {
                objectName: "auditRefreshButton"
                text: "刷新"
                onClicked: Facade.refreshAdvancedReads()
            }
        }

        ListView {
            id: list
            objectName: "auditList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: Facade.auditViews
            ScrollBar.vertical: ScrollBar {}

            delegate: Rectangle {
                width: list.width
                height: card.implicitHeight
                radius: Theme.tokens.radius.r12
                color: Theme.tokens.color.bgSurface
                border.color: Theme.tokens.color.border
                border.width: 1

                ColumnLayout {
                    id: card
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 4

                    Text {
                        text: root.severityLabel(severity) + " · " + category
                        font.pixelSize: 13
                        font.bold: true
                        color: root.severityColor(severity)
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: evidence !== ""
                        text: "证据：" + evidence
                        font.pixelSize: 12
                        color: Theme.tokens.color.textPrimary
                        wrapMode: Text.WordWrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                    Text {
                        Layout.fillWidth: true
                        visible: explanation !== ""
                        text: explanation
                        font.pixelSize: 12
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                    }
                    Text {
                        text: "置信度 " + confidence.toFixed(2) + " · 状态 " + status
                        font.pixelSize: 11
                        color: Theme.tokens.color.textSecondary
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        visible: status === "OPEN" && !root.readOnly
                        spacing: 6

                        Item {
                            Layout.fillWidth: true
                        }
                        AppButton {
                            objectName: "ignoreAuditButton"
                            text: "忽略"
                            onClicked: Facade.updateAuditFindingStatus(index, "REJECTED")
                        }
                        AppButton {
                            objectName: "falsePositiveAuditButton"
                            text: "误报"
                            onClicked: Facade.updateAuditFindingStatus(index, "FALSE_POSITIVE")
                        }
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    onDoubleClicked: Facade.revealAuditEvidence(index)
                }
            }

            EmptyState {
                objectName: "auditEmptyState"
                anchors.fill: parent
                visible: Facade.auditViews.count === 0
                title: Facade.advancedState === "NO_PROJECT"
                       ? "未打开项目"
                       : Facade.advancedState === "ERROR"
                         ? "审校读取失败"
                         : "暂无审校问题"
                body: Facade.advancedState === "NO_PROJECT"
                      ? "打开项目后，这里显示当前章节的审校发现。"
                      : Facade.advancedState === "ERROR"
                        ? "读取审校数据失败，请点击「刷新」重试。"
                        : "当前章节没有审校问题；审校工作台与修复流程将在后续 Wave 接线。"
            }
        }
    }

    function severityLabel(value) {
        if (value === "ERROR") return "错误"
        if (value === "BLOCKER") return "阻断"
        if (value === "WARNING") return "警告"
        if (value === "INFO") return "提示"
        return value
    }

    function severityColor(value) {
        if (value === "ERROR" || value === "BLOCKER") return Theme.tokens.color.danger
        if (value === "WARNING") return Theme.tokens.color.warning
        return Theme.tokens.color.textSecondary
    }
}
