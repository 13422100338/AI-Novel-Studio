import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "pages"

ApplicationWindow {
    id: window
    objectName: "f1Window"

    width: 1440
    height: 900
    minimumWidth: 1100
    minimumHeight: 680
    visible: true
    title: "AI Novel Studio (F1)"
    color: Theme.tokens.color.bgCanvas
    font.family: Theme.tokens.font.ui

    property bool sidebarVisible: true

    function navTitle(navId) {
        const map = {
            "writing": "写作",
            "characters": "人物",
            "memory": "记忆",
            "clues": "线索",
            "audit": "审校",
            "settings": "设置"
        }
        return map[navId] || "写作"
    }

    function autoSaveText(state) {
        if (state === "CLEAN") return "已保存"
        if (state === "CONFLICT") return "冲突"
        return "等待保存"
    }

    function autoSaveTone(state) {
        if (state === "CLEAN") return "success"
        if (state === "CONFLICT") return "danger"
        return "warning"
    }

    function draftText(status) {
        if (status === "QUEUED") return "排队中"
        if (status === "GENERATING") return "生成中"
        if (status === "COMPLETED") return "已完成"
        if (status === "FAILED") return "失败"
        if (status === "CANCELLED") return "已取消"
        return "空闲"
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            NavigationRail {
                Layout.preferredWidth: 56
                Layout.fillHeight: true
            }

            Rectangle {
                id: sidebarHost
                objectName: "sidebarHost"
                Layout.preferredWidth: window.sidebarVisible ? 280 : 0
                Layout.fillHeight: true
                color: Theme.tokens.color.bgSidebar
                clip: true

                Behavior on Layout.preferredWidth {
                    NumberAnimation {
                        duration: Facade.reduceMotion ? 0 : Theme.tokens.duration.panel
                    }
                }

                ContextSidebar {
                    anchors.fill: parent
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.tokens.color.bgCanvas

                StackLayout {
                    anchors.fill: parent
                    currentIndex: Facade.activeNav === "writing" ? 0 : 1

                    WritingPage {}

                    EmptyState {
                        title: "页面迁移中"
                        body: "「" + window.navTitle(Facade.activeNav) + "」工作区将在后续 Wave 接入现有服务，本轮仅实现写作工作区垂直切片。"
                    }
                }
            }

        }

        Rectangle {
            id: statusBar
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            color: Theme.tokens.color.bgSurface
            border.color: Theme.tokens.color.border
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 8

                AppButton {
                    objectName: "sidebarToggle"
                    text: window.sidebarVisible ? "收起侧栏" : "展开侧栏"
                    onClicked: window.sidebarVisible = !window.sidebarVisible
                }

                StatusChip {
                    label: "字数"
                    value: Facade.currentWordCountText
                    tone: "accent"
                }
                StatusChip {
                    label: "自动保存"
                    value: window.autoSaveText(Facade.editorState)
                    tone: window.autoSaveTone(Facade.editorState)
                }
                StatusChip {
                    label: "任务"
                    value: window.draftText(Facade.draftStatus)
                    tone: Facade.draftStatus === "GENERATING" || Facade.draftStatus === "QUEUED" ? "accent"
                        : Facade.draftStatus === "FAILED" || Facade.draftStatus === "CANCELLED" ? "danger"
                        : "neutral"
                }
                StatusChip {
                    label: "模型"
                    value: "Mock"
                    tone: "accent"
                }
                StatusChip {
                    label: "数据源"
                    value: Facade.projectSource === "project" ? "项目" : "演示"
                    tone: Facade.projectSource === "project" ? "accent" : "neutral"
                }

                Item {
                    Layout.fillWidth: true
                }

                AppButton {
                    objectName: "motionButton"
                    text: Facade.reduceMotion ? "动效：关" : "动效：开"
                    onClicked: Facade.setReduceMotion(!Facade.reduceMotion)
                }
                AppButton {
                    objectName: "themeButton"
                    text: "主题：" + Theme.themeName
                    onClicked: Theme.setTheme(Theme.nextThemeName())
                }
            }
        }
    }

    SlidingDrawer {
        anchors.fill: parent
        open: Facade.aiDrawerOpen
        onClosed: Facade.toggleAiDrawer(false)
    }
}
