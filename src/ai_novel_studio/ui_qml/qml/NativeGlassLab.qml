import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "surfaces"

// Native Glass Lab (isolation ticket: AI-Novel-Studio-原生毛玻璃测试界面-实施任务.md).
//
// Standalone experiment page, deliberately separate from the production
// shell and the Visual V0 lab:
//   - mode "native": frameless transparent window + DWM system backdrop
//     (Desktop Acrylic by default, Mica optional). The window behind content
//     (wallpaper / other apps) is blurred by DWM itself.
//   - mode "internal": opaque window, app-controlled Acrylic (AcrylicSurface
//     blurring an in-app BackdropLayer). Visual comparison only.
//   - mode "solid": opaque window, plain theme surfaces. Readability/fallback
//     comparison.
// The lab never claims a native material is active unless the Python bridge
// confirmed the DWM call AND the machine supports it (Windows build 22621+,
// "Transparency effects" enabled).
ApplicationWindow {
    id: root
    objectName: "nativeGlassWindow"

    width: 1280
    height: 820
    minimumWidth: 960
    minimumHeight: 640
    visible: true
    title: "AI Novel Studio · Native Glass Lab"
    flags: Qt.FramelessWindowHint
    // Transparent only while a native DWM backdrop is confirmed active;
    // otherwise the opaque theme canvas is the reliable fallback.
    color: root.nativeActive ? "transparent" : Theme.tokens.color.bgCanvas
    font.family: Theme.tokens.font.ui

    // --- Lab state ---------------------------------------------------------
    property string mode: "native"               // native | internal | solid
    property string nativeKind: "acrylic"        // acrylic | mica
    property string themeName: "dark"
    readonly property string activeKind:
        typeof NativeGlassBridge !== "undefined"
            ? NativeGlassBridge.activeKind : "none"
    property string statusReason: ""
    readonly property bool nativeSupported:
        typeof NativeGlassBridge !== "undefined" && NativeGlassBridge.nativeSupported
    readonly property bool nativeActive:
        typeof NativeGlassBridge !== "undefined" && NativeGlassBridge.nativeActive

    // Lightweight FPS estimate (same approach as VisualLab).
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

    // Helper: theme hex string -> rgba with alpha.
    function tint(color: color, alpha: real): color {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }

    // --- Mode application --------------------------------------------------
    function applyMode(nextMode: string) {
        root.mode = nextMode
        if (typeof NativeGlassBridge === "undefined") {
            root.statusReason = "实验桥接未注册"
            return
        }
        if (nextMode === "native") {
            root.nativeRetryCount = 0
            const ok = NativeGlassBridge.apply(root.nativeKind)
            root.statusReason = ok ? "" : NativeGlassBridge.unsupportedReason
        } else {
            NativeGlassBridge.apply("none")
            root.statusReason = ""
        }
        NativeGlassBridge.setDarkMode(root.themeName === "dark")
    }

    function switchNativeKind(kind: string) {
        root.nativeKind = kind
        if (root.mode === "native") {
            root.applyMode("native")
        }
    }

    function switchTheme(name: string) {
        root.themeName = name
        Theme.setTheme(name)
        if (typeof NativeGlassBridge !== "undefined") {
            NativeGlassBridge.setDarkMode(name === "dark")
        }
    }

    // Qt's transparent QML window can race the DWM material on first show;
    // re-apply once the window is actually visible (and once more shortly
    // after, bounded, to cover handle-rebuild quirks).
    onVisibleChanged: {
        if (root.visible && root.mode === "native") {
            root.applyMode("native")
        }
    }
    // DWM can reject the backdrop while the window is not the foreground
    // window (verified on Windows 11 25H2: first acrylic call failed until
    // the window was activated). Re-apply when the window gains activation.
    onActiveChanged: {
        if (root.active && root.mode === "native") {
            root.applyMode("native")
        }
    }
    Timer {
        interval: 150
        repeat: false
        running: root.visible
        onTriggered: {
            if (root.mode === "native" && typeof NativeGlassBridge !== "undefined") {
                NativeGlassBridge.refresh()
            }
        }
    }

    // DWM first-show race: the window can briefly report apply success and
    // then lose the material when Qt rebuilds the native handle. Retry a few
    // times while the lab is in native mode before giving up.
    property int nativeRetryCount: 0
    Timer {
        interval: 300
        repeat: true
        running: root.visible && root.mode === "native"
            && root.nativeSupported && !root.nativeActive
            && root.nativeRetryCount < 5
        onTriggered: {
            if (typeof NativeGlassBridge !== "undefined") {
                root.nativeRetryCount += 1
                const ok = NativeGlassBridge.refresh()
                if (ok) {
                    root.nativeRetryCount = 5
                }
            }
        }
    }
    onNativeActiveChanged: {
        if (root.nativeActive) {
            root.nativeRetryCount = 5
        }
    }

    // --- Window-level wash -------------------------------------------------
    // Native: light theme tint over the DWM backdrop so text stays readable
    // while the wallpaper/other-app blur still shows through. Internal/solid:
    // fully opaque theme canvas.
    Rectangle {
        id: windowWash
        objectName: "ngBackdrop"
        anchors.fill: parent
        visible: true
        color: root.nativeActive
            ? root.tint(Theme.tokens.color.bgCanvas, 0.15)
            : Theme.tokens.color.bgCanvas
    }

    // In-app backdrop used only by the "internal" mode's AcrylicSurface blur
    // (decorative glows so the blur has something to soften).
    BackdropLayer {
        id: backdropLayer
        objectName: "ngBackdropLayer"
        anchors.fill: parent
        visible: root.mode === "internal"
        washEnabled: false
    }

    // --- Local glass panel -------------------------------------------------
    // native: translucent theme fill over the DWM backdrop.
    // internal: real-time app-internal Acrylic.
    // solid: opaque theme fill.
    component LabPanel: Item {
        id: panel
        default property alias content: panelContent.data
        property real radius: 12
        property real translucency: 0.55   // 0..1, 1 = opaque
        property string panelName: ""

        // internal: real-time app-internal Acrylic.
        // solid: same component with the opaque fallback so the panel keeps
        // the unified material language (border + noise) without blur/tint.
        AcrylicSurface {
            anchors.fill: parent
            visible: root.mode !== "native"
            radius: panel.radius
            sourceItem: backdropLayer
            opaqueFallback: root.mode === "solid"
            objectName: panel.panelName.length > 0 ? panel.panelName + "Acrylic" : ""
        }

        Rectangle {
            id: panelFill
            anchors.fill: parent
            radius: panel.radius
            visible: root.mode === "native"
            color: root.tint(Theme.tokens.color.bgSurface, panel.translucency)
            border.color: Theme.tokens.color.border
            border.width: 1
        }

        Item {
            id: panelContent
            anchors.fill: parent
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // --- Custom title bar (frameless window drag + window controls) ----
        Item {
            id: titleBar
            objectName: "ngTitleBar"
            Layout.fillWidth: true
            Layout.preferredHeight: 40

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                onPressed: {
                    if (typeof root.startSystemMove === "function") {
                        root.startSystemMove()
                    }
                }
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 8
                spacing: 6

                Text {
                    text: "Native Glass Lab"
                    font.pixelSize: 13
                    font.bold: true
                    color: Theme.tokens.color.textPrimary
                }
                Text {
                    text: "· 原生毛玻璃测试（隔离实验，不接业务）"
                    font.pixelSize: 11
                    color: Theme.tokens.color.textSecondary
                }

                Item { Layout.fillWidth: true }

                AppButton {
                    objectName: "ngModeNative"
                    text: "native"
                    ghost: true
                    selected: root.mode === "native"
                    onClicked: root.applyMode("native")
                }
                AppButton {
                    objectName: "ngModeInternal"
                    text: "internal"
                    ghost: true
                    selected: root.mode === "internal"
                    onClicked: root.applyMode("internal")
                }
                AppButton {
                    objectName: "ngModeSolid"
                    text: "solid"
                    ghost: true
                    selected: root.mode === "solid"
                    onClicked: root.applyMode("solid")
                }
                AppButton {
                    objectName: "ngThemeButton"
                    text: root.themeName === "dark" ? "深色" : "浅色"
                    ghost: true
                    onClicked: root.switchTheme(
                        root.themeName === "dark" ? "light" : "dark")
                }
                AppButton {
                    objectName: "ngMinButton"
                    text: "—"
                    ghost: true
                    onClicked: root.showMinimized()
                }
                AppButton {
                    objectName: "ngMaxButton"
                    text: root.visibility === Window.Maximized ? "❐" : "□"
                    ghost: true
                    onClicked: root.visibility === Window.Maximized
                        ? root.showNormal() : root.showMaximized()
                }
                AppButton {
                    objectName: "ngCloseButton"
                    text: "×"
                    ghost: true
                    onClicked: root.close()
                }
            }
        }

        // --- Native-kind row (Acrylic vs Mica) + live status ----------------
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 30

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: 8

                Text {
                    text: "原生材质："
                    font.pixelSize: 11
                    color: Theme.tokens.color.textSecondary
                }
                AppButton {
                    objectName: "ngAcrylicButton"
                    text: "Desktop Acrylic"
                    ghost: true
                    selected: root.nativeKind === "acrylic"
                    enabled: root.nativeSupported
                    onClicked: root.switchNativeKind("acrylic")
                }
                AppButton {
                    objectName: "ngMicaButton"
                    text: "Mica"
                    ghost: true
                    selected: root.nativeKind === "mica"
                    enabled: root.nativeSupported
                    onClicked: root.switchNativeKind("mica")
                }

                Item { Layout.fillWidth: true }

                Text {
                    objectName: "ngLiveStatus"
                    text: {
                        if (!root.nativeSupported) {
                            return "原生不可用：" + (typeof NativeGlassBridge !== "undefined"
                                ? NativeGlassBridge.unsupportedReason : "未知")
                        }
                        if (root.nativeActive) {
                            return "DWM " + root.activeKind + " 已生效"
                        }
                        return root.statusReason.length > 0
                            ? root.statusReason : "原生未启用"
                    }
                    font.pixelSize: 11
                    color: root.nativeActive
                        ? Theme.tokens.color.success : Theme.tokens.color.textSecondary
                }
            }
        }

        // --- Three-column body ---------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10
            Layout.leftMargin: 10
            Layout.rightMargin: 10

            // 1. Left navigation (decorative).
            LabPanel {
                objectName: "ngNavPanel"
                Layout.preferredWidth: 56
                Layout.fillHeight: true
                radius: 12
                translucency: 0.40
                panelName: "ngNav"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.topMargin: 10
                    anchors.bottomMargin: 10
                    spacing: 6
                    Repeater {
                        model: ["\u270E", "\u25A4", "\u2726", "\u2699"]
                        delegate: IconButton {
                            Layout.preferredWidth: 44
                            Layout.preferredHeight: 42
                            Layout.alignment: Qt.AlignHCenter
                            iconText: modelData
                            text: modelData
                            selected: index === 0
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            // 2. Chapter list (decorative).
            LabPanel {
                objectName: "ngChapterPanel"
                Layout.preferredWidth: 170
                Layout.fillHeight: true
                radius: 12
                translucency: 0.50
                panelName: "ngChapter"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8
                    Text {
                        text: "雾港来信"
                        font.pixelSize: 13
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                    }
                    Repeater {
                        model: ["第一章 渡轮", "第二章 灯塔", "第三章 旧信",
                                "第四章 潮汐", "第五章 归航"]
                        delegate: Text {
                            text: modelData
                            font.pixelSize: 11
                            color: index === 0
                                ? Theme.tokens.color.accent
                                : Theme.tokens.color.textSecondary
                            Layout.fillWidth: true
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            // 3. Central manuscript (high-opacity reading surface).
            PaperSurface {
                objectName: "ngManuscript"
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 12

                Flickable {
                    id: manuscriptFlick
                    anchors.fill: parent
                    anchors.margins: 18
                    contentWidth: width
                    contentHeight: manuscriptText.implicitHeight
                    clip: true

                    Text {
                        id: manuscriptText
                        objectName: "ngManuscriptText"
                        width: manuscriptFlick.width
                        font.family: Theme.tokens.font.manuscript
                        font.pixelSize: 15
                        lineHeight: 1.75
                        wrapMode: Text.Wrap
                        color: Theme.tokens.color.textPrimary
                        text: "第一章 渡轮\n\n"
                            + "雾从海面漫上来的时候，渡轮正缓缓靠向十七号码头。"
                            + "林默站在船舷边，看远处灯塔的光晕被水汽揉成一团模糊的暖色。"
                            + "这是他离开雾港十二年后的第一次回来，口袋里那封没有署名的信，"
                            + "已经被他反复摩挲得起了毛边。\n\n"
                            + "甲板上有个孩子指着水面喊：“看，海豚！”"
                            + "人群呼啦一下涌过去，林默却没有动。他记得小时候听人说，"
                            + "雾港的雾里藏着一座只在退潮时出现的旧城，"
                            + "每个在月圆之夜出生的人，都会在某个清晨听见城门的钟声。\n\n"
                            + "他原本不信。直到七岁那年，他在沙滩上捡到一枚刻着陌生姓氏的银币，"
                            + "而母亲的脸色，在看见那枚银币的瞬间白得像纸。\n\n"
                            + "渡轮靠岸的汽笛声响起，岸上的人群开始移动。"
                            + "林默把信重新放回内袋，走向那片他以为再也不会踏上的土地。"
                            + "雾港的雾比记忆里更浓，浓到连路灯都只能照亮一小圈潮湿的光。\n\n"
                            + "码头的旧钟楼上，有人正看着他。\n\n"
                            + "（测试文本：用于验证正文区在原生毛玻璃、应用内玻璃与纯色三种模式下的阅读清晰度。"
                            + "本实验不读取、不写入任何真实章节数据。）"
                    }
                }

                GlassScrollbar {
                    flickable: manuscriptFlick
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.right: parent.right
                    anchors.topMargin: 4
                    anchors.bottomMargin: 4
                    anchors.rightMargin: 2
                }
            }

            // 4. Right Agent test panel (three translucency tiers).
            LabPanel {
                objectName: "ngAgentPanel"
                Layout.preferredWidth: 290
                Layout.fillHeight: true
                radius: 12
                translucency: 0.45
                panelName: "ngAgent"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    Text {
                        text: "AI 测试面板"
                        font.pixelSize: 13
                        font.bold: true
                        color: Theme.tokens.color.textPrimary
                    }

                    // Status card (high translucency).
                    LabPanel {
                        objectName: "ngCardStatus"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 76
                        radius: 10
                        translucency: 0.30
                        panelName: "ngCardStatus"

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8
                            Rectangle {
                                width: 10
                                height: 10
                                radius: 5
                                color: Theme.tokens.agent.thinkingA
                            }
                            Text {
                                text: "剧情商讨中 · Thinking"
                                font.pixelSize: 11
                                color: Theme.tokens.color.textPrimary
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: "Mock"
                                font.pixelSize: 10
                                color: Theme.tokens.color.textSecondary
                            }
                        }
                    }

                    // Candidate card (medium translucency).
                    LabPanel {
                        objectName: "ngCardCandidates"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 140
                        radius: 10
                        translucency: 0.55
                        panelName: "ngCardCandidates"

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 8
                            Text {
                                text: "候选走向"
                                font.pixelSize: 12
                                font.bold: true
                                color: Theme.tokens.color.textPrimary
                            }
                            Repeater {
                                model: ["A. 旧城钟声响起", "B. 银币主人现身", "C. 信是母亲写的"]
                                delegate: Text {
                                    text: modelData
                                    font.pixelSize: 11
                                    color: Theme.tokens.color.textSecondary
                                    Layout.fillWidth: true
                                }
                            }
                        }
                    }

                    // Action card (low translucency).
                    LabPanel {
                        objectName: "ngCardActions"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 96
                        radius: 10
                        translucency: 0.75
                        panelName: "ngCardActions"

                        Flow {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 6
                            AppButton { text: "采纳" ; primary: true }
                            AppButton { text: "改写" }
                            AppButton { text: "拒绝"; ghost: true }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    Text {
                        text: "右栏卡片透明度：状态 0.30 / 候选 0.55 / 操作 0.75"
                        font.pixelSize: 10
                        color: Theme.tokens.color.textSecondary
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }
        }

        // --- Status bar -----------------------------------------------------
        Rectangle {
            id: statusBar
            objectName: "ngStatusBar"
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            color: Theme.tokens.color.bgSurface
            border.color: Theme.tokens.color.border
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 12

                Text {
                    text: "模式：" + root.mode + (root.nativeActive ? "（DWM " + root.activeKind + "）" : "")
                    font.pixelSize: 10
                    color: Theme.tokens.color.textSecondary
                }
                Text {
                    text: "平台：" + (typeof NativeGlassBridge !== "undefined"
                        ? NativeGlassBridge.platformName : "-")
                    font.pixelSize: 10
                    color: Theme.tokens.color.textSecondary
                }
                Text {
                    text: "Build：" + (typeof NativeGlassBridge !== "undefined"
                        ? NativeGlassBridge.buildText : "-")
                    font.pixelSize: 10
                    color: Theme.tokens.color.textSecondary
                }
                Text {
                    text: "透明效果：" + (typeof NativeGlassBridge !== "undefined"
                        ? (NativeGlassBridge.transparencyEffects ? "开" : "关") : "-")
                    font.pixelSize: 10
                    color: Theme.tokens.color.textSecondary
                }
                Text {
                    text: "FPS：" + root.fpsEstimate.toFixed(0)
                    font.pixelSize: 10
                    color: Theme.tokens.color.textSecondary
                }
                Text {
                    text: "后端：" + (typeof RenderBackendInfo !== "undefined"
                        ? RenderBackendInfo : "unknown")
                    font.pixelSize: 10
                    color: Theme.tokens.color.textSecondary
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: "隔离实验 · 不写入业务数据"
                    font.pixelSize: 10
                    color: Theme.tokens.color.textSecondary
                }
            }
        }
    }
}
