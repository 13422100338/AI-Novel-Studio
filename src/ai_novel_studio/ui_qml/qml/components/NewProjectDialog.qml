import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

StudioDialog {
    id: root

    property url selectedParentUrl: ""
    readonly property string parentPath: String(selectedParentUrl)

    signal projectCreated(string message)

    modal: true
    title: "新建项目"
    footer: Item {
        implicitHeight: 70
        RowLayout {
            anchors.right: parent.right
            anchors.rightMargin: 22
            anchors.verticalCenter: parent.verticalCenter
            spacing: 10
            AppButton {
                objectName: "createProjectCancelButton"
                text: "取消"
                ghost: true
                onClicked: root.reject()
            }
            AppButton {
                objectName: "createProjectConfirmButton"
                text: "创建项目"
                primary: true
                enabled: nameInput.text.trim() !== "" && root.parentPath !== ""
                onClicked: root.create()
            }
        }
    }

    function create() {
        // Keep the accepted folder as a QUrl and hand it to the bridge so
        // toLocalFile() conversion happens on the Python side (same boundary
        // as openProjectFromUrl). Never pre-stringify into a file:/// URL.
        var error = Facade.createProjectFromUrl(
            root.selectedParentUrl, nameInput.text)
        if (error === "") {
            nameInput.text = ""
            root.selectedParentUrl = ""
            errorText.text = ""
            root.accept()
            root.projectCreated("")
        } else {
            errorText.text = error
        }
    }

    onOpened: {
        nameInput.text = ""
        root.selectedParentUrl = ""
        errorText.text = ""
        Qt.callLater(function() { nameInput.forceActiveFocus() })
    }

    contentItem: ColumnLayout {
        spacing: 14

        Text {
            Layout.fillWidth: true
            text: "为这部小说准备一个工作区，保存大纲、正文和创作笔记。"
            wrapMode: Text.Wrap
            font.pixelSize: 13
            color: Theme.tokens.color.textSecondary
        }

        Label {
            text: "项目名称"
            color: Theme.tokens.color.textSecondary
        }
        TextField {
            id: nameInput
            objectName: "newProjectNameInput"
            Layout.fillWidth: true
            placeholderText: "例如：我的小说"
            font.pixelSize: 14
            color: Theme.tokens.color.textPrimary
            placeholderTextColor: Theme.tokens.color.textSecondary
            padding: 12
            selectByMouse: true
            background: Rectangle {
                color: Theme.tokens.color.bgEditor
                border.color: nameInput.activeFocus ? Theme.tokens.color.accent : Theme.tokens.color.border
                radius: 9
            }
        }

        Label {
            text: "保存位置"
            color: Theme.tokens.color.textSecondary
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Label {
                Layout.fillWidth: true
                text: root.parentPath === "" ? "请选择小说工作区的存放位置"
                      : root.parentPath.replace(/^file:\/\/\//, "")
                elide: Text.ElideMiddle
                color: Theme.tokens.color.textPrimary
            }
            AppButton {
                objectName: "chooseParentDirButton"
                text: "选择文件夹…"
                onClicked: parentFolderDialog.open()
            }
        }

        Label {
            Layout.fillWidth: true
            text: root.parentPath === "" || nameInput.text.trim() === ""
                  ? "" : "将创建：" + root.parentPath.replace(/^file:\/\/\//, "") + "/" + nameInput.text.trim()
            wrapMode: Text.WordWrap
            color: Theme.tokens.color.textSecondary
        }

        Label {
            id: errorText
            objectName: "newProjectError"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            visible: text !== ""
            color: Theme.tokens.color.danger
        }
    }

    FolderDialog {
        id: parentFolderDialog
        objectName: "newProjectParentDialog"
        title: "选择父目录"
        onAccepted: root.selectedParentUrl = parentFolderDialog.selectedFolder
    }
}
