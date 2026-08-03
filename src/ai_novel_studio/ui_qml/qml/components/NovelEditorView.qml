import QtQuick
import QtWebEngine

WebEngineView {
    id: webView
    objectName: "novelEditorView"

    property url editorUrl: ""
    signal editorLoaded()

    profile: WebEngineProfile {
        id: editorProfile
        offTheRecord: true
    }

    webChannel: EditorChannel
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
