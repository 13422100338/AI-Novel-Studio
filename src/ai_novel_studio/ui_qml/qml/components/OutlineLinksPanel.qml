import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Popup {
    id: root
    property var outline
    property int sourceLine: 1
    readonly property var view: outline.state
    readonly property bool ready: view.loaded && !view.dirty && view.linksReady
    readonly property string reviewToken: view.currentId + ":" + view.linkFingerprint + ":" + view.linksEpoch
    property var selectedIds: []
    property string expandedHistory: ""
    signal revealRequested(int position)

    objectName: "outlineLinksPanel"
    width: Math.min(390, parent ? parent.width : 390)
    height: parent ? parent.height : 640
    x: parent ? Math.max(0, parent.width - width) : 0
    y: 0
    padding: 16
    modal: false
    closePolicy: Popup.CloseOnEscape
    onReviewTokenChanged: { selectedIds = []; expandedHistory = "" }
    background: Rectangle { color: Theme.tokens.color.bgSurface; radius: 12; border.color: Theme.tokens.color.border }

    function toggleSelected(linkId, checked) {
        selectedIds = checked ? selectedIds.filter(function(id) { return id !== linkId }).concat([linkId])
                              : selectedIds.filter(function(id) { return id !== linkId })
    }

    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text { text: "章节关联"; font.pixelSize: 18; font.bold: true; color: Theme.tokens.color.textPrimary }
            Item { Layout.fillWidth: true }
            AppButton { text: "×"; ghost: true; Accessible.name: "关闭章节关联"; onClicked: root.close() }
        }
        Text {
            Layout.fillWidth: true
            text: root.view.dirty ? "大纲有未保存更改，保存后重新检查关联。"
                : !root.view.linksReady ? "关联尚未完成检查，原有记录保留，暂不能确认。"
                : "全书有 " + root.view.pendingLinkCount + " 项待确认。改纲后旧关联保留，需重新确认。"
            wrapMode: Text.WordWrap
            font.pixelSize: 12
            color: Theme.tokens.color.textSecondary
        }
        AppButton {
            Layout.fillWidth: true
            text: root.view.dirty ? "保存并检查关联" : "重新扫描大纲链接"
            enabled: root.view.loaded
            onClicked: { if (root.outline.flush()) root.outline.refreshLinks() }
        }
        Text {
            visible: root.view.linksError !== ""
            Layout.fillWidth: true
            text: root.view.linksError
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.danger
            font.pixelSize: 12
        }
        Text {
            Layout.fillWidth: true
            text: "在光标所在行后插入章节链接 · 第 " + root.sourceLine + " 行"
            color: Theme.tokens.color.textSecondary
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
        ComboBox {
            id: chapterChoice
            objectName: "outlineLinkChapterChoice"
            Layout.fillWidth: true
            model: root.view.linkChapters
            textRole: "title"
            valueRole: "id"
            palette.text: Theme.tokens.color.textPrimary
            background: Rectangle { color: Theme.tokens.color.bgCanvas; border.color: Theme.tokens.color.border; radius: 8 }
        }
        AppButton {
            objectName: "outlineLinkInsertButton"
            Layout.fillWidth: true
            text: "插入关联"
            enabled: root.view.loaded && root.view.linkChapters.length > 0
            onClicked: root.outline.insertChapterLink(chapterChoice.currentValue, root.sourceLine)
        }
        CheckBox {
            id: showRemoved
            text: "显示已确认移除的历史关联"
            palette.text: Theme.tokens.color.textSecondary
            palette.highlight: Theme.tokens.color.accent
            font.pixelSize: 12
        }
        ListView {
            id: linksList
            objectName: "outlineLinksList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10
            clip: true
            model: root.view.links.filter(function(item) { return item.active || showRemoved.checked })
            delegate: Rectangle {
                required property var modelData
                width: linksList.width
                implicitHeight: card.implicitHeight + 20
                radius: 8
                color: Theme.tokens.color.bgCanvas
                border.color: Theme.tokens.color.border
                ColumnLayout {
                    id: card
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        CheckBox {
                            objectName: "outline-link-select-" + modelData.id
                            checked: root.selectedIds.indexOf(modelData.id) >= 0
                            enabled: root.ready && modelData.status === "PENDING"
                            palette.highlight: Theme.tokens.color.accent
                            onClicked: root.toggleSelected(modelData.id, checked)
                        }
                        Text {
                            Layout.fillWidth: true
                            text: modelData.chapterTitle
                            textFormat: Text.PlainText
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                            wrapMode: Text.WordWrap
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: (root.view.dirty && modelData.active ? "待保存后检查" : !root.view.linksReady && modelData.active ? "待重新检查" : modelData.statusText)
                            + " · " + (modelData.position >= 0 ? "第 " : "原位置第 ") + modelData.line + " 行"
                        color: modelData.status === "CONFIRMED" && root.ready ? Theme.tokens.color.success : Theme.tokens.color.warning
                        font.pixelSize: 12
                    }
                    Text {
                        visible: modelData.section !== ""
                        Layout.fillWidth: true
                        text: modelData.section
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        color: Theme.tokens.color.textSecondary
                        font.pixelSize: 12
                    }
                    Text {
                        Layout.fillWidth: true
                        text: modelData.quote
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        color: Theme.tokens.color.textSecondary
                        font.pixelSize: 11
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 4
                        AppButton {
                            objectName: "outline-link-open-" + modelData.id
                            text: "打开章节"; ghost: true
                            enabled: modelData.chapterAvailable
                            onClicked: root.outline.openLinkedChapter(modelData.chapterId)
                        }
                        AppButton {
                            text: "查看位置"; ghost: true
                            enabled: !root.view.dirty && modelData.position >= 0
                            onClicked: root.revealRequested(modelData.position)
                        }
                        AppButton {
                            text: "定位到当前行"; ghost: true
                            visible: modelData.status === "MISSING_SOURCE"
                            enabled: root.ready
                            onClicked: root.outline.relocateLink(modelData.id, root.sourceLine, root.view.linkFingerprint)
                        }
                        AppButton {
                            objectName: "outline-link-retire-" + modelData.id
                            text: "确认移除"; ghost: true
                            visible: modelData.status === "MISSING_SOURCE" || modelData.status === "MISSING_CHAPTER"
                            enabled: root.ready
                            onClicked: root.outline.retireLink(modelData.id, root.view.linkFingerprint)
                        }
                        AppButton {
                            text: root.expandedHistory === modelData.id ? "收起记录" : "确认记录"
                            ghost: true
                            onClicked: root.expandedHistory = root.expandedHistory === modelData.id ? "" : modelData.id
                        }
                    }
                    Text {
                        visible: root.expandedHistory === modelData.id
                        Layout.fillWidth: true
                        text: modelData.history.map(function(item) { return item.time + " · " + item.action + " · 原文修订 " + item.revision + "，第 " + item.line + " 行" }).join("\n")
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        color: Theme.tokens.color.textSecondary
                        font.pixelSize: 11
                    }
                }
            }
        }
        Text {
            visible: linksList.count === 0
            Layout.fillWidth: true
            text: "先在大纲中选定事件，再选择正式章节插入链接。已有的普通章节链接可重新扫描识别。"
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textSecondary
            font.pixelSize: 12
        }
        AppButton {
            objectName: "outlineLinksConfirmButton"
            Layout.fillWidth: true
            text: "确认所选关联（" + root.selectedIds.length + "）"
            primary: true
            enabled: root.ready && root.selectedIds.length > 0
            onClicked: root.outline.confirmLinks(root.selectedIds, root.view.linkFingerprint)
        }
    }
}
