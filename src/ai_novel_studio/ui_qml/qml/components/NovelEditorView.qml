import QtQuick
import QtWebChannel
import QtWebEngine

WebEngineView {
    id: webView
    objectName: "novelEditorView"

    property var bridge: null
    property url editorUrl: ""
    signal editorLoaded()

    profile: QtWebEngineProfile {
        id: editorProfile
        offTheRecord: true
    }

    webChannel: QWebChannel {
        id: channel
        function rebind() {
            if (webView.bridge !== null) {
                registerObject("pythonBridge", webView.bridge)
            }
        }
        Component.onCompleted: rebind()
    }

    onBridgeChanged: channel.rebind()
    url: webView.editorUrl

    onLoadingChanged: {
        if (loadRequest.status === WebEngineView.LoadSucceededStatus) {
            webView.editorLoaded()
        }
    }

    function loadChapter(payloadJson) {
        runJavaScript(
            "window.__novelEditor && " +
            "window.__novelEditor.loadDocument(" + payloadJson + ")"
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
}

