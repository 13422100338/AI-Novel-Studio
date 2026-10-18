import QtQuick

// GlassScrollbar — 垂直滚动条范本（窗口最右侧那种），玻璃语言。
// 用户澄清：上一轮做的底部可拖面板不是目标，目标是垂直滚动条。
//
// Skill 驱动的关键行为（apple-design / emil-design-eng / review-animations，
// 自审见 glassmorphism-ui-log.md §19）：
// - thumb 高度 = 视口/内容比例，位置 = contentY 归一化映射，全程 1:1 绑定
//   （直接操作，无动画干扰拖动）；
// - 拖动 thumb 反向写回 flickable.contentY（含指针起点偏移，尊重抓取位置）；
// - 点击轨道在点击处前后翻一屏（点击上方向上、下方向下），不跳远；
// - hover 只做 opacity 0.55→1.0（120ms，仅合成属性，reduceMotion 时 0）；
// - 档位：Safe 实色 thumb / 无轨道；Balanced 半透明玻璃 thumb + 淡轨道；
//   Premium thumb 渐变 + 顶部 1px 高光（light catching the material）；
// - 内容不超高时整条隐藏（功能完整但无可滚动内容，符合 §12.3）。
Item {
    id: root
    objectName: "glassScrollbar"

    // The scrollable this bar drives. Geometry bindings below keep the thumb
    // glued to the flickable in both directions (drag -> contentY and
    // contentY -> thumb) with no animation in the loop.
    required property Flickable flickable

    implicitWidth: 14
    readonly property real trackHeight: root.flickable ? root.flickable.height : 0
    readonly property bool visibleWhen:
        root.flickable && root.flickable.contentHeight > root.flickable.height + 1
    readonly property real thumbHeight: Math.max(
        24,
        root.trackHeight
            * (root.flickable.height / Math.max(1, root.flickable.contentHeight))
    )
    readonly property real scrollableRange: Math.max(
        1,
        root.flickable.contentHeight - root.flickable.height
    )
    readonly property real thumbRange: Math.max(1, root.trackHeight - root.thumbHeight)
    readonly property real thumbY:
        (root.flickable.contentY / root.scrollableRange) * root.thumbRange
    readonly property real normalized:
        root.flickable.contentY / root.scrollableRange
    readonly property bool springEnabled:
        typeof Facade !== "undefined" && Facade ? !Facade.reduceMotion : false

    property real dragStartY: 0
    property real dragStartContentY: 0
    property bool thumbDragging: false
    property color thumbColor: Theme.tokens.color.accent

    visible: root.visibleWhen
    enabled: root.visibleWhen

    // Set the flickable position from a pointer position inside this bar:
    // 1:1 with the grab offset preserved (apple-design §2).
    function setFromPointer(localY) {
        if (!root.flickable) {
            return
        }
        var targetContentY = root.dragStartContentY
            + (localY - root.dragStartY)
                * (root.scrollableRange / root.thumbRange)
        root.flickable.contentY = Math.max(
            0,
            Math.min(root.flickable.contentHeight - root.flickable.height, targetContentY)
        )
    }

    // Track: glass hairline. Safe tier has no track (thumb only).
    Rectangle {
        anchors.fill: parent
        visible: Theme.visualQuality !== "safe"
        radius: 4
        color: Qt.rgba(
            root.thumbColor.r,
            root.thumbColor.g,
            root.thumbColor.b,
            Theme.visualQuality === "premium" ? 0.10 : 0.08
        )
        border.width: 1
        border.color: Theme.tokens.color.border
        opacity: 0.9
    }

    // Thumb: rounded glass pill, hover brightens (opacity only).
    Rectangle {
        id: thumb
        objectName: "glassScrollbarThumb"
        width: 6
        height: root.thumbHeight
        radius: 3
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.thumbY
        color: Theme.visualQuality === "premium" ? "transparent" : root.thumbColor
        gradient: Theme.visualQuality === "premium" ? thumbGradient : null
        opacity: root.thumbDragging || dragArea.containsMouse ? 1.0 : 0.55

        Behavior on opacity {
            NumberAnimation {
                duration: root.springEnabled ? 120 : 0
                easing.type: Easing.OutCubic
            }
        }

        Gradient {
            id: thumbGradient
            GradientStop {
                position: 0.0
                color: Qt.lighter(root.thumbColor, 1.45)
            }
            GradientStop {
                position: 1.0
                color: root.thumbColor
            }
        }

        // Premium rim: bright top edge = light catching the material.
        Rectangle {
            visible: Theme.visualQuality === "premium"
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.topMargin: 1
            anchors.leftMargin: 2
            anchors.rightMargin: 2
            height: 1
            radius: 1
            color: Qt.rgba(1, 1, 1, 0.6)
        }
    }

    MouseArea {
        id: dragArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor

        onPressed: {
            if (mouse.y >= thumb.y && mouse.y <= thumb.y + thumb.height) {
                // Grab the thumb, preserving the grab offset.
                root.thumbDragging = true
                root.dragStartY = mouse.y
                root.dragStartContentY = root.flickable.contentY
            } else {
                // Track click: page by one viewport in the click direction.
                var target = root.flickable.contentY
                    + (mouse.y < thumb.y ? -1 : 1) * root.flickable.height
                root.flickable.contentY = Math.max(
                    0,
                    Math.min(
                        root.flickable.contentHeight - root.flickable.height,
                        target
                    )
                )
            }
        }
        onPositionChanged: {
            if (root.thumbDragging) {
                root.setFromPointer(mouse.y)
            }
        }
        onReleased: root.thumbDragging = false
        onExited: root.thumbDragging = false
    }
}
