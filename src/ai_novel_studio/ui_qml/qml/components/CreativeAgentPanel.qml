import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Codex-style Agent panel: structured timeline + composer (Frontend Wave C1).
// Card types are rendered through a component map; no giant delegate.
Item {
    id: root
    objectName: "creativeAgentPanel"

    // Shared responsive layout rules (C1.2):
    // delegate width = timeline width - vertical scrollbar - safety margin.
    // Every timeline card fills this width; nothing may use a fixed width.
    property int scrollbarWidth: 10
    property int contentSafeMargin: 12
    // Test/diagnostic hook: lets a harness force delegate instantiation for
    // layout assertions without scrolling. No effect in normal use.
    property int timelineCacheBuffer: 0
    // Before/after diagnostic hook: emulates the pre-C1.2 delegate width rule
    // (cards run under the scrollbar). Normal use keeps this false.
    property bool timelineDelegateFullWidth: false
    property bool controlsExpanded: false

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                elide: Text.ElideRight
                text: "✧ AI 助手"
                font.pixelSize: 17
                font.bold: true
                color: Theme.tokens.color.textPrimary
            }
            Text {
                Layout.maximumWidth: 66
                elide: Text.ElideRight
                text: Facade.codexEnabled ? Facade.codexStatusText : (Facade.agentBusy ? "忙碌" : "就绪")
                font.pixelSize: 11
                color: Facade.agentBusy ? Theme.tokens.color.accent : Theme.tokens.color.success
            }
            AppButton {
                objectName: "assistantControlsButton"
                text: root.controlsExpanded ? "收起设置" : "模型与会话"
                ghost: true
                visible: Facade.codexEnabled
                onClicked: root.controlsExpanded = !root.controlsExpanded
            }
            AppButton {
                objectName: "agentCloseButton"
                text: "×"
                implicitWidth: 28
                implicitHeight: 24
                onClicked: Facade.toggleAiDrawer(false)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.tokens.color.border
        }

        CodexControls {
            visible: Facade.codexEnabled && root.controlsExpanded
            Layout.fillWidth: true
        }

        ColumnLayout {
            visible: Facade.codexEnabled && root.controlsExpanded
            Layout.fillWidth: true
            spacing: 6
            Text {
                text: "当前会话"
                font.pixelSize: 12
                color: Theme.tokens.color.textSecondary
            }
            AppComboBox {
                objectName: "codexSessionCombo"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                model: Facade.codexSessions
                textRole: "label"
                valueRole: "value"
                currentIndex: Facade.codexSessionIndex
                displayText: currentIndex < 0 ? "新会话 · 等待发送" : currentText
                enabled: !Facade.agentBusy
                onActivated: Facade.manageCodexSession("switch", currentValue)
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                AppButton {
                    objectName: "codexNewSessionButton"
                    text: "新建会话"
                    Layout.fillWidth: true
                    ghost: true
                    enabled: !Facade.agentBusy && Facade.projectSource === "project"
                    onClicked: Facade.manageCodexSession("new", "")
                }
                AppButton {
                    objectName: "codexForkSessionButton"
                    text: "分支"
                    Layout.fillWidth: true
                    ghost: true
                    enabled: !Facade.agentBusy && Facade.codexCanManageCurrent
                    onClicked: Facade.manageCodexSession("fork", "")
                }
                AppButton {
                    objectName: "codexCompactButton"
                    text: "压缩"
                    Layout.fillWidth: true
                    ghost: true
                    enabled: !Facade.agentBusy && Facade.codexCanManageCurrent
                    onClicked: Facade.manageCodexSession("compact", "")
                }
            }
        }

        Text {
            visible: Facade.codexEnabled
            Layout.fillWidth: true
            text: Facade.codexNovelText
            color: Theme.tokens.color.textSecondary
            font.pixelSize: 11
            wrapMode: Text.WordWrap
        }

        ListView {
            id: timeline
            objectName: "agentTimeline"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            cacheBuffer: root.timelineCacheBuffer
            spacing: 8
            model: Facade.agentTimeline
            rightMargin: root.scrollbarWidth + 2
            ScrollBar.vertical: AppScrollBar {
                width: root.scrollbarWidth
            }

            delegate: Loader {
                id: delegateLoader
                // New timeline cards fade in instead of popping; opacity and
                // scale never touch height, so C1.3 geometry stays intact.
                opacity: 0
                scale: 0.98
                // Content width of the list viewport: never let a card extend
                // under the scrollbar or past the visible area.
                width: Math.max(
                    0,
                    root.timelineDelegateFullWidth
                        ? timeline.width
                        : timeline.width - root.scrollbarWidth - root.contentSafeMargin
                )
                // Single height authority (C1.3): the delegate height follows
                // the loaded card's implicitHeight so the ListView lays cards
                // out in order without overlap.
                height: implicitHeight
                sourceComponent: root.componentFor(kind)

                Behavior on opacity {
                    NumberAnimation {
                        duration: Facade.reduceMotion ? 0 : 150
                        easing.type: Easing.OutCubic
                    }
                }
                Behavior on scale {
                    NumberAnimation {
                        duration: Facade.reduceMotion ? 0 : 150
                        easing.type: Easing.OutCubic
                    }
                }

                onLoaded: {
                    const loadedItem = delegateLoader.item
                    if (loadedItem === null) {
                        return
                    }
                    if (kind === "user_text" || kind === "assistant_text") {
                        loadedItem.text = text
                        loadedItem.user = kind === "user_text"
                    } else if (kind === "run_status") {
                        loadedItem.label = label
                        loadedItem.busy = busy
                        // `status` alone resolves to Loader.status (Ready=1),
                        // not the timeline model role; use the model object.
                        loadedItem.status = model.status
                    } else if (kind === "writer_task") {
                        loadedItem.itemId = itemId
                        loadedItem.copyRequested.connect(function() { Facade.copyWriterDraft(itemId) })
                        loadedItem.stopRequested.connect(function() { Facade.stopWriterDraft() })
                    } else if (kind === "tool_call" || kind === "tool_result") {
                        loadedItem.label = label
                        loadedItem.text = text
                    } else if (kind === "choice_card") {
                        loadedItem.options = options
                        loadedItem.chosen.connect(function(choice) {
                            Facade.agentReplyChoice(choice)
                        })
                    } else if (kind === "text_diff") {
                        loadedItem.itemId = itemId
                        loadedItem.state = state
                        loadedItem.label = label
                        loadedItem.currentText = currentText
                        loadedItem.draftText = draftText
                        loadedItem.approve.connect(function() {
                            Facade.approveAgentItem(itemId)
                        })
                        loadedItem.retry.connect(function() {
                            Facade.retryAgentItem(itemId)
                        })
                        loadedItem.discard.connect(function() {
                            Facade.discardAgentItem(itemId)
                        })
                    } else if (kind === "confirmation") {
                        loadedItem.itemId = itemId
                        loadedItem.state = state
                        loadedItem.label = label
                        loadedItem.text = text
                        loadedItem.confirm.connect(function() {
                            Facade.approveAgentItem(itemId)
                        })
                        loadedItem.cancel.connect(function() {
                            Facade.cancelAgentItem(itemId)
                        })
                    } else if (kind === "form_card") {
                        loadedItem.itemId = itemId
                        loadedItem.state = state
                        loadedItem.title = label
                        loadedItem.description = text
                        loadedItem.fieldLabels = fieldLabels
                        loadedItem.fieldValues = fieldValues
                        loadedItem.submitted.connect(function(valuesJson) {
                            Facade.submitAgentForm(itemId, valuesJson)
                        })
                        loadedItem.skipped.connect(function() {
                            Facade.skipAgentForm(itemId)
                        })
                        loadedItem.cancelled.connect(function() {
                            Facade.cancelAgentItem(itemId)
                        })
                    } else if (kind === "change_set") {
                        loadedItem.itemId = itemId
                        loadedItem.state = state
                        loadedItem.label = label
                        loadedItem.target = target
                        loadedItem.operation = operation
                        loadedItem.beforeText = beforeText
                        loadedItem.afterText = afterText
                        loadedItem.risk = risk
                        loadedItem.reason = reason
                        loadedItem.approve.connect(function() {
                            Facade.approveAgentItem(itemId)
                        })
                        loadedItem.edit.connect(function() {
                            Facade.editAgentChangeSet(itemId)
                        })
                        loadedItem.discard.connect(function() {
                            Facade.discardAgentItem(itemId)
                        })
                    } else if (kind === "warning" || kind === "error") {
                        loadedItem.text = text
                    }
                    delegateLoader.opacity = 1
                    delegateLoader.scale = 1.0
                }

                Binding {
                    target: delegateLoader.item
                    property: "text"
                    value: model.text
                    when: delegateLoader.status === Loader.Ready && ["user_text", "assistant_text", "tool_call", "tool_result", "warning", "error"].indexOf(model.kind) >= 0
                }
                Binding {
                    target: delegateLoader.item
                    property: "label"
                    value: model.label
                    when: delegateLoader.status === Loader.Ready && ["run_status", "tool_call", "tool_result", "writer_task"].indexOf(model.kind) >= 0
                }
                Binding {
                    target: delegateLoader.item
                    property: "busy"
                    value: model.busy
                    when: delegateLoader.status === Loader.Ready && ["run_status", "writer_task", "tool_call", "tool_result"].indexOf(model.kind) >= 0
                }
                Binding {
                    target: delegateLoader.item
                    property: "status"
                    value: model.status
                    when: delegateLoader.status === Loader.Ready && ["run_status", "tool_call", "tool_result"].indexOf(model.kind) >= 0
                }
                Binding { target: delegateLoader.item; property: "state"; value: model.state; when: delegateLoader.status === Loader.Ready && model.kind === "writer_task" }
                Binding { target: delegateLoader.item; property: "detail"; value: model.text; when: delegateLoader.status === Loader.Ready && model.kind === "writer_task" }
                Binding { target: delegateLoader.item; property: "draftText"; value: model.draftText; when: delegateLoader.status === Loader.Ready && model.kind === "writer_task" }
                Binding { target: delegateLoader.item; property: "payloadJson"; value: model.data; when: delegateLoader.status === Loader.Ready && model.kind === "writer_task" }
            }

            EmptyState {
                parent: timeline
                anchors.fill: parent
                visible: timeline.count === 0
                title: "从一个想法开始"
                body: Facade.codexEnabled
                    ? "聊剧情、人物，或直接说“帮我写这一章”。Codex 会整理要求并调用独立写作模型，草稿和进度显示在这里。"
                    : "输入框用于讨论当前小说；下方快捷按钮会生成可审查的章节修改。"
            }
        }

        Text {
            visible: Facade.codexEnabled && Facade.codexUsageText !== ""
            Layout.fillWidth: true
            text: Facade.codexUsageText
            color: Theme.tokens.color.textSecondary
            font.pixelSize: 10
            wrapMode: Text.WordWrap
        }

        Connections {
            target: Facade.agentTimeline
            function onRowsInserted(parent, first, last) {
                // Multi-turn chat behavior: follow new events to the bottom
                // without disturbing the geometry of existing cards.
                timeline.positionViewAtEnd()
            }
        }

        AgentComposer {
            Layout.fillWidth: true
            onSendRequested: function(text) {
                Facade.startAssistantChat(text)
            }
            onStopRequested: Facade.stopAgentTurn()
            onSessionCommand: function(command) {
                if (command === "model")
                    root.controlsExpanded = !root.controlsExpanded
                else
                    Facade.manageCodexSession(command, "")
            }
            onQuickCommand: function(command) {
                if (Facade.codexEnabled) {
                    Facade.startAssistantChat("/" + command)
                } else if (command === "生成草稿") {
                    Facade.startAgentTurn("生成章节草稿")
                } else {
                    Facade.startAgentTurn(command)
                }
            }
        }
    }

    function componentFor(kind) {
        switch (kind) {
        case "user_text":
        case "assistant_text":
            return agentTextComponent
        case "run_status":
            return runStatusComponent
        case "writer_task":
            return writerTaskComponent
        case "tool_call":
        case "tool_result":
            return toolCallComponent
        case "choice_card":
            return choiceCardComponent
        case "text_diff":
            return textDiffComponent
        case "confirmation":
            return confirmationComponent
        case "form_card":
            return formCardComponent
        case "change_set":
            return changeSetComponent
        case "warning":
        case "error":
            return warningComponent
        default:
            return undefined
        }
    }

    Component {
        id: agentTextComponent
        AgentTextBlock {}
    }
    Component {
        id: runStatusComponent
        AgentRunStatus {}
    }
    Component { id: writerTaskComponent; WriterTaskCard {} }
    Component {
        id: toolCallComponent
        ToolCallCard {}
    }
    Component {
        id: choiceCardComponent
        ChoiceCard {}
    }
    Component {
        id: textDiffComponent
        TextDiffCard {}
    }
    Component {
        id: confirmationComponent
        ConfirmationCard {}
    }
    Component {
        id: formCardComponent
        FormCard {}
    }
    Component {
        id: changeSetComponent
        ChangeSetCard {}
    }
    Component {
        id: warningComponent
        AgentTextBlock {
            textColor: Theme.tokens.color.danger
            markdown: false
        }
    }
}
