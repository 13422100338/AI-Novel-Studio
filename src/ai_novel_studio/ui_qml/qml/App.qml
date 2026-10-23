import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "pages"
import "surfaces"

ApplicationWindow {
    id: window
    objectName: "f1Window"

    width: 1440
    height: 900
    minimumWidth: 1100
    minimumHeight: 680
    visible: true
    title: "AI Novel Studio"
    // Production-shell system backdrop (DWM Desktop Acrylic): the Python
    // bootstrap exposes UseNativeGlass only when the machine supports it.
    // The optional material becomes transparent only while the bridge reports
    // nativeActive; themed window controls also work on the opaque canvas.
    property bool nativeGlass: typeof UseNativeGlass !== "undefined" && UseNativeGlass
    readonly property bool nativeActive:
        typeof NativeGlassBridge !== "undefined" && NativeGlassBridge.nativeActive
    flags: Qt.Window | Qt.FramelessWindowHint
    color: window.nativeGlass && window.nativeActive
        ? "transparent" : Theme.tokens.color.bgCanvas
    font.family: Theme.tokens.font.ui

    property bool sidebarVisible: true
    property bool useWebEngine: WritingPageUseWebEngine
    property string lastEditorChapterId: ""
    readonly property bool outlineActive: Facade.activeNav === "outline"
    readonly property bool notesActive: Facade.activeNav === "notes"
    readonly property string activeSaveState: notesActive
        ? (Facade.notes.state.dirty ? (Facade.notes.state.error ? "CONFLICT" : "DIRTY") : "CLEAN")
        : outlineActive
        ? (Facade.outline.state.dirty ? (Facade.outline.state.error ? "CONFLICT" : "DIRTY") : "CLEAN")
        : Facade.editorState

    onClosing: function(close) {
        if (!Facade.outline.flush()) {
            close.accepted = false
            Facade.setActiveNav("outline")
        } else if (!Facade.notes.flush()) {
            close.accepted = false
            Facade.setActiveNav("notes")
        }
    }

    // Helper: theme hex string -> rgba with alpha (window wash over the DWM
    // material, same value as the Native Glass Lab).
    function tint(color: color, alpha: real): color {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }

    function navTitle(navId) {
        const map = {
            "writing": "写作",
            "outline": "大纲",
            "notes": "笔记",
            "library": "旧资料",
            "advanced": "旧资料 · 高级视图",
            "settings": "设置"
        }
        return map[navId] || "写作"
    }

    function navIndex(navId) {
        const map = {
            "writing": 0,
            "outline": 4,
            "notes": 5,
            "library": 1,
            "advanced": 2,
            "settings": 3
        }
        return map[navId] || 0
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

    // Native-glass wash: a light theme tint over the DWM backdrop so text
    // stays readable while the desktop still shows through (alpha 0.15,
    // measured in the Native Glass Lab: 0.15*canvas + 0.85*acrylic keeps the
    // material clearly visible while keeping contrast).
    Rectangle {
        id: windowWash
        objectName: "f1WindowWash"
        anchors.fill: parent
        visible: window.nativeGlass && window.nativeActive
        color: window.tint(Theme.tokens.color.bgCanvas, 0.15)
        z: 0
    }

    // App-controlled backdrop. The production shell is now flat (clean modern
    // design): all chrome surfaces render opaque via AcrylicSurface's
    // opaqueFallback, so this decorative layer stays hidden and costs no GPU.
    // The object is kept (same wiring) because chrome surfaces still reference
    // it as their sourceItem and the native-glass path keys off it.
    BackdropLayer {
        id: backgroundLayer
        objectName: "f1BackgroundLayer"
        anchors.fill: parent
        visible: false
        washEnabled: false
    }

    WindowResizeHandles { targetWindow: window }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Theme-matched chrome keeps the desktop caption in the same paper
        // language as the footer; system move/resize still use native APIs.
        Item {
            id: glassTitleBar
            objectName: "glassTitleBar"
            visible: true
            Layout.fillWidth: true
            Layout.preferredHeight: 36

            Rectangle { objectName: "windowTitleSurface"; anchors.fill: parent; color: Theme.tokens.color.bgSurface }
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.tokens.color.border }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                onDoubleClicked: window.visibility === Window.Maximized ? window.showNormal() : window.showMaximized()
                onPressed: {
                    if (typeof window.startSystemMove === "function") {
                        window.startSystemMove()
                    }
                }
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 8
                spacing: 6

                Text {
                    text: "AI Novel Studio"
                    font.pixelSize: 13
                    font.bold: true
                    color: Theme.tokens.color.textPrimary
                }

                Item { Layout.fillWidth: true }

                AppButton {
                    objectName: "glassMinButton"
                    text: "—"
                    Accessible.name: "最小化"
                    implicitWidth: 36
                    implicitHeight: 28
                    ghost: true
                    onClicked: window.showMinimized()
                }
                AppButton {
                    objectName: "glassMaxButton"
                    text: window.visibility === Window.Maximized ? "❐" : "□"
                    Accessible.name: "最大化或还原"
                    implicitWidth: 36
                    implicitHeight: 28
                    ghost: true
                    onClicked: window.visibility === Window.Maximized
                        ? window.showNormal() : window.showMaximized()
                }
                AppButton {
                    objectName: "glassCloseButton"
                    text: "×"
                    Accessible.name: "关闭窗口"
                    implicitWidth: 36
                    implicitHeight: 28
                    ghost: true
                    onClicked: window.close()
                }
            }
        }

        Item {
            objectName: "workspaceToolbar"
            Layout.fillWidth: true
            Layout.preferredHeight: 46
            WorkspaceTabs {
                anchors.centerIn: parent
                width: Math.min(300, parent.width - 32)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 12
            spacing: 10

            // Sidebar host: flat opaque panel (clean modern shell). The
            // backdrop wiring is kept so the native-glass experiment and the
            // structural shell contract stay intact.
            // Width switches stay one-step: animating the layout
            // cell resizes the WebEngine editor frame by frame.
            AcrylicSurface {
                id: sidebarHost
                objectName: "sidebarHost"
                Layout.preferredWidth: window.sidebarVisible
                    ? (window.width < 1280 ? (window.outlineActive ? 190 : 240) : 280) : 0
                Layout.fillHeight: true
                sourceItem: backgroundLayer
                opaqueFallback: true
                radius: 16
                clip: true

                // Sidebar width switches in one step: animating the layout cell
                // resizes the WebEngine editor every frame (ideal-UI spec 10.1).
                ContextSidebar {
                    anchors.fill: parent
                }
            }

            Rectangle {
                objectName: "workspaceHost"
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.tokens.color.bgCanvas

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 6
                    StackLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: window.navIndex(Facade.activeNav)

                        WritingPage {
                            id: writingPage
                            useWebEngine: window.useWebEngine
                            backdropSource: backgroundLayer
                        }

                        MemoryLibraryPage {}

                        AdvancedCreationPage {}

                        SettingsPage {}

                        OutlinePage { id: outlinePage }
                        NotesPage {}
                    }
                }
            }

            AgentDock {
                open: Facade.aiDrawerOpen
                windowWidth: window.width
                defaultWidth: window.width < 1280 ? 330 : 380
                // Reserve a usable document column even after dragging the dock wider.
                maxWidth: Math.max(320, Math.min(window.width * 0.45,
                    window.width - sidebarHost.width - 408))
                backdropSource: backgroundLayer
                onClosed: Facade.toggleAiDrawer(false)
            }

        }

        Rectangle {
            id: statusBar
            objectName: "windowStatusSurface"
            Layout.fillWidth: true
            Layout.preferredHeight: 40
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

                AppButton {
                    objectName: "statusMoreButton"
                    text: "状态 ⌄"
                    ghost: true
                    onClicked: moreMenu.open()
                }

                StatusChip {
                    objectName: "wordCountStatusChip"
                    label: window.notesActive ? "笔记" : window.outlineActive ? "大纲" : "字数"
                    value: window.notesActive ? Facade.notes.state.text.length.toLocaleString() + " 字符"
                        : window.outlineActive ? Facade.outline.state.text.length.toLocaleString() + " 字符"
                        : window.useWebEngine ? Facade.webEngineWordCountText : Facade.currentWordCountText
                    tone: "accent"
                }
                StatusChip {
                    objectName: "autoSaveStatusChip"
                    label: window.notesActive ? "笔记保存" : "自动保存"
                    value: window.notesActive ? (Facade.notes.state.loaded ? (Facade.notes.state.dirty ? "未保存" : "已保存") : "未载入")
                        : window.outlineActive && !Facade.outline.state.loaded ? "未载入" : window.autoSaveText(window.activeSaveState)
                    tone: window.notesActive && !Facade.notes.state.loaded ? "neutral"
                        : window.outlineActive && !Facade.outline.state.loaded ? "neutral" : window.autoSaveTone(window.activeSaveState)
                }
                StatusChip {
                    label: "任务"
                    value: window.draftText(Facade.draftStatus)
                    tone: Facade.draftStatus === "GENERATING" || Facade.draftStatus === "QUEUED" ? "accent"
                        : Facade.draftStatus === "FAILED" || Facade.draftStatus === "CANCELLED" ? "danger"
                        : "neutral"
                }
                StatusChip {
                    objectName: "modelStatusChip"
                    label: Facade.codexEnabled ? "写作模型" : "模型"
                    value: typeof ModelSettingsReady !== "undefined"
                           && ModelSettingsReady
                        ? ModelSettings.modelStatusText
                        : Facade.modelStatusText
                    tone: value === "模型 已配置" ? "accent" : "neutral"
                }
                Item {
                    Layout.fillWidth: true
                }
                AppButton {
                    id: settingsButton
                    objectName: "nav-settings"
                    implicitWidth: 32
                    implicitHeight: 30
                    padding: 5
                    ghost: true
                    selected: Facade.activeNav === "settings"
                    Accessible.name: "设置"
                    ToolTip.visible: hovered
                    ToolTip.text: "设置"
                    onClicked: Facade.setActiveNav("settings")
                    contentItem: Item {
                        NavIcon {
                            anchors.centerIn: parent
                            kind: "settings"
                            iconColor: settingsButton.selected ? "white" : Theme.tokens.color.textSecondary
                        }
                    }
                }
            }
        }

        Popup {
            id: moreMenu
            objectName: "statusMoreMenu"
            parent: Overlay.overlay
            x: 12
            y: Math.max(12, parent.height - height - 46)
            width: 300
            padding: 18
            focus: true
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
            background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 14 }
            contentItem: ColumnLayout {
                spacing: 12
                Text { text: "当前状态"; font.pixelSize: 16; font.bold: true; color: Theme.tokens.color.textPrimary }
                Text { text: "Token：" + Facade.usageInputOutputText; font.pixelSize: 13; color: Theme.tokens.color.textSecondary }
                Text { text: "费用：" + Facade.usageCostText; font.pixelSize: 13; color: Theme.tokens.color.textSecondary }
                Text { text: "缓存：" + Facade.usageCacheText; font.pixelSize: 13; color: Theme.tokens.color.textSecondary }
                Text {
                    text: "数据源：" + (Facade.projectSource === "project" ? "当前项目" : Facade.projectSource === "mock" ? "演示" : "未打开项目")
                    font.pixelSize: 13
                    color: Theme.tokens.color.textSecondary
                }
            }
        }
    }

    // DWM first-show race (same as the Native Glass Lab): the window can
    // briefly lose the material when Qt rebuilds the native handle. Retry a
    // few times while the shell is visible and native is requested.
    property int nativeRetryCount: 0
    Timer {
        interval: 300
        repeat: true
        running: window.visible && window.nativeGlass && window.nativeActive !== true
            && window.nativeRetryCount < 5
        onTriggered: {
            if (typeof NativeGlassBridge !== "undefined") {
                window.nativeRetryCount += 1
                const ok = NativeGlassBridge.refresh()
                if (ok) {
                    window.nativeRetryCount = 5
                }
            }
        }
    }
    onNativeActiveChanged: {
        if (window.nativeActive) {
            window.nativeRetryCount = 5
        }
    }
    onVisibleChanged: {
        if (window.visible && window.nativeGlass
                && typeof NativeGlassBridge !== "undefined") {
            NativeGlassBridge.refresh()
        }
    }
    onActiveChanged: {
        if (window.active && window.nativeGlass
                && typeof NativeGlassBridge !== "undefined") {
            NativeGlassBridge.refresh()
        }
    }

    // Keep the DWM immersive dark tint in sync with the app theme.
    Connections {
        target: Theme
        function onTokensChanged() {
            if (typeof NativeGlassBridge !== "undefined") {
                NativeGlassBridge.setDarkMode(Theme.themeName === "dark")
            }
        }
    }

    Connections {
        target: Facade
        function onEvidenceRevealRequested(evidence, position, length) {
            writingPage.revealEvidence(position, length)
        }
        function onChapterChanged() {
            if (Facade.currentChapterId !== window.lastEditorChapterId) {
                window.lastEditorChapterId = Facade.currentChapterId
                writingPage.reloadFromFacade()
            }
        }
    }
}
