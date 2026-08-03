
    import QtQuick
    import "components"
    Item {
        objectName: "probe"
        property bool modeOk: drawer.webEngineMode === true
        property SlidingDrawer drawer: SlidingDrawer {
            webEngineMode: true
        }
    }
    