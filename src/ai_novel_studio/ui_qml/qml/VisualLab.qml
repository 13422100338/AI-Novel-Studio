import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "design"
import "effects"
import "surfaces"

// Visual V0 rework (diagnosis doc: AI_Novel_Studio_Visual_V0实验页问题诊断与下一版重做要求.md).
// The lab is now a scaled-down, business-free four-column mirror of the
// target writing workspace:
//   NavigationRail | ContextSidebar | Acrylic editor (正文) | AI Acrylic Panel
//
// Route decisions (course correction):
// - Opaque ApplicationWindow; BackdropLayer covers the whole window with a
//   solid theme fallback so no black bare region can appear.
// - App-controlled Acrylic (BackdropLayer + AcrylicSurface) is the main
//   visual route; system Mica is an optional, default-off experiment toggled
//   from the experiment control drawer.
// - Quality tiers share the same window, layout and component structure;
//   only blur/noise/shadow strength changes.
// - All content is static QML demo data (no Facade, no WebEngine, no backend).
ApplicationWindow {
    id: root
    objectName: "visualLabWindow"

    width: 1440
    height: 900
    minimumWidth: 1100
    minimumHeight: 700
    visible: true
    title: "AI Novel Studio · Visual V0 样板"
    // Opaque by default. Only the optional Mica experiment (default off)
    // makes the window transparent; otherwise the theme canvas is the
    // reliable fallback and no bare black region can appear.
    property bool systemBackdrop: false
    readonly property bool micaActive:
        root.systemBackdrop && Theme.visualQuality !== "safe"
    color: root.micaActive ? "transparent" : Theme.tokens.color.bgCanvas
    font.family: Theme.tokens.font.ui

    property bool experimentOpen: false
    property bool debugBackdrop: false
    property bool debugSourceRect: false
    property bool debugBlurRegion: false
    // Neon flow demo state (user direction §24): idle | thinking | generating
    // | success | error | cancelled | reduced.
    property string neonDemoMode: "thinking"
    // Lightweight FPS estimate (diagnosis doc §10: show FPS / render backend).
    property int frameCount: 0
    property int lastFrameCount: 0
    property real fpsEstimate: 0

    Connections {
        target: root
        function onFrameSwapped() {
            root.frameCount += 1
        }
    }
    Timer {
        interval: 1000
        repeat: true
        running: root.visible
        onTriggered: {
            root.fpsEstimate = root.frameCount - root.lastFrameCount
            root.lastFrameCount = root.frameCount
        }
    }

    // App-controlled backdrop: full-window coverage with solid fallback.
    BackdropLayer {
        id: backgroundLayer
        objectName: "labBackgroundLayer"
        anchors.fill: parent
        washEnabled: root.micaActive
        washAlpha: Theme.visualQuality === "premium" ? 0.18 : 0.32
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // --- Header: title + one entry point to the experiment drawer. Same
        // glass material as the four-column workspace (user feedback: every
        // container should share the unified glass style).
        AcrylicSurface {
            objectName: "labHeader"
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            sourceItem: backgroundLayer
            radius: 0

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 12
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: "Visual V0 · 理想 UI 样板"
                    font.pixelSize: 16
                    font.bold: true
                    color: Theme.tokens.color.textPrimary
                }

                AppButton {
                    objectName: "experimentOpenButton"
                    text: "实验控制"
                    ghost: true
                    onClicked: root.experimentOpen = true
                }
            }
        }

        // --- Experiment control strip: folds down between the header and the
        // body so the four-column workspace shifts instead of being covered
        // (fixes the previous drawer covering the AI panel and being hard to
        // dismiss).
        ExperimentControlPanel {
            id: controlPanel
            Layout.fillWidth: true
            Layout.preferredHeight: root.experimentOpen ? controlPanel.implicitHeight : 0
            clip: true
            visible: root.experimentOpen
            open: root.experimentOpen
            fpsEstimate: root.fpsEstimate
            renderBackend: typeof RenderBackendInfo !== "undefined"
                ? RenderBackendInfo : "unknown"
            debugBackdrop: root.debugBackdrop
            debugSourceRect: root.debugSourceRect
            debugBlurRegion: root.debugBlurRegion
            micaExperiment: root.systemBackdrop
            onClosed: root.experimentOpen = false
            onMicaChanged: root.systemBackdrop = enabled
            onDebugBackdropToggled: root.debugBackdrop = enabled
            onDebugSourceRectToggled: root.debugSourceRect = enabled
            onDebugBlurRegionToggled: root.debugBlurRegion = enabled
        }

        // --- Four-column body (mirrors the target workspace structure).
        RowLayout {
            id: bodyLayout
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0
            // "显示背景原图": fade the surfaces out so the raw BackdropLayer
            // is visible for Acrylic evaluation.
            opacity: root.debugBackdrop ? 0.15 : 1.0

            Behavior on opacity {
                NumberAnimation {
                    duration: Facade.reduceMotion ? 0 : Theme.tokens.duration.normal
                    easing.type: Easing.OutCubic
                }
            }

            // 1. Navigation rail (static demo) - Acrylic glass surface so the
            // quality tiers change it too (diagnosis doc §7.1).
            AcrylicSurface {
                objectName: "labNavRail"
                Layout.preferredWidth: 56
                Layout.fillHeight: true
                sourceItem: backgroundLayer
                radius: 0

                ColumnLayout {
                    anchors.fill: parent
                    anchors.topMargin: 10
                    anchors.bottomMargin: 10
                    spacing: 4

                    Item { Layout.preferredHeight: 8 }

                    Repeater {
                        model: [
                            { icon: "\u270E", label: "写作", active: true },
                            { icon: "\u25A4", label: "记忆库", active: false },
                            { icon: "\u2726", label: "高级创作", active: false },
                            { icon: "\u2699", label: "设置", active: false }
                        ]
                        delegate: IconButton {
                            Layout.preferredWidth: 44
                            Layout.preferredHeight: 48
                            Layout.alignment: Qt.AlignHCenter
                            iconText: modelData.icon
                            text: modelData.label
                            selected: modelData.active
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            // 2. Context / chapter sidebar (static demo) - Acrylic glass
            // surface so the quality tiers change it too (doc §7.1).
            AcrylicSurface {
                objectName: "labChapterSidebar"
                Layout.preferredWidth: 270
                Layout.fillHeight: true
                sourceItem: backgroundLayer
                radius: 0

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    Text {
                        Layout.fillWidth: true
                        text: "雾港来信"
                        font.pixelSize: 15
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "第一卷 · 潮汐声（8 章）"
                        font.pixelSize: 11
                        color: Theme.tokens.color.textSecondary
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: Theme.tokens.color.border
                    }

                    // Static chapter tree (current chapter highlighted).
                    ListView {
                        id: chapterList
                        objectName: "labChapterList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 2
                        model: [
                            { kind: "volume", title: "第一卷 · 潮汐声" },
                            { kind: "chapter", title: "第 1 章 渡口", count: "1,280 字", current: false },
                            { kind: "chapter", title: "第 2 章 潮汐声", count: "2,140 字", current: true },
                            { kind: "chapter", title: "第 3 章 灯塔", count: "980 字", current: false },
                            { kind: "chapter", title: "第 4 章 栈桥", count: "1,540 字", current: false }
                        ]
                        delegate: Rectangle {
                            width: chapterList.width
                            height: modelData.kind === "volume" ? 28 : 42
                            radius: Theme.tokens.radius.r8
                            color: modelData.kind === "volume" ? "transparent"
                                 : modelData.current ? Theme.tokens.color.pressed
                                 : "transparent"

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 6
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    font.pixelSize: modelData.kind === "volume" ? 11 : 13
                                    font.bold: modelData.kind === "volume" || modelData.current
                                    elide: Text.ElideRight
                                    color: modelData.current
                                        ? Theme.tokens.color.accent
                                        : Theme.tokens.color.textPrimary
                                }
                                Text {
                                    visible: modelData.kind === "chapter"
                                    text: modelData.count || ""
                                    font.pixelSize: 10
                                    color: Theme.tokens.color.textSecondary
                                }
                            }
                        }
                    }
                }
            }

            // 3. Central manuscript workspace — same glass material as the
            // side panels (user feedback: the central editor should share the
            // unified glass style, blurring the same BackdropLayer glow).
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                AcrylicSurface {
                    objectName: "labPaperSurface"
                    anchors.fill: parent
                    anchors.margins: 12
                    sourceItem: backgroundLayer
                    radius: Theme.tokens.radius.r12

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 24
                        spacing: 8

                        Text {
                            Layout.fillWidth: true
                            text: "第 2 章 潮汐声"
                            font.pixelSize: 19
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "第一卷 · 雾港来信"
                            font.pixelSize: 11
                            color: Theme.tokens.color.textSecondary
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.topMargin: 6
                            Layout.bottomMargin: 6
                            height: 1
                            color: Theme.tokens.color.border
                        }

                        Text {
                            Layout.fillWidth: true
                            text: "清晨的雾港还浸在灰蓝色的光线里。渡轮靠岸时，甲板上的水汽把远处灯塔的光晕揉成一团模糊的暖色。"
                            font.family: Theme.tokens.font.manuscript
                            font.pixelSize: 14
                            lineHeight: 1.8
                            wrapMode: Text.WordWrap
                            color: Theme.tokens.color.textPrimary
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "林默把最后一封信塞进外套内袋，沿着湿漉漉的栈桥走进镇子。雾还没散，灯塔的灯一圈圈地转着，像是替谁守着什么。"
                            font.family: Theme.tokens.font.manuscript
                            font.pixelSize: 14
                            lineHeight: 1.8
                            wrapMode: Text.WordWrap
                            color: Theme.tokens.color.textPrimary
                        }
                        Text {
                            Layout.fillWidth: true
                            text: "他在老渡口站了很久，直到船工把缆绳抛上岸，才想起自己已经三年没有回来。"
                            font.family: Theme.tokens.font.manuscript
                            font.pixelSize: 14
                            lineHeight: 1.8
                            wrapMode: Text.WordWrap
                            color: Theme.tokens.color.textPrimary
                        }

                        Item {
                            Layout.fillHeight: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                Layout.fillWidth: true
                                text: "约 2,140 字 · 已保存"
                                font.pixelSize: 10
                                color: Theme.tokens.color.textSecondary
                            }
                            StatusChip {
                                label: "状态"
                                value: "已保存"
                                tone: "success"
                            }
                        }
                    }
                }
            }

            // 4. AI assistant acrylic panel (complete panel, cards inside).
            Item {
                id: aiPanelHost
                Layout.preferredWidth: 360
                Layout.fillHeight: true

                AcrylicSurface {
                    objectName: "labAcrylicSurface"
                    anchors.fill: parent
                    anchors.margins: 12
                    sourceItem: backgroundLayer
                    visible: !root.micaActive
                }
                GlassSurface {
                    objectName: "labGlassSurface"
                    anchors.fill: parent
                    anchors.margins: 12
                    opaque: true
                    visible: root.micaActive
                }

                // Debug overlays (inside the AI panel host so coordinates are
                // relative and the outlines never overlap other columns).
                Rectangle {
                    visible: root.debugSourceRect
                    anchors.fill: parent
                    color: "transparent"
                    border.color: "#E53935"
                    border.width: 1
                    opacity: 0.85
                }
                Rectangle {
                    visible: root.debugBlurRegion
                    anchors.fill: parent
                    anchors.margins: -2
                    color: "transparent"
                    border.color: "#43A047"
                    border.width: 1
                    opacity: 0.7
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 8

                    // Header.
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: "AI 助手"
                            font.pixelSize: 14
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                        }
                        StatusChip {
                            label: "运行中"
                            value: "2 个步骤"
                            tone: "accent"
                        }
                    }

                    // Lightweight status lines (not big cards).
                    Repeater {
                        model: [
                            { done: true, text: "已读取当前章节" },
                            { done: true, text: "已找到 3 条相关记忆" },
                            { done: false, text: "正在生成修改稿" }
                        ]
                        delegate: RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text {
                                text: modelData.done ? "\u2713" : "\u25CB"
                                font.pixelSize: 11
                                color: modelData.done
                                    ? Theme.tokens.color.success
                                    : Theme.tokens.color.warning
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.text
                                font.pixelSize: 11
                                color: Theme.tokens.color.textPrimary
                            }
                        }
                    }

                    // Neon flow showcase (user direction §24): one 320x160
                    // rounded card whose border carries an energy point with a
                    // fading tail + soft halo traveling the full perimeter.
                    // Only ONE state is active at a time (并发上限 1-2).
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        Item {
                            Layout.preferredWidth: 320
                            Layout.preferredHeight: 160
                            Layout.alignment: Qt.AlignHCenter

                            Rectangle {
                                objectName: "neonDemoCard"
                                anchors.fill: parent
                                radius: Theme.tokens.radius.r16
                                color: Theme.tokens.color.bgSurface

                                Text {
                                    anchors.centerIn: parent
                                    text: {
                                        var labels = {
                                            "idle": "idle · 静态边框",
                                            "thinking": "thinking · 循环流光",
                                            "generating": "generating · 循环流光",
                                            "success": "success · 单次扫过",
                                            "error": "error · 单次扫过",
                                            "cancelled": "cancelled · 淡出",
                                            "reduced": "reduceMotion · 静态高亮"
                                        }
                                        return labels[root.neonDemoMode] || root.neonDemoMode
                                    }
                                    font.pixelSize: 12
                                    font.bold: true
                                    color: Theme.tokens.color.textPrimary
                                }
                            }
                            StreamingGlowBorder {
                                id: neonDemoGlow
                                objectName: "labNeonDemoGlow"
                                anchors.fill: parent
                                radius: Theme.tokens.radius.r16
                                active: root.neonDemoMode !== "idle"
                                state: root.neonDemoMode === "reduced"
                                    ? "idle"
                                    : root.neonDemoMode
                            }
                        }

                        Flow {
                            Layout.fillWidth: true
                            spacing: 6
                            Repeater {
                                model: [
                                    "idle", "thinking", "generating",
                                    "success", "error", "cancelled", "reduced"
                                ]
                                delegate: AppButton {
                                    objectName: "labNeonMode-" + modelData
                                    text: modelData
                                    ghost: true
                                    selected: root.neonDemoMode === modelData
                                    onClicked: root.neonDemoMode = modelData
                                }
                            }
                        }
                    }

                    // Diff card keeps a plain static border in the lab so the
                    // neon demo is the only flowing instance.
                    TextDiffCard {
                        objectName: "labDiffCard"
                        Layout.fillWidth: true
                        label: "修改对比 · 第三段"
                        currentText: "渡轮靠岸时，甲板上的水汽把远处灯塔的光晕揉成一团模糊的暖色。"
                        draftText: "渡轮靠岸时，咸湿的水汽在甲板上流动，把远处灯塔的光晕揉成一团暖色。"
                        state: "PENDING"
                    }

                    ChangeSetCard {
                        objectName: "labChangeSetCard"
                        Layout.fillWidth: true
                        label: "变更提案"
                        target: "人物 · 林默"
                        operation: "更新"
                        beforeText: "码头工人"
                        afterText: "退役水手"
                        risk: "低"
                        reason: "Mock 提案：人物设定与第一章背景冲突"
                        state: "PENDING"
                    }

                    FormCard {
                        objectName: "labFormCard"
                        Layout.fillWidth: true
                        title: "补充设定"
                        description: "请补充人物关系设定（Mock 表单，不写入项目）"
                        fieldLabels: ["人物名", "关系", "备注"]
                        fieldValues: ["林默", "旧友", "待确认"]
                        state: "PENDING"
                    }

                    Item {
                        Layout.fillHeight: true
                    }

                    // Quick actions.
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6
                        AppButton { text: "重写"; primary: true }
                        AppButton { text: "润色" }
                        AppButton { text: "再次生成"; ghost: true }
                        AppButton { text: "停止"; ghost: true }
                    }

                    // Composer.
                    TextField {
                        objectName: "labInputField"
                        Layout.fillWidth: true
                        placeholderText: "向 AI 助手提问…（Enter 发送，Shift+Enter 换行）"
                        color: Theme.tokens.color.textPrimary
                        placeholderTextColor: Theme.tokens.color.textSecondary
                        font.pixelSize: 11
                        background: Rectangle {
                            radius: Theme.tokens.radius.r8
                            color: Theme.tokens.color.bgSurface
                            border.color: Theme.tokens.color.border
                            border.width: 1
                        }
                    }
                }
            }

            // 5. Scrollbar template: the vertical scrollbar at the far right
            // edge of the window (user clarification). Glass panel with a
            // long mock manuscript and a right-edge GlassScrollbar.
            ScrollbarTemplate {
                objectName: "labScrollbarTemplate"
                Layout.preferredWidth: 230
                Layout.fillHeight: true
                sourceItem: backgroundLayer
            }
        }

    }

}
