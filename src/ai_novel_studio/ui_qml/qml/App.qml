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
    // The window goes frameless + transparent only while the bridge reports
    // nativeActive; every failure path keeps the opaque theme canvas.
    property bool nativeGlass: typeof UseNativeGlass !== "undefined" && UseNativeGlass
    readonly property bool nativeActive:
        typeof NativeGlassBridge !== "undefined" && NativeGlassBridge.nativeActive
    flags: window.nativeGlass ? Qt.FramelessWindowHint : Qt.Window
    color: window.nativeGlass && window.nativeActive
        ? "transparent" : Theme.tokens.color.bgCanvas
    font.family: Theme.tokens.font.ui

    property bool sidebarVisible: true
    property bool useWebEngine: WritingPageUseWebEngine
    property string lastEditorChapterId: ""

    // Helper: theme hex string -> rgba with alpha (window wash over the DWM
    // material, same value as the Native Glass Lab).
    function tint(color: color, alpha: real): color {
        return Qt.rgba(color.r, color.g, color.b, alpha)
    }

    function navTitle(navId) {
        const map = {
            "writing": "写作",
            "library": "记忆库",
            "advanced": "高级创作",
            "settings": "设置"
        }
        return map[navId] || "写作"
    }

    function navIndex(navId) {
        const map = {
            "writing": 0,
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

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Custom title bar: only exists on the frameless native-glass shell.
        // Drag moves the window; the three buttons use the window API.
        Item {
            id: glassTitleBar
            objectName: "glassTitleBar"
            visible: window.nativeGlass
            Layout.fillWidth: true
            Layout.preferredHeight: 40

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
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
                Text {
                    text: "F1"
                    font.pixelSize: 11
                    color: Theme.tokens.color.textSecondary
                }

                Item { Layout.fillWidth: true }

                AppButton {
                    objectName: "glassMinButton"
                    text: "—"
                    ghost: true
                    onClicked: window.showMinimized()
                }
                AppButton {
                    objectName: "glassMaxButton"
                    text: window.visibility === Window.Maximized ? "❐" : "□"
                    ghost: true
                    onClicked: window.visibility === Window.Maximized
                        ? window.showNormal() : window.showMaximized()
                }
                AppButton {
                    objectName: "glassCloseButton"
                    text: "×"
                    ghost: true
                    onClicked: window.close()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 12
            spacing: 10

            NavigationRail {
                Layout.preferredWidth: 64
                Layout.fillHeight: true
                backdropSource: backgroundLayer
            }

            // Sidebar host: flat opaque panel (clean modern shell). The
            // backdrop wiring is kept so the native-glass experiment and the
            // structural shell contract stay intact.
            // Width switches stay one-step: animating the layout
            // cell resizes the WebEngine editor frame by frame.
            AcrylicSurface {
                id: sidebarHost
                objectName: "sidebarHost"
                Layout.preferredWidth: window.sidebarVisible ? (window.width < 1280 ? 240 : 280) : 0
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

                StackLayout {
                    anchors.fill: parent
                    currentIndex: window.navIndex(Facade.activeNav)

                    WritingPage {
                        id: writingPage
                        useWebEngine: window.useWebEngine
                        backdropSource: backgroundLayer
                    }

                    MemoryLibraryPage {}

                    AdvancedCreationPage {}

                    SettingsPage {}
                }
            }

            AgentDock {
                open: Facade.aiDrawerOpen
                windowWidth: window.width
                backdropSource: backgroundLayer
                onClosed: Facade.toggleAiDrawer(false)
            }

        }

        Rectangle {
            id: statusBar
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

                StatusChip {
                    label: "字数"
                    value: window.useWebEngine ? Facade.webEngineWordCountText : Facade.currentWordCountText
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
                    objectName: "statusMoreButton"
                    text: "···"
                    onClicked: moreMenu.popup()
                }
            }
        }

        Menu {
            id: moreMenu
            objectName: "statusMoreMenu"

            MenuItem {
                text: "主题：" + Theme.themeName
                onTriggered: Theme.setTheme(Theme.nextThemeName())
            }
            MenuItem {
                text: Facade.reduceMotion ? "动效：开" : "动效：关"
                onTriggered: Facade.setReduceMotion(!Facade.reduceMotion)
            }
            MenuSeparator {}
            MenuItem {
                text: "Token：" + Facade.usageInputOutputText
                enabled: false
            }
            MenuItem {
                text: "费用：" + Facade.usageCostText
                enabled: false
            }
            MenuItem {
                text: "缓存：" + Facade.usageCacheText
                enabled: false
            }
            MenuItem {
                text: "数据源：" + (Facade.projectSource === "project" ? "项目"
                    : Facade.projectSource === "mock" ? "演示" : "未打开")
                enabled: false
            }
        }
    }

    // Frameless resize edges/corners (native-glass shell only). They call the
    // OS resize loop so DWM keeps the acrylic material during the drag.
    Item {
        anchors.fill: parent
        visible: window.nativeGlass
        z: 100

        MouseArea {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 6
            cursorShape: Qt.SizeVerCursor
            onPressed: window.startSystemResize(Qt.TopEdge)
        }
        MouseArea {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 6
            cursorShape: Qt.SizeVerCursor
            onPressed: window.startSystemResize(Qt.BottomEdge)
        }
        MouseArea {
            anchors { top: parent.top; bottom: parent.bottom; left: parent.left }
            width: 6
            cursorShape: Qt.SizeHorCursor
            onPressed: window.startSystemResize(Qt.LeftEdge)
        }
        MouseArea {
            anchors { top: parent.top; bottom: parent.bottom; right: parent.right }
            width: 6
            cursorShape: Qt.SizeHorCursor
            onPressed: window.startSystemResize(Qt.RightEdge)
        }
        MouseArea {
            anchors { left: parent.left; top: parent.top }
            width: 12
            height: 12
            cursorShape: Qt.SizeFDiagCursor
            onPressed: window.startSystemResize(Qt.LeftEdge | Qt.TopEdge)
        }
        MouseArea {
            anchors { right: parent.right; top: parent.top }
            width: 12
            height: 12
            cursorShape: Qt.SizeBDiagCursor
            onPressed: window.startSystemResize(Qt.RightEdge | Qt.TopEdge)
        }
        MouseArea {
            anchors { left: parent.left; bottom: parent.bottom }
            width: 12
            height: 12
            cursorShape: Qt.SizeBDiagCursor
            onPressed: window.startSystemResize(Qt.LeftEdge | Qt.BottomEdge)
        }
        MouseArea {
            anchors { right: parent.right; bottom: parent.bottom }
            width: 12
            height: 12
            cursorShape: Qt.SizeFDiagCursor
            onPressed: window.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
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
