import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    objectName: "generationConfigDialog"

    property bool openRequested: false

    title: "生成草稿"
    modal: true
    width: 420
    anchors.centerIn: parent
    visible: root.openRequested

    onOpened: {
        targetWords.value = Facade.generationTargetWords
        tokenLimit.value = Facade.generationOutputTokenLimit
        modeCombo.currentIndex = Math.max(0, modeCombo.indexOfValue(Facade.generationMode))
        auditCombo.currentIndex = Math.max(0, auditCombo.indexOfValue(Facade.generationAuditPolicy))
    }
    onClosed: root.openRequested = false

    contentItem: ColumnLayout {
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                Layout.preferredWidth: 110
                text: "目标字数"
                font.pixelSize: 12
                color: Theme.tokens.color.textPrimary
            }
            SpinBox {
                id: targetWords
                objectName: "targetWordsSpin"
                Layout.fillWidth: true
                from: 100
                to: 100000
                stepSize: 100
                editable: true
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                Layout.preferredWidth: 110
                text: "输出 Token"
                font.pixelSize: 12
                color: Theme.tokens.color.textPrimary
            }
            SpinBox {
                id: tokenLimit
                objectName: "tokenLimitSpin"
                Layout.fillWidth: true
                from: 256
                to: 32768
                stepSize: 256
                editable: true
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                Layout.preferredWidth: 110
                text: "创作档位"
                font.pixelSize: 12
                color: Theme.tokens.color.textPrimary
            }
            ComboBox {
                id: modeCombo
                objectName: "modeCombo"
                Layout.fillWidth: true
                textRole: "label"
                valueRole: "value"
                model: [
                    { label: "快速（BASIC）", value: "BASIC" },
                    { label: "标准（STANDARD）", value: "STANDARD" },
                    { label: "严格（STRICT）", value: "STRICT" }
                ]
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                Layout.preferredWidth: 110
                text: "采用前审校"
                font.pixelSize: 12
                color: Theme.tokens.color.textPrimary
            }
            ComboBox {
                id: auditCombo
                objectName: "auditCombo"
                Layout.fillWidth: true
                textRole: "label"
                valueRole: "value"
                model: [
                    { label: "最小（MINIMAL）", value: "MINIMAL" },
                    { label: "标准（STANDARD）", value: "STANDARD" },
                    { label: "深度（DEEP）", value: "DEEP" }
                ]
            }
        }
    }

    footer: DialogButtonBox {
        Button {
            objectName: "cancelGenerationButton"
            text: "取消"
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            onClicked: root.close()
        }
        Button {
            objectName: "startGenerationButton"
            text: "开始生成"
            highlighted: true
            onClicked: {
                Facade.setGenerationTargetWords(targetWords.value)
                Facade.setGenerationOutputTokenLimit(tokenLimit.value)
                Facade.setGenerationMode(modeCombo.currentValue)
                Facade.setGenerationAuditPolicy(auditCombo.currentValue)
                root.close()
                Facade.requestDraft()
            }
        }
    }
}
