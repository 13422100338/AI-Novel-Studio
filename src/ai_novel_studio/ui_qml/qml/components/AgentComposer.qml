import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ColumnLayout {
    id: root
    objectName: "agentComposer"

    signal sendRequested(string text)
    signal stopRequested()
    signal quickCommand(string command)
    signal sessionCommand(string command)
    property bool menuFromSlash: false
    property int commandIndex: 0
    readonly property var writingCommands: [
        {name: "重写", alias: "rewrite", hint: "调整选文表达"},
        {name: "润色", alias: "polish", hint: "打磨措辞与句式"},
        {name: "精简", alias: "shorten", hint: "去掉选文冗余"},
        {name: "扩写", alias: "expand", hint: "补充选文细节"},
        {name: "生成草稿", alias: "draft", hint: "调用独立写作模型"},
        {name: "续写", alias: "continue", hint: "接着当前章节写"}
    ]
    readonly property string commandQuery: input.text.startsWith("/") ? input.text.slice(1).toLowerCase() : ""
    readonly property var filteredCommands: writingCommands.filter(function(command) {
        return !root.menuFromSlash || root.commandQuery === "skills" || command.name.indexOf(root.commandQuery) >= 0 || command.alias.indexOf(root.commandQuery) >= 0
    })

    function chooseCommand(command) {
        writingMenu.close()
        if (root.menuFromSlash) {
            input.text = "/" + command.name + " "
            input.cursorPosition = input.text.length
            input.forceActiveFocus()
        } else {
            root.quickCommand(command.name)
        }
    }

    FileDialog {
        id: attachmentDialog
        title: "添加创作材料"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["图片与文本 (*.png *.jpg *.jpeg *.webp *.gif *.txt *.md)"]
        onAccepted: {
            for (let url of selectedFiles)
                Facade.addCodexAttachment(url)
        }
    }

    Flow {
        visible: Facade.codexEnabled && Facade.codexAttachments.length > 0
        Layout.fillWidth: true
        spacing: 4
        Repeater {
            model: Facade.codexAttachments
            AppButton {
                required property var modelData
                required property int index
                text: (modelData.name.length > 34 ? modelData.name.slice(0, 30) + "…" : modelData.name) + " ×"
                enabled: !Facade.agentBusy
                onClicked: Facade.removeCodexAttachment(index)
            }
        }
    }

    ContextReferenceChip {
        objectName: "selectionReferenceChip"
        Layout.fillWidth: true
        opacity: Facade.hasSelectionReference ? 1 : 0
        visible: opacity > 0.01
        label: Facade.selectionReferenceLabel
        preview: Facade.selectionReferencePreview
        onCleared: Facade.clearSelectionReference()
    }

    Rectangle {
        id: inputBox
        objectName: "agentComposerBox"
        Layout.fillWidth: true
        Layout.preferredHeight: 144
        color: Theme.tokens.color.bgEditor
        border.color: input.activeFocus ? Theme.tokens.color.accent : Theme.tokens.color.border
        border.width: input.activeFocus ? 2 : 1
        radius: 20

        TextArea {
            id: input
            objectName: "agentComposerInput"
            anchors.fill: parent
            anchors.margins: 10
            anchors.bottomMargin: 42
            // Room for the embedded send circle at the right edge.
            anchors.rightMargin: 10
            placeholderText: Facade.codexCanSteer ? "给当前任务追加要求…" : "向 AI 助手提问，或告诉它接下来怎么写…"
            font.pixelSize: 14
            placeholderTextColor: Theme.tokens.color.textSecondary
            color: Theme.tokens.color.textPrimary
            wrapMode: TextEdit.Wrap
            background: null
            Keys.priority: Keys.BeforeItem
            onTextChanged: {
                root.commandIndex = 0
                if (text.startsWith("/") && !/\s/.test(text) && root.filteredCommands.length > 0 && !Facade.agentBusy) {
                    root.menuFromSlash = true
                    writingMenu.open()
                } else if (root.menuFromSlash) {
                    writingMenu.close()
                }
            }
            Keys.onEscapePressed: function(event) {
                if (writingMenu.opened) {
                    writingMenu.close()
                    event.accepted = true
                } else {
                    event.accepted = false
                }
            }
            Keys.onDownPressed: function(event) {
                if (writingMenu.opened) {
                    root.commandIndex = (root.commandIndex + 1) % root.filteredCommands.length
                    event.accepted = true
                } else {
                    event.accepted = false
                }
            }
            Keys.onUpPressed: function(event) {
                if (writingMenu.opened) {
                    root.commandIndex = (root.commandIndex + root.filteredCommands.length - 1) % root.filteredCommands.length
                    event.accepted = true
                } else {
                    event.accepted = false
                }
            }

            Keys.onReturnPressed: function(event) {
                if (event.modifiers & Qt.ShiftModifier) {
                    input.insert(input.cursorPosition, "\n")
                    event.accepted = true
                } else if (writingMenu.opened && root.menuFromSlash && root.filteredCommands.length > 0) {
                    root.chooseCommand(root.filteredCommands[root.commandIndex])
                    event.accepted = true
                } else {
                    root.submit()
                    event.accepted = true
                }
            }
        }

        // Embedded circular send button (chat language): accent circle with
        // an up arrow, docked at the input's bottom-right corner.
        Rectangle {
            id: sendButton
            objectName: "agentSendButton"
            width: 32
            height: 32
            radius: 16
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 8
            property bool canSend: input.text.trim() !== "" && (!Facade.agentBusy || Facade.codexCanSteer)
            opacity: canSend ? 1.0 : 0.4
            color: Theme.tokens.color.textPrimary

            Text {
                anchors.centerIn: parent
                text: Facade.codexCanSteer ? "＋" : "↑"
                font.pixelSize: 15
                font.bold: true
                color: Theme.tokens.color.bgSurface
            }
            MouseArea {
                id: sendArea
                anchors.fill: parent
                enabled: sendButton.canSend
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.submit()
            }
        }

        // Stop docks left of the send circle while the agent is busy.
        AppButton {
            id: attachmentButton
            objectName: "agentAttachmentButton"
            text: "＋"
            implicitWidth: 32
            implicitHeight: 32
            Accessible.name: "添加材料、笔记或写作指令"
            enabled: !Facade.agentBusy
            ghost: true
            anchors.left: parent.left
            anchors.leftMargin: 6
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            onClicked: materialsMenu.open()
        }
        Popup {
            id: materialsMenu
            objectName: "composerMaterialsMenu"
            x: 6
            y: -height - 8
            width: 240
            padding: 10
            focus: true
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
            background: Rectangle { color: Theme.tokens.color.bgSurface; border.color: Theme.tokens.color.border; radius: 14 }
            contentItem: ColumnLayout {
                spacing: 4
                AppButton {
                    objectName: "composerAttachAction"
                    text: "添加附件…"
                    Layout.fillWidth: true
                    ghost: true
                    visible: Facade.codexEnabled
                    onClicked: { materialsMenu.close(); attachmentDialog.open() }
                }
                AppButton {
                    id: writingButton
                    objectName: "writingMenuButton"
                    text: "/ 写作"
                    ghost: true
                    enabled: !Facade.agentBusy
                    Layout.fillWidth: true
                    onClicked: {
                        materialsMenu.close()
                        root.menuFromSlash = false
                        root.commandIndex = 0
                        writingMenu.open()
                    }
                }
                NotesInputPicker { id: notePickerAction; Layout.fillWidth: true }
            }
            Connections {
                target: notePickerAction
                function onClicked() { materialsMenu.close() }
            }
        }
        Popup {
            id: writingMenu
            objectName: "writingCommandMenu"
            x: 6
            y: -height - 6
            width: Math.min(inputBox.width - 12, 300)
            padding: 8
            focus: !root.menuFromSlash
            modal: false
            onOpened: {
                if (root.menuFromSlash)
                    input.forceActiveFocus()
            }
            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
            background: Rectangle {
                color: Theme.tokens.color.bgSurface
                border.color: Theme.tokens.color.border
                radius: Theme.tokens.radius.r12
            }
            contentItem: ColumnLayout {
                spacing: 2
                Text {
                    Layout.fillWidth: true
                    Layout.margins: 6
                    text: "小说编辑技能 · Codex"
                    font.pixelSize: 11
                    color: Theme.tokens.color.textSecondary
                }
                Repeater {
                    model: root.filteredCommands
                    AppButton {
                        required property var modelData
                        required property int index
                        objectName: modelData.name === "生成草稿" ? "writerQuickButton" : "writingCommand" + modelData.alias
                        Layout.fillWidth: true
                        implicitHeight: 34
                        text: "/" + modelData.name + "　" + modelData.hint
                        selected: root.menuFromSlash && root.commandIndex === index
                        ghost: true
                        onClicked: root.chooseCommand(modelData)
                    }
                }
            }
        }
        AppButton {
            id: stopButton
            objectName: "agentStopButton"
            text: "停止"
            ghost: true
            visible: Facade.agentBusy
            anchors.right: sendButton.left
            anchors.rightMargin: 4
            anchors.verticalCenter: sendButton.verticalCenter
            onClicked: root.stopRequested()
        }
        CodexControls {
            id: composerModels
            visible: Facade.codexEnabled
            anchors.right: Facade.agentBusy ? stopButton.left : sendButton.left
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 9
            anchors.rightMargin: 4
            width: Math.min(228, implicitWidth, parent.width - (Facade.agentBusy ? 150 : 86))
            compact: true
        }
    }

    Text {
        Layout.fillWidth: true
        visible: !Facade.codexEnabled
        text: "Enter 发送 · / 写作指令 · Shift + Enter 换行"
        font.pixelSize: 11
        color: Theme.tokens.color.textSecondary
    }

    function submit() {
        const text = input.text
        if (text.trim() === "" || (Facade.agentBusy && !Facade.codexCanSteer)) {
            return
        }
        if (text.trim() === "/" || text.trim() === "/skills") {
            root.menuFromSlash = true
            writingMenu.open()
            return
        }
        input.text = ""
        if (text.trim() === "/model" && Facade.codexEnabled) {
            composerModels.openModels()
            return
        }
        if (["/new", "/compact"].indexOf(text.trim()) >= 0 && Facade.codexEnabled) {
            root.sessionCommand(text.trim().slice(1))
            return
        }
        root.sendRequested(text)
    }
}
