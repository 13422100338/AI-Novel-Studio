import QtQuick
import QtWebChannel
import QtWebEngine

WebEngineView {
    id: webView
    objectName: "novelEditorView"

    property url editorUrl: ""
    property string pendingDocumentPayload: ""
    property int pendingDocumentAttempts: 0
    signal editorLoaded()
    // 2026-08-26 ticket: the host distinguishes page readiness from
    // deterministic parse failures. documentLoaded carries the fixed
    // {chapterId, revision, wordCount} projection; documentLoadFailed fires at
    // most once per attempt with UNSUPPORTED_MARKDOWN / PARSE_FAILED /
    // NOT_READY and is never retried for deterministic statuses.
    signal documentLoaded(string chapterId, int revision, int wordCount)
    signal documentLoadFailed(string reason)

    WebChannel {
        id: editorChannel
        Component.onCompleted: {
            registerObject("pythonBridge", pythonBridge)
        }
    }

    profile: WebEngineProfile {
        id: editorProfile
        offTheRecord: true
    }

    // Paint the view with the editor surface color on every resize/repaint;
    // otherwise QtWebEngine can show the default black canvas while the page
    // re-lays out during dock open/close (C1.5).
    // Fixed property: WebEngineView must not re-bind its canvas color to a
    // live bridge property at runtime (C1.5 / crash on capability emit).
    // Callers set editorSurfaceColor before/at load; default keeps theme.
    property color editorSurfaceColor: Theme.tokens.color.bgEditor
    backgroundColor: editorSurfaceColor

    webChannel: editorChannel
    url: webView.editorUrl

    // QtWebEngine composites asynchronously: after a width change the
    // renderer is not always notified to resize its surface, so the newly
    // exposed strip stays black until something forces a re-composite. The
    // nudge runs immediately (covers resizes Chromium has already processed)
    // and again after one short timer tick (covers the delayed notification).
    // It is a repaint trigger, not a reload (C1.5).
    function nudgeRepaint() {
        // The callback creates a renderer round-trip: without it the layout
        // read is fire-and-forget and Chromium still does not re-composite
        // the resized surface.
        webView.runJavaScript(
            "void(document.body.offsetHeight)",
            function() {}
        )
        webView.update()
    }

    Timer {
        id: resizeRepaintTimer
        interval: 25
        repeat: false
        onTriggered: webView.nudgeRepaint()
    }
    onWidthChanged: {
        if (webView.width > 0) {
            webView.nudgeRepaint()
            resizeRepaintTimer.restart()
        }
    }
    onHeightChanged: {
        if (webView.height > 0) {
            webView.nudgeRepaint()
            resizeRepaintTimer.restart()
        }
    }

    Connections {
        target: pythonBridge
        function onDocumentReady() {
            webView.editorLoaded()
            webView.flushPendingDocument()
        }
    }

    onLoadingChanged: function(loadRequest) {
        if (loadRequest.status === WebEngineView.LoadSucceededStatus) {
            webView.editorLoaded()
        }
    }

    Timer {
        id: documentLoadRetry
        interval: 50
        repeat: false
        onTriggered: webView.flushPendingDocument()
    }

    // The editor page ships paper-theme defaults in style.css (--editor-bg
    // #fffdf7), so without this the page stays beige in every theme. Push the
    // current Theme tokens into the page as CSS variables on load and on every
    // theme change, so html/body, scrollbars and ProseMirror all repaint with
    // the active theme.
    function applyCurrentTheme() {
        var tokens = {
            "--editor-bg": Theme.tokens.color.bgEditor,
            "--editor-text": Theme.tokens.color.textPrimary,
            "--editor-accent": Theme.tokens.color.accent,
            "--editor-muted": Theme.tokens.color.textSecondary,
        }
        runJavaScript(
            "window.__novelEditor && " +
            "window.__novelEditor.applyTheme(" + JSON.stringify(tokens) + ")"
        )
    }

    Connections {
        target: Theme
        function onTokensChanged() {
            webView.applyCurrentTheme()
        }
    }

    Connections {
        target: webView
        function onEditorLoaded() {
            webView.applyCurrentTheme()
        }
    }

    function loadChapter(payloadJson) {
        pendingDocumentPayload = payloadJson
        pendingDocumentAttempts = 0
        flushPendingDocument()
    }

    function flushPendingDocument() {
        if (pendingDocumentPayload === "") {
            return
        }
        var payload = pendingDocumentPayload
        runJavaScript(
            "(function() {" +
            " try {" +
            " if (!window.__novelEditor) { return null; }" +
            " return JSON.stringify(window.__novelEditor.loadDocument(" + payload + "));" +
            " } catch (e) {" +
            " return JSON.stringify({status: 'PARSE_FAILED', chapterId: '', revision: 0, wordCount: 0});" +
            " }" +
            "})()",
            function(resultJson) {
                if (resultJson === undefined || resultJson === null || resultJson === "") {
                    // NOT_READY: page or bridge not mounted yet. This is the
                    // only branch allowed to retry, and only within a short
                    // bounded window.
                    webView.pendingDocumentAttempts += 1
                    if (webView.pendingDocumentAttempts < 40) {
                        documentLoadRetry.restart()
                        return
                    }
                    webView.pendingDocumentPayload = ""
                    webView.pendingDocumentAttempts = 0
                    webView.documentLoadFailed("NOT_READY")
                    return
                }
                webView.pendingDocumentPayload = ""
                var result = JSON.parse(resultJson)
                if (result.status === "LOADED") {
                    webView.pendingDocumentAttempts = 0
                    webView.documentLoaded(result.chapterId, result.revision, result.wordCount)
                    return
                }
                // Deterministic failure: report once, never retry.
                webView.pendingDocumentAttempts = 0
                webView.documentLoadFailed(result.status)
            }
        )
    }

    function requestSave() {
        runJavaScript("window.__novelEditor && window.__novelEditor.requestSave()")
    }

    function applyTheme(tokensJson) {
        runJavaScript(
            "window.__novelEditor && " +
            "window.__novelEditor.applyTheme(" + tokensJson + ")"
        )
    }

    function revealRange(from, to) {
        runJavaScript(
            "window.__novelEditor && " +
            "window.__novelEditor.revealRange(" + from + ", " + to + ")"
        )
    }

    function setBaseRevision(revision) {
        runJavaScript(
            "window.__novelEditor && " +
            "window.__novelEditor.setBaseRevision(" + revision + ")"
        )
    }
}
