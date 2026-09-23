import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui

// Reads the state file the daemon writes on every transition, so the bar
// reflects what it's doing without polling a process.
BarWidget {
  id: root
  moduleName: "shona.indicator"

  property string status: "stopped"
  property string label: ""

  // Deliberately not a microphone glyph: omarchy-voice's indicator already
  // uses one, and the two plugins sitting side by side in the bar with
  // identical icons was indistinguishable at a glance. Translate (md-translate
  // / md-translate-off) reads as this plugin's actual job instead.
  readonly property var icons: ({
    "stopped":    "󰸆",
    "loading":    "󱚟",
    "idle":       "󰗊",
    "listening":  "󰗊",
    "processing": "󱚟",
    "error":      "󰸆"
  })

  FileView {
    id: state
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/shona-translate/state.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      retryTimer.running = false
      try {
        const parsed = JSON.parse(state.text())
        root.status = parsed.status || "idle"
        root.label = parsed.text || ""
      } catch (e) {
        root.status = "error"
        root.label = ""
      }
    }
    onLoadFailed: {
      root.status = "stopped"
      root.label = ""
      // The daemon can still be downloading/loading its model when the bar
      // starts, so the file may not exist yet. Without a retry, that one
      // failed read sticks forever: watchChanges only fires on writes to a
      // path it already has open, so a file created after this point is
      // never noticed. Keep trying until it shows up.
      retryTimer.running = true
    }
  }

  Timer {
    id: retryTimer
    interval: 3000
    repeat: true
    onTriggered: state.reload()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.icons[root.status] || root.icons["idle"]
    active: root.status === "listening" || root.status === "processing"
    tooltipText: root.label !== ""
                 ? "Shona -> English: " + root.label + "  (right-click: mic settings, middle-click: history)"
                 : "Shona translate: " + root.status + "  (right-click: mic settings, middle-click: history)"
    onPressed: function(b) {
      if (!root.bar) return
      if (b === Qt.RightButton) root.bar.run("omarchy-shell shell toggle shona.settings")
      else if (b === Qt.MiddleButton) root.bar.run("omarchy-shell shell toggle shona.history")
      else root.bar.run("shona-translate toggle")
    }
  }
}
