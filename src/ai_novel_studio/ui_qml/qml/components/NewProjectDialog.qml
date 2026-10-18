import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Dialog {
    id: root

    property string parentPath: ""

    signal projectCreated(string message)

    modal: true
    title: "新建项目"
    standardButtons: Dialog.Cancel
    width: 420

    footer: DialogButtonBox {
        Button {
            objectName: "createProjectConfirmButton"
            text: "创建"
            enabled: nameInput.text.trim() !== "" && root.parentPath !== ""
            onClicked: root.create()
        }
        Button {
            text: "取消"
            onClicked: root.reject()
        }
    }

    function create() {
        // selectedFolder is a QUrl: hand it to the bridge untouched so
        // toLocalFile() conversion happens on the Python side (same boundary
        // as openProjectFromUrl). Never pre-stringify into a file:/// URL.
        var error = Facade.createProjectFromUrl(
            parentFolderDialog.selectedFolder, nameInput.text)
        if (error === "") {
            nameInput.text = ""
            root.parentPath = ""
            errorText.text = ""
            root.accept()
            root.projectCreated("")
        } else {
            errorText.text = error
        }
    }

    onOpened: {
        nameInput.text = ""
        root.parentPath = ""
        errorText.text = ""
    }

    ColumnLayout {
        width: parent.width
        spacing: 8

        Label {
            text: "项目名称"
            color: Theme.tokens.color.textSecondary
        }
        TextField {
            id: nameInput
            objectName: "newProjectNameInput"
            Layout.fillWidth: true
            placeholderText: "例如：我的小说"
        }

        Label {
            text: "父目录"
            color: Theme.tokens.color.textSecondary
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 6

            Label {
                Layout.fillWidth: true
                text: root.parentPath === "" ? "（未选择）"
                      : root.parentPath.replace(/^file:\/\/\//, "")
                elide: Text.ElideMiddle
                color: Theme.tokens.color.textPrimary
            }
            AppButton {
                objectName: "chooseParentDirButton"
                text: "选择…"
                onClicked: parentFolderDialog.open()
            }
        }

        Label {
            Layout.fillWidth: true
            text: root.parentPath === "" || nameInput.text.trim() === ""
                  ? "" : "目标位置：" + root.parentPath + "/" + nameInput.text.trim()
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
        onAccepted: root.parentPath = parentFolderDialog.selectedFolder
    }
}
