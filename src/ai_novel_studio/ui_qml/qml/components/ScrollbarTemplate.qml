import QtQuick
import QtQuick.Layouts
import "../surfaces"

// ScrollbarTemplate — 窗口最右侧的垂直滚动条范本（用户澄清的目标组件：
// “一般在窗口最右侧”的滚动条）。固定窄列放在四栏工作区最右：
//   - 玻璃面板（AcrylicSurface，与其它栏同源 BackdropLayer）；
//   - 一段足够长的 Mock 文稿（Flickable 滚动）；
//   - 右缘 GlassScrollbar：拖 thumb 1:1、点轨道翻页、hover 淡入；
//   - 档位：Safe 实色 thumb / Balanced 半透明玻璃 / Premium 渐变+rim；
//   - reduceMotion：hover 淡入改为 0ms，拖动始终 1:1 无动画。
Item {
    id: root
    objectName: "scrollbarTemplate"

    // Forward the lab backdrop so the panel blurs the same light source as
    // the other four columns (unified glass language, §14/§16).
    required property Item sourceItem

    implicitWidth: 230

    AcrylicSurface {
        id: glass
        objectName: "scrollbarTemplateSurface"
        anchors.fill: parent
        sourceItem: root.sourceItem
        radius: Theme.tokens.radius.r12

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: "滚动条范本 · 窗口最右侧"
                font.pixelSize: 12
                font.bold: true
                color: Theme.tokens.color.textPrimary
            }
            Text {
                Layout.fillWidth: true
                text: "拖 thumb 滚动 · 点轨道翻页 · hover 淡入 · Safe 实色 / Premium 玻璃渐变"
                font.pixelSize: 9
                lineHeight: 1.5
                wrapMode: Text.WordWrap
                color: Theme.tokens.color.textSecondary
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Theme.tokens.color.border
            }

            // Scrollable manuscript + the right-edge scrollbar.
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Flickable {
                    id: manuscriptFlickable
                    objectName: "scrollbarManuscript"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: manuscriptFlickable.width
                    contentHeight: manuscriptColumn.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    flickDeceleration: 1500

                    Column {
                        id: manuscriptColumn
                        width: manuscriptFlickable.width
                        spacing: 8

                        Repeater {
                            model: 18
                            delegate: Text {
                                width: manuscriptColumn.width
                                text: "第 " + (index + 1) + " 段 · 清晨的雾气还浸在灰蓝色的光线里。渡船靠岸时，甲板上的水汽把远处灯塔的光晕揉成一团模糊的暖色。林默把最后一封信塞进外套内袋，沿着湿漉漉的栈桥走进镇子。"
                                font.family: Theme.tokens.font.manuscript
                                font.pixelSize: 11
                                lineHeight: 1.6
                                wrapMode: Text.WordWrap
                                color: Theme.tokens.color.textPrimary
                            }
                        }
                    }
                }

                GlassScrollbar {
                    objectName: "glassScrollbar"
                    Layout.preferredWidth: 14
                    Layout.fillHeight: true
                    flickable: manuscriptFlickable
                    thumbColor: Theme.tokens.color.accent
                }
            }

            Text {
                Layout.fillWidth: true
                text: "拖动中 1:1 跟手 · 无动画干扰 · reduceMotion 下 hover 即时"
                font.pixelSize: 9
                color: Theme.tokens.color.textSecondary
            }
        }
    }
}
