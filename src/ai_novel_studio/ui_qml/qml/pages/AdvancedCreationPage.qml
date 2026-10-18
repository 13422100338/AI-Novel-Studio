import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    objectName: "advancedCreationPage"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        Text {
            text: "高级创作"
            font.pixelSize: 17
            font.bold: true
            color: Theme.tokens.color.textPrimary
        }

        TabBar {
            id: tabs
            Layout.fillWidth: true
            background: Rectangle {
                color: "transparent"
            }
            Repeater {
                model: ["伏笔与回收", "故事线", "时间线", "人物认知", "一致性审查", "影响分析"]
                delegate: ThemedTabButton {
                    text: modelData
                    checked: tabs.currentIndex === index
                    onClicked: tabs.currentIndex = index
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            // -- 伏笔与回收: read-only approved clue ledger ----------------
            Item {
                objectName: "clueLedgerPage"

                EmptyState {
                    anchors.centerIn: parent
                    visible: Facade.advancedState !== "READY"
                             || Facade.advancedClues.length === 0
                    title: Facade.advancedState === "NO_PROJECT"
                           ? "未打开项目"
                           : Facade.advancedState === "ERROR"
                             ? "线索读取失败"
                             : "暂无已审核伏笔"
                    body: Facade.advancedState === "NO_PROJECT"
                          ? "打开项目后，这里显示当前章节之前已审核的伏笔时间线。"
                          : Facade.advancedState === "READY"
                            ? "当前章节之前还没有已审核/锁定的伏笔记录。"
                            : ""
                }

                ListView {
                    visible: Facade.advancedState === "READY"
                             && Facade.advancedClues.length > 0
                    anchors.fill: parent
                    clip: true
                    spacing: 8
                    model: Facade.advancedClues

                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width
                        height: clueCard.implicitHeight + 16
                        radius: Theme.tokens.radius.r8
                        color: Theme.tokens.color.bgSurface
                        border.color: Theme.tokens.color.border

                        ColumnLayout {
                            id: clueCard
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 4

                            RowLayout {
                                Layout.fillWidth: true
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.title
                                    font.pixelSize: 13
                                    font.bold: true
                                    elide: Text.ElideRight
                                    color: Theme.tokens.color.textPrimary
                                }
                                StatusChip {
                                    label: "事件"
                                    value: String(modelData.eventCount)
                                    tone: "neutral"
                                }
                            }
                            Text {
                                Layout.fillWidth: true
                                text: modelData.summary
                                       + (modelData.summaryTruncated ? "…" : "")
                                wrapMode: Text.WordWrap
                                font.pixelSize: 12
                                color: Theme.tokens.color.textSecondary
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }
                            Text {
                                text: "最近动作：" + modelData.lastAction
                                      + " · 涉及章节 " + modelData.chapterIds.length
                                font.pixelSize: 10
                                color: Theme.tokens.color.textSecondary
                            }
                        }
                    }
                }
            }

            // -- 故事线(本章计划): canonical AUTHOR_PLAN projection ----------
            Item {
                objectName: "chapterPlanPage"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 8

                    RowLayout {
                        spacing: 8
                        Text {
                            text: "本章计划"
                            font.pixelSize: 14
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                        }
                        StatusChip {
                            label: "性质"
                            value: "作者计划（非正典）"
                            tone: "warning"
                        }
                        StatusChip {
                            objectName: "planLockedChip"
                            label: "需求锁定"
                            value:
                                Facade.advancedPlan.requirementLocked ? "是" : "否"
                            tone: "neutral"
                        }
                    }

                    Text {
                        text: "说明：这是当前章节的计划视图，不是多故事线管理。"
                        font.pixelSize: 11
                        color: Theme.tokens.color.textSecondary
                    }

                    Label { text: "章节需求" ; color: Theme.tokens.color.textSecondary }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: planRequirementText.implicitHeight + 20
                        radius: Theme.tokens.radius.r8
                        color: Theme.tokens.color.bgSurface
                        border.color: Theme.tokens.color.border
                        Text {
                            id: planRequirementText
                            objectName: "planRequirementText"
                            anchors.fill: parent
                            anchors.margins: 10
                            text: Facade.advancedState === "READY"
                                  ? (Facade.advancedPlan.requirementText || "（未设置章节需求）")
                                    + (Facade.advancedPlan.requirementTruncated ? "\n…已截断" : "")
                                  : ""
                            wrapMode: Text.WordWrap
                            font.pixelSize: 12
                            color: Theme.tokens.color.textPrimary
                        }
                    }

                    Label { text: "项目指导" ; color: Theme.tokens.color.textSecondary }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: planGuidanceText.implicitHeight + 20
                        radius: Theme.tokens.radius.r8
                        color: Theme.tokens.color.bgSurface
                        border.color: Theme.tokens.color.border
                        Text {
                            id: planGuidanceText
                            objectName: "planGuidanceText"
                            anchors.fill: parent
                            anchors.margins: 10
                            text: Facade.advancedState === "READY"
                                  ? (Facade.advancedPlan.guidanceText || "（无）")
                                    + (Facade.advancedPlan.guidanceTruncated ? "\n…已截断" : "")
                                  : ""
                            wrapMode: Text.WordWrap
                            font.pixelSize: 12
                            color: Theme.tokens.color.textPrimary
                        }
                    }
                }
            }

            // -- 时间线: honest placeholder (no global timeline yet) ---------
            EmptyState {
                objectName: "timelinePlaceholder"
                title: "时间线"
                body: "项目全局时间线尚未实现；单个人物的经历请见「人物认知」页的人物轨迹。"
            }

            // -- 人物认知: cognition rows + per-character trajectory --------
            Item {
                objectName: "cognitionPage"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 8

                    RowLayout {
                        spacing: 10

                        Text {
                            text: "人物认知与轨迹"
                            font.pixelSize: 14
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                        }
                        ComboBox {
                            id: characterCombo
                            objectName: "cognitionCharacterCombo"
                            Layout.preferredWidth: 200
                            model: Facade.characterViews
                            textRole: "name"
                            onActivated: function (index) {
                                Facade.loadAdvancedForSubject(
                                    Facade.characterIdAt(index))
                            }
                        }
                        AppButton {
                            objectName: "reloadCognitionButton"
                            text: "重新载入"
                            enabled: characterCombo.count > 0
                            onClicked: characterCombo.activated(
                                characterCombo.currentIndex)
                        }
                    }

                    Label {
                        text: "人物认知（当前可见的视角断言，只读）"
                        color: Theme.tokens.color.textSecondary
                    }
                    ListView {
                        id: cognitionList
                        objectName: "cognitionList"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(220, contentHeight)
                        clip: true
                        spacing: 6
                        model: Facade.cognitionRows

                        delegate: Rectangle {
                            required property var modelData
                            width: cognitionList.width
                            height: cogCard.implicitHeight + 14
                            radius: Theme.tokens.radius.r8
                            color: Theme.tokens.color.bgSurface
                            border.color: Theme.tokens.color.border
                            ColumnLayout {
                                id: cogCard
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 2
                                RowLayout {
                                    Layout.fillWidth: true
                                    StatusChip {
                                        label: "类型"
                                        value: modelData.viewType
                                        tone: "neutral"
                                    }
                                    StatusChip {
                                        visible:
                                            modelData.epistemicStatus !== ""
                                        label: "认知"
                                        value: modelData.epistemicStatus
                                        tone: "accent"
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.viewerName === ""
                                              ? "观察者：读者"
                                              : "观察者：" + modelData.viewerName
                                        font.pixelSize: 10
                                        color: Theme.tokens.color.textSecondary
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.content
                                          + (modelData.contentTruncated ? "…" : "")
                                    wrapMode: Text.WordWrap
                                    font.pixelSize: 12
                                    color: Theme.tokens.color.textPrimary
                                }
                                Text {
                                    text: "关于：" + modelData.targetName
                                    font.pixelSize: 10
                                    color: Theme.tokens.color.textSecondary
                                }
                            }
                        }
                    }
                    Label {
                        visible: Facade.cognitionState === "READY"
                                 && Facade.cognitionRows.length === 0
                        text: "当前章节时点没有可见的人物认知断言。"
                        color: Theme.tokens.color.textSecondary
                    }

                    Item { Layout.fillHeight: true }

                    Label {
                        text: "人物轨迹（已审核事件，按叙事顺序）"
                        color: Theme.tokens.color.textSecondary
                    }
                    ListView {
                        id: trajectoryList
                        objectName: "trajectoryList"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(180, contentHeight)
                        clip: true
                        spacing: 6
                        model: Facade.trajectoryIndex

                        delegate: Rectangle {
                            required property var modelData
                            width: trajectoryList.width
                            height: trajCard.implicitHeight + 12
                            radius: Theme.tokens.radius.r8
                            color: Theme.tokens.color.bgSurface
                            border.color: Theme.tokens.color.border
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: Facade.openTrajectoryDetail(
                                    modelData.occurrenceId)
                            }
                            ColumnLayout {
                                id: trajCard
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 2
                                Text {
                                    Layout.fillWidth: true
                                    text: "#" + modelData.sequence + " "
                                          + modelData.title
                                          + "（" + modelData.role + "）"
                                    font.pixelSize: 12
                                    elide: Text.ElideRight
                                    color: Theme.tokens.color.textPrimary
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.summary
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                    color: Theme.tokens.color.textSecondary
                                }
                            }
                        }
                    }

                    RowLayout {
                        visible: Facade.trajectoryDetail !== {}
                        spacing: 8
                        Text {
                            text: Facade.trajectoryDetail === {}
                                  ? "" : Facade.trajectoryDetail.title || ""
                            font.bold: true
                            color: Theme.tokens.color.textPrimary
                        }
                        AppButton {
                            objectName: "loadEvidenceButton"
                            text: "回源正文证据"
                            enabled: Facade.trajectoryDetail !== {}
                            onClicked: Facade.loadTrajectoryEvidence(
                                Facade.trajectoryDetail.occurrenceId)
                        }
                    }
                    Repeater {
                        model: Facade.trajectoryEvidence
                        delegate: Text {
                            required property var modelData
                            width: parent ? parent.width : 0
                            text: "[" + modelData.chapterId.substring(0, 8)
                                  + " …] " + modelData.text
                                  + (modelData.truncated ? "…" : "")
                            wrapMode: Text.WordWrap
                            font.pixelSize: 11
                            color: Theme.tokens.color.textSecondary
                        }
                    }
                    Label {
                        text: "说明：轨迹仅包含已审核/锁定且未失效的事件；证据按需回源正式正文。"
                        color: Theme.tokens.color.textSecondary
                    }
                }
            }
            AuditPage {}
            EmptyState { title: "影响分析"; body: "影响分析将在稳定的变更预览服务完成后开放。" }
        }
    }
}
