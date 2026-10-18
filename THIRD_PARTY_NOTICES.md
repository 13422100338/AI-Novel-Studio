# Third-Party Notices

## PySide6 / Qt for Python

This project uses Qt for Python. See the upstream licensing documentation:
<https://doc.qt.io/qtforpython-6/licenses.html>

### qwebchannel.js (Qt WebChannel client)

The Phase 1 editor page embeds `qwebchannel.js`, sourced from the Qt WebChannel
repository and covered by the Qt commercial license terms or LGPL-3.0-only or
GPL-2.0-only or GPL-3.0-only (SPDX:
`LicenseRef-Qt-Commercial OR LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`).
The file keeps its upstream copyright header:
Copyright (C) 2016 The Qt Company Ltd. and Klarälvdalens Datakonsult AB.
Upstream source: <https://code.qt.io/cgit/qt/qtwebchannel.git/tree/src/webchannel/qwebchannel.js>

## Tiptap / ProseMirror

The Phase 1 editor bundle uses the MIT-licensed Tiptap core and ProseMirror
packages (`@tiptap/core`, `@tiptap/pm`, `prosemirror-markdown`,
`prosemirror-view`). License texts are shipped in the npm package directories
of the built distribution and are documented upstream:
<https://tiptap.dev/docs/legal> and <https://prosemirror.net/license/>.

Development-only tools are not bundled as application runtime dependencies.
