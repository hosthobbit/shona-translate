import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons

// A small caption card, bottom-center, that appears while listening or
// translating and then shows the last English translation for a while.
// Reads the same state.json the bar-widget indicator does.
Item {
  id: root

  property string status: "stopped"
  property string label: ""
  property real updatedAt: 0
  property real nowSeconds: Date.now() / 1000

  // A killed daemon leaves the last status in the file forever. Treat
  // anything older than a couple minutes as nothing to show.
  readonly property bool fresh: updatedAt > 0 && (nowSeconds - updatedAt) < 120
  readonly property bool busy: status === "listening" || status === "processing"
  // Once idle with a translation, keep it up for a bit, then let it fade.
  readonly property bool showingResult: status === "idle" && label !== ""
                                         && (nowSeconds - updatedAt) < 15
  readonly property bool visible_: fresh && (busy || showingResult || status === "error")

  readonly property color tint: status === "error" ? Color.urgent : Color.accent

  readonly property string statusText: {
    if (status === "listening") return "Listening (Shona)..."
    if (status === "processing") return "Translating..."
    if (status === "error") return label || "Error"
    return label
  }

  FileView {
    id: stateFile
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/shona-translate/state.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      retryTimer.running = false
      try {
        const parsed = JSON.parse(stateFile.text())
        root.status = parsed.status || "idle"
        root.label = parsed.text || ""
        root.updatedAt = Number(parsed.updated) || 0
      } catch (e) {
        root.status = "error"
        root.label = ""
        root.updatedAt = 0
      }
    }
    onLoadFailed: {
      root.status = "stopped"
      root.label = ""
      root.updatedAt = 0
      // See ShonaIndicator.qml: the daemon may not have written the state
      // file yet when the shell starts, and a failed read never gets a
      // second try on its own. Keep polling until the file exists.
      retryTimer.running = true
    }
  }

  Timer {
    id: retryTimer
    interval: 3000
    repeat: true
    onTriggered: stateFile.reload()
  }

  Timer {
    running: true
    interval: 1000
    repeat: true
    onTriggered: root.nowSeconds = Date.now() / 1000
  }

  PanelWindow {
    id: panel
    visible: root.visible_
    anchors { bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "shona-translate-caption"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    mask: Region {}
    implicitHeight: card.height + 48

    Rectangle {
      id: card
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 32
      width: Math.min(560, parent.width - 64)
      height: text.implicitHeight + 28
      radius: 14
      color: Color.background
      border.width: 1
      border.color: root.tint
      opacity: root.visible_ ? 0.96 : 0
      Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

      Row {
        anchors.centerIn: parent
        width: parent.width - 28
        spacing: 10

        Rectangle {
          width: 8
          height: 8
          radius: 4
          color: root.tint
          anchors.verticalCenter: parent.verticalCenter
          visible: root.busy

          SequentialAnimation on opacity {
            running: root.busy
            loops: Animation.Infinite
            NumberAnimation { from: 1.0; to: 0.25; duration: 550; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.25; to: 1.0; duration: 550; easing.type: Easing.InOutSine }
          }
        }

        Text {
          id: text
          width: parent.width - (root.busy ? 18 : 0)
          text: root.statusText
          color: Color.foreground
          wrapMode: Text.WordWrap
          maximumLineCount: 3
          elide: Text.ElideRight
          font.pixelSize: 15
        }
      }
    }
  }
}
