import QtQuick
import QtWebChannel
import QtWebEngine

WebEngineView {
    id: webView
    objectName: "novelEditorView"

    property url editorUrl: ""
    signal editorLoaded()

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

    webChannel: editorChannel
    url: webView.editorUrl

    onLoadingChanged: function(loadRequest) {
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
