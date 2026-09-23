import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons

// Last HISTORY_LIMIT (10) translations, each with the recording that
// produced it. The daemon owns history.json — writing it, capping it at
// 10, and deleting the recording of anything it prunes (see history.py) —
// this panel only reads it and plays/copies from it.
Item {
  id: root

  property bool opened: false
  property var entries: []
  property string justCopiedId: ""
  property real nowSeconds: Date.now() / 1000
  readonly property string fontFamily: Style.font.family

  // On-demand second opinion from Claude, via the `claude` CLI already
  // installed and logged in on this machine — not called automatically on
  // every translation (that would add a delay and an API call to every
  // click-to-listen), only when a specific entry looks wrong. One at a
  // time: reviewingId is "" when idle, the entry id while a check is
  // in flight. reviewState keeps the outcome per entry id so it survives
  // scrolling the list.
  property string reviewingId: ""
  property var reviewState: ({})

  function requestReview(entry) {
    if (root.reviewingId !== "") return
    root.reviewingId = entry.id
    var prompt = "A small offline translation model turned this Shona speech into English. " +
      "Shona: " + JSON.stringify(entry.shona) + " " +
      "Its English translation: " + JSON.stringify(entry.english) + " " +
      "In one short sentence: say it's accurate, or give a corrected, natural English translation. " +
      "No preamble, no markdown — just that one sentence."
    reviewProc.command = ["claude", "-p", prompt]
    reviewTimeout.restart()
    reviewProc.running = true
  }

  function setReview(id, status, text) {
    var next = ({})
    for (var k in root.reviewState) next[k] = root.reviewState[k]
    next[id] = { status: status, text: text }
    root.reviewState = next
  }

  function open(_payloadJson) {
    root.opened = true
    historyFile.reload()
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.close()
  }

  function agoText(updated) {
    var diff = Math.max(0, root.nowSeconds - updated)
    if (diff < 60) return "just now"
    if (diff < 3600) return Math.floor(diff / 60) + "m ago"
    if (diff < 86400) return Math.floor(diff / 3600) + "h ago"
    return Math.floor(diff / 86400) + "d ago"
  }

  function copyToClipboard(value, entryId) {
    if (!value) return
    Quickshell.execDetached(["bash", "-c", "printf %s " + Util.shellQuote(value) + " | wl-copy"])
    root.justCopiedId = entryId
    copiedResetTimer.restart()
  }

  function playRecording(path) {
    if (!path) return
    Quickshell.execDetached(["pw-play", path])
  }

  FileView {
    id: historyFile
    path: Quickshell.env("HOME") + "/.local/state/shona-translate/history.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        root.entries = JSON.parse(historyFile.text())
      } catch (e) {
        root.entries = []
      }
    }
    onLoadFailed: root.entries = []
  }

  Timer {
    running: root.opened
    interval: 30000
    repeat: true
    onTriggered: root.nowSeconds = Date.now() / 1000
  }

  Timer {
    id: copiedResetTimer
    interval: 1200
    onTriggered: root.justCopiedId = ""
  }

  Timer {
    id: reviewTimeout
    interval: 30000
    onTriggered: {
      if (reviewProc.running) reviewProc.running = false
      root.setReview(root.reviewingId, "error", "Timed out waiting for Claude.")
      root.reviewingId = ""
    }
  }

  Process {
    id: reviewProc
    command: ["claude"]
    stdout: StdioCollector {
      onStreamFinished: {
        var reply = text.trim()
        if (reply) root.setReview(root.reviewingId, "done", reply)
      }
    }
    stderr: StdioCollector {
      id: reviewStderr
    }
    onExited: (exitCode, exitStatus) => {
      reviewTimeout.stop()
      var id = root.reviewingId
      root.reviewingId = ""
      // stdout's onStreamFinished already set a "done" result when there
      // was one; only step in here if that never happened.
      if (!root.reviewState[id]) {
        var detail = reviewStderr.text ? reviewStderr.text.trim() : ""
        root.setReview(id, "error", detail || "Claude didn't return a reply.")
      }
    }
  }

  PanelWindow {
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "shona-translate-history"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

    Rectangle {
      anchors.fill: parent
      color: Qt.rgba(0, 0, 0, 0.6)

      MouseArea {
        anchors.fill: parent
        onClicked: root.dismiss()
      }
    }

    Item {
      id: keyCatcher
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: root.dismiss()

      Rectangle {
        id: card
        anchors.centerIn: parent
        width: 560
        height: Math.min(parent.height - 80, content.implicitHeight + 40)
        radius: 14
        color: Color.background
        border.width: 1
        border.color: Color.accent

        MouseArea { anchors.fill: parent; onClicked: {} } // swallow: only the scrim dismisses

        ColumnLayout {
          id: content
          anchors.fill: parent
          anchors.margins: 20
          spacing: 14

          RowLayout {
            Layout.fillWidth: true
            Text {
              text: "Shona translate — recent"
              color: Color.foreground
              font.family: root.fontFamily
              font.pixelSize: 16
              font.bold: true
              Layout.fillWidth: true
            }
            Text {
              text: "✕"
              color: Color.foreground
              font.pixelSize: 16
              MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.dismiss() }
            }
          }

          Text {
            text: "The last " + Math.max(root.entries.length, 10) + " turns. Click the English text (or the copy icon) to copy it; click ▶ to hear the recording again."
            color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.7)
            font.family: root.fontFamily
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
          }

          Text {
            visible: root.entries.length === 0
            text: "Nothing translated yet."
            color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.6)
            font.family: root.fontFamily
            font.pixelSize: 13
            Layout.fillWidth: true
          }

          ListView {
            id: list
            visible: root.entries.length > 0
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: Math.min(contentHeight, 420)
            clip: true
            spacing: 10
            model: root.entries
            boundsBehavior: Flickable.StopAtBounds

            delegate: ColumnLayout {
              id: row
              required property var modelData
              width: list.width
              spacing: 6

              RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Text {
                  text: "▶"
                  color: Color.foreground
                  font.family: root.fontFamily
                  font.pixelSize: 15
                  MouseArea {
                    anchors.fill: parent
                    anchors.margins: -6
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.playRecording(row.modelData.wav)
                  }
                }

                ColumnLayout {
                  Layout.fillWidth: true
                  spacing: 2

                  Text {
                    Layout.fillWidth: true
                    text: row.modelData.english
                    color: Color.foreground
                    font.family: root.fontFamily
                    font.pixelSize: 13
                    font.bold: true
                    wrapMode: Text.WordWrap
                    MouseArea {
                      anchors.fill: parent
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.copyToClipboard(row.modelData.english, row.modelData.id)
                    }
                  }

                  Text {
                    Layout.fillWidth: true
                    text: row.modelData.shona
                    color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.55)
                    font.family: root.fontFamily
                    font.pixelSize: 11
                    font.italic: true
                    wrapMode: Text.WordWrap
                  }
                }

                Text {
                  text: root.justCopiedId === row.modelData.id ? "✓ copied" : "copy"
                  color: root.justCopiedId === row.modelData.id ? Color.accent : Color.foreground
                  font.family: root.fontFamily
                  font.pixelSize: 11
                  MouseArea {
                    anchors.fill: parent
                    anchors.margins: -6
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.copyToClipboard(row.modelData.english, row.modelData.id)
                  }
                }

                Text {
                  readonly property bool busy: root.reviewingId === row.modelData.id
                  text: busy ? "checking…" : "🤖 double check"
                  color: busy ? Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.5) : Color.foreground
                  font.family: root.fontFamily
                  font.pixelSize: 11
                  MouseArea {
                    anchors.fill: parent
                    anchors.margins: -6
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.requestReview(row.modelData)
                  }
                }

                Text {
                  text: root.agoText(row.modelData.updated)
                  color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.5)
                  font.family: root.fontFamily
                  font.pixelSize: 11
                }
              }

              Text {
                readonly property var review: root.reviewState[row.modelData.id]
                visible: review !== undefined
                Layout.fillWidth: true
                Layout.leftMargin: 25
                text: review ? "🤖 " + review.text : ""
                color: review && review.status === "error" ? Color.urgent : Color.accent
                font.family: root.fontFamily
                font.pixelSize: 12
                wrapMode: Text.WordWrap
              }

              Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.12)
              }
            }
          }
        }
      }
    }
  }
}
