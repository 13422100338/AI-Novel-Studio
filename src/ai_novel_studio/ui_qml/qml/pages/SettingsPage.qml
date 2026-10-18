import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    objectName: "settingsPage"
    readonly property bool codexEnabled: typeof Facade !== "undefined" && Facade.codexEnabled

    // The page is usable only when the bootstrap registered the bridge
    // (real app). Standalone shells/tests without it see the honest
    // placeholder instead of a dead form.
    readonly property bool bridgeReady:
        typeof ModelSettings !== "undefined" && ModelSettings !== null

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        Text {
            text: "模型与连接"
            font.pixelSize: 22
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        Rectangle {
            visible: root.codexEnabled
            Layout.fillWidth: true
            implicitHeight: codexSettingsBox.implicitHeight + 24
            color: Theme.tokens.color.bgSurface
            radius: Theme.tokens.radius.r12
            border.color: Theme.tokens.color.border
            ColumnLayout {
                id: codexSettingsBox
                anchors.fill: parent
                anchors.margins: 12
                Text {
                    text: "Codex 助手"
                    font.pixelSize: 15
                    font.bold: true
                    color: Theme.tokens.color.textPrimary
                }
                CodexControls { Layout.fillWidth: true; details: true }
                Text {
                    Layout.fillWidth: true
                    text: "使用已登录的 ChatGPT 账号，管理对话、资料检索与小说规划。"
                    wrapMode: Text.WordWrap
                    color: Theme.tokens.color.textSecondary
                    font.pixelSize: 12
                }
            }
        }

        EmptyState {
            visible: !root.bridgeReady
            Layout.fillWidth: true
            title: "模型设置不可用"
            body: "当前运行环境未注册模型配置桥接。"
        }

        Text {
            visible: root.bridgeReady
            text: "独立写作模型"
            font.pixelSize: 15
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        Loader {
            visible: root.bridgeReady
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: root.bridgeReady ? settingsForm : null
        }
    }

    Component {
        id: settingsForm

        GridLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: root.width < 580 ? 1 : 2
            rowSpacing: 12
            columnSpacing: 14

            // -- provider list -------------------------------------------------
            Rectangle {
                Layout.preferredWidth: root.width < 580 ? -1 : 200
                Layout.preferredHeight: root.width < 580 ? 162 : -1
                Layout.fillWidth: root.width < 580
                Layout.fillHeight: root.width >= 580
                radius: Theme.tokens.radius.r12
                color: Theme.tokens.color.bgSurface
                border.color: Theme.tokens.color.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            Layout.fillWidth: true
                            text: "写作连接"
                            font.pixelSize: 14
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                        }
                        AppButton {
                            objectName: "addProviderButton"
                            text: "+ 新增"
                            onClicked: ModelSettings.beginNewProvider()
                        }
                    }

                    ListView {
                        id: providerList
                        objectName: "providerList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: ModelSettings.providers

                        delegate: Item {
                            width: providerList.width
                            height: 48
                            required property var modelData
                            Rectangle {
                                anchors.fill: parent
                                radius: Theme.tokens.radius.r8
                                color: ModelSettings.currentProviderId === modelData.id
                                    ? Theme.tokens.color.pressed : area.containsMouse
                                    ? Theme.tokens.color.hover : "transparent"
                            }
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.name
                                    elide: Text.ElideRight
                                    font.pixelSize: 13
                                    color: Theme.tokens.color.textPrimary
                                }
                                StatusChip {
                                    label: "密钥"
                                    value: modelData.hasCredential ? "已存" : "无"
                                    tone: modelData.hasCredential ? "success" : "warning"
                                }
                            }
                            MouseArea {
                                id: area
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: ModelSettings.selectProvider(
                                    modelData.id)
                            }
                        }
                    }

                    AppButton {
                        objectName: "removeProviderButton"
                        Layout.fillWidth: true
                        text: "删除所选连接"
                        ghost: true
                        enabled: !ModelSettings.editingNewProvider
                        onClicked: ModelSettings.removeCurrent()
                    }
                }
            }

            // -- editor form ---------------------------------------------------
            ScrollView {
                id: writerFormScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    width: writerFormScroll.availableWidth
                    spacing: 14

                    RowLayout {
                        spacing: 10
                        AppButton {
                            objectName: "saveProviderButton"
                            text: "保存连接"
                            primary: true
                            enabled: nameInput.text.trim() !== ""
                                 && baseUrlInput.text.trim() !== ""
                            onClicked: ModelSettings.saveCurrent(
                                apiKeyInput.text)
                        }
                        AppButton {
                            objectName: "refreshModelsButton"
                            text: "刷新模型"
                            onClicked: ModelSettings.refreshModels(
                                apiKeyInput.text)
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: writerFormScroll.availableWidth < 340 ? 1 : 2
                        columnSpacing: 14
                        rowSpacing: 10

                        Label { text: "名称" }
                        AppTextField {
                            id: nameInput
                            objectName: "providerNameInput"
                            Layout.fillWidth: true
                            text: ModelSettings.draftName
                            onTextEdited: ModelSettings.setDraftName(text)
                        }
                        Label { text: "Base URL" }
                        AppTextField {
                            id: baseUrlInput
                            objectName: "providerBaseUrlInput"
                            Layout.fillWidth: true
                            text: ModelSettings.draftBaseUrl
                            placeholderText: "https://api.example.com/v1"
                            onTextEdited: ModelSettings.setDraftBaseUrl(text)
                        }
                        Label { text: "Models URL（可选）" }
                        AppTextField {
                            objectName: "providerModelsUrlInput"
                            Layout.fillWidth: true
                            text: ModelSettings.draftModelsUrl
                            onTextEdited: ModelSettings.setDraftModelsUrl(text)
                        }
                        Label { text: "接口类型" }
                        AppComboBox {
                            objectName: "providerInterfaceCombo"
                            Layout.fillWidth: true
                            model: ["openai_compatible"]
                            currentIndex: 0
                            onActivated: ModelSettings.setDraftInterfaceType(
                                currentValue)
                        }
                        Label { text: "超时（秒）" }
                        SpinBox {
                            id: timeoutSpin
                            objectName: "providerTimeoutSpin"
                            implicitHeight: 36
                            font.pixelSize: 13
                            Layout.fillWidth: true
                            from: 1
                            to: 600
                            value: ModelSettings.draftTimeout
                            onValueModified: ModelSettings.setDraftTimeout(value)
                        }
                        Label { text: "API Key" }
                        AppTextField {
                            id: apiKeyInput
                            objectName: "apiKeyInput"
                            Layout.fillWidth: true
                            echoMode: TextInput.Password
                            placeholderText: "只写不回显；留空保留原密钥"
                        }
                    }

                    Connections {
                        target: ModelSettings
                        function onApiKeyFieldsCleared() {
                            apiKeyInput.clear()
                        }
                        function onCurrentProviderChanged() {
                            timeoutSpin.value = ModelSettings.draftTimeout
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        AppButton {
                            objectName: "probeCapabilitiesButton"
                            text: "探测能力"
                            onClicked: probeModelInput.text.trim() === ""
                                ? ModelSettings.refreshModels(apiKeyInput.text)
                                : ModelSettings.probeCapabilities(
                                    probeModelInput.text, apiKeyInput.text)
                        }
                        AppTextField {
                            id: probeModelInput
                            objectName: "probeModelInput"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 80
                            placeholderText: "要探测的模型 ID"
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        visible: !root.codexEnabled
                        Label { text: "旧剧情路由（兼容）" }
                        AppComboBox {
                            objectName: "plotRouteCombo"
                            Layout.fillWidth: true
                            model: ModelSettings.availableModels
                            onActivated: ModelSettings.assignRoute(
                                "plot", currentValue)
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Label { text: "正文写作模型" }
                        AppComboBox {
                            objectName: "proseRouteCombo"
                            Layout.fillWidth: true
                            model: ModelSettings.availableModels
                            onActivated: ModelSettings.assignRoute(
                                "prose", currentValue)
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "当前写作连接：" + ModelSettings.proseRouteText
                        wrapMode: Text.WrapAnywhere
                        color: Theme.tokens.color.textSecondary
                    }

                    Label {
                        objectName: "settingsStatusMessage"
                        Layout.fillWidth: true
                        text: ModelSettings.statusMessage
                        wrapMode: Text.WordWrap
                        color: Theme.tokens.color.textSecondary
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: "说明：这里的 API 连接用于独立写作模型；"
                              + "API Key 保存在系统凭据库，本页面不显示已存密钥。"
                        color: Theme.tokens.color.textSecondary
                    }
                }
            }
        }
    }
}
