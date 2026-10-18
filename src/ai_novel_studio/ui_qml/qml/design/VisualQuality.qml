import QtQuick

// Visual quality helpers (ideal-UI spec 11): Safe / Balanced / Premium.
// QML surfaces read these booleans instead of comparing the raw string so the
// quality policy lives in one place. The active value comes from ThemeProvider
// (single source, also visible in the Visual V0 lab page).
QtObject {
    id: root

    readonly property bool safe: Theme.visualQuality === "safe"
    readonly property bool balanced: Theme.visualQuality === "balanced"
    readonly property bool premium: Theme.visualQuality === "premium"
}
