import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons

// Mic picker for shona-translate: shows every input device, a live peak
// meter while testing one, and plays back what it just recorded so you can
// actually hear what the daemon would hear. Everything talks to the running
// daemon through the `shona-translate` CLI (devices.json / mic-test.json /
// level are the daemon's side of that conversation; see shona_translate.daemon).
Item {
  id: root

  property bool opened: false
  property var devices: []
  property string currentDevice: ""
  property string testingDevice: ""
  property string errorMessage: ""
  property real levelValue: 0
  property string lastTestDevice: ""
  property real lastTestPeak: -1
  property string lastTestWav: ""
  readonly property string fontFamily: Style.font.family

  function open(_payloadJson) {
    root.opened = true
    root.errorMessage = ""
    devicesProc.running = true
  }

  function close() {
    root.opened = false
  }

  function dismiss() {
    root.close()
  }

  function startTest(name) {
    if (root.testingDevice !== "") return
    root.errorMessage = ""
    root.levelValue = 0
    root.testingDevice = name
    if (testProc.running) testProc.running = false
    testProc.command = ["shona-translate", "test-mic", name]
    testProc.running = true
    testTimeout.restart()
  }

  function useDevice(name) {
    if (useProc.running) useProc.running = false
    useProc.command = ["shona-translate", "set-device", name]
    useProc.running = true
  }

  function replayLast() {
    if (root.lastTestWav === "") return
    if (replayProc.running) replayProc.running = false
    replayProc.command = ["paplay", root.lastTestWav]
    replayProc.running = true
  }

  // A test always finishes on its own (recording is a fixed length daemon
  // side), but this is the fallback if the result file somehow never lands.
  Timer {
    id: testTimeout
    interval: 10000
    onTriggered: {
      root.testingDevice = ""
      root.errorMessage = "Microphone test timed out. Please try again."
    }
  }

  FileView {
    id: devicesFile
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/shona-translate/devices.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        const parsed = JSON.parse(devicesFile.text())
        root.devices = Array.isArray(parsed.devices) ? parsed.devices : []
        root.currentDevice = parsed.current || ""
      } catch (e) {}
    }
  }

  FileView {
    id: testFile
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/shona-translate/mic-test.json"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        const parsed = JSON.parse(testFile.text())
        root.lastTestDevice = parsed.device || ""
        root.lastTestPeak = parsed.peak !== undefined ? Number(parsed.peak) : -1
        root.lastTestWav = parsed.wav || ""
        if (parsed.device === root.testingDevice) root.testingDevice = ""
      } catch (e) {}
    }
  }

  // Its own file, rewritten several times a second by the daemon while a
  // test runs — polled rather than watched, same reasoning as voice.orb's
  // level file (an atomic-replace churns the inode too fast for inotify to
  // be the cheaper option).
  FileView {
    id: levelFile
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/shona-translate/level"
    onLoaded: {
      const value = parseFloat(levelFile.text())
      root.levelValue = isFinite(value) ? Math.max(0, Math.min(1, value)) : 0
    }
    onLoadFailed: root.levelValue = 0
  }

  Timer {
    running: root.testingDevice !== ""
    interval: 60
    repeat: true
    onTriggered: levelFile.reload()
    onRunningChanged: if (!running) root.levelValue = 0
  }

  Process { id: devicesProc; command: ["shona-translate", "devices"] }
  Process {
    id: testProc
    command: ["shona-translate"]
    stdout: StdioCollector {
      onStreamFinished: {
        const reply = text.trim()
        if (reply.startsWith("error:")) root.errorMessage = reply.slice(6).trim()
      }
    }
    stderr: StdioCollector {
      onStreamFinished: {
        if (text.trim() !== "") root.errorMessage = text.trim()
      }
    }
    onExited: (exitCode, exitStatus) => {
      testTimeout.stop()
      root.testingDevice = ""
      testFile.reload()
      if (exitCode !== 0 && root.errorMessage === "")
        root.errorMessage = "Microphone test failed. Check that the translation service is running."
    }
  }
  Process { id: useProc; command: ["shona-translate"] }
  Process { id: replayProc; command: ["paplay"] }

  PanelWindow {
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "shona-translate-settings"
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
        width: 520
        height: content.implicitHeight + 40
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
              text: "Shona translate — microphone"
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
            text: "Click Test and speak for three seconds to see the input level and hear it back. Click Use to select a microphone."
            color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.7)
            font.family: root.fontFamily
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
          }

          Text {
            visible: root.errorMessage !== ""
            text: root.errorMessage
            color: Color.accent
            font.family: root.fontFamily
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
          }

          Repeater {
            model: root.devices
            delegate: Rectangle {
              required property string modelData
              Layout.fillWidth: true
              height: row.implicitHeight + 16
              radius: 8
              color: modelData === root.currentDevice
                     ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.14)
                     : "transparent"
              border.width: modelData === root.currentDevice ? 1 : 0
              border.color: Color.accent

              RowLayout {
                id: row
                anchors.fill: parent
                anchors.margins: 8
                spacing: 10

                Text {
                  text: modelData === root.currentDevice ? "●" : "○"
                  color: Color.accent
                  font.pixelSize: 12
                }

                Text {
                  text: modelData
                  color: Color.foreground
                  font.family: root.fontFamily
                  font.pixelSize: 13
                  Layout.fillWidth: true
                  elide: Text.ElideRight
                }

                Text {
                  visible: root.testingDevice === modelData
                  text: Math.round(root.levelValue * 100) + "%"
                  color: Color.accent
                  font.family: root.fontFamily
                  font.pixelSize: 12
                }

                Rectangle {
                  visible: root.testingDevice === modelData
                  width: 60; height: 8; radius: 4
                  color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.15)
                  Rectangle {
                    width: parent.width * root.levelValue
                    height: parent.height
                    radius: 4
                    color: Color.accent
                  }
                }

                Text {
                  text: root.testingDevice === modelData ? "listening..." : "Test"
                  color: Color.accent
                  font.family: root.fontFamily
                  font.pixelSize: 12
                  opacity: root.testingDevice !== "" && root.testingDevice !== modelData ? 0.4 : 1.0
                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    enabled: root.testingDevice === "" || root.testingDevice === modelData
                    onClicked: root.startTest(modelData)
                  }
                }

                Text {
                  text: modelData === root.currentDevice ? "in use" : "Use"
                  color: modelData === root.currentDevice ? Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.4) : Color.foreground
                  font.family: root.fontFamily
                  font.pixelSize: 12
                  MouseArea {
                    anchors.fill: parent
                    cursorShape: modelData === root.currentDevice ? Qt.ArrowCursor : Qt.PointingHandCursor
                    enabled: modelData !== root.currentDevice
                    onClicked: root.useDevice(modelData)
                  }
                }
              }
            }
          }

          Rectangle {
            Layout.fillWidth: true
            visible: root.lastTestDevice !== ""
            height: lastRow.implicitHeight + 16
            radius: 8
            color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.06)

            RowLayout {
              id: lastRow
              anchors.fill: parent
              anchors.margins: 8
              spacing: 10
              Text {
                text: "Last test: " + root.lastTestDevice
                      + (root.lastTestPeak >= 0 ? "  — peak " + root.lastTestPeak.toFixed(3) : "")
                color: Color.foreground
                font.family: root.fontFamily
                font.pixelSize: 12
                Layout.fillWidth: true
                elide: Text.ElideRight
              }
              Text {
                text: "▶ Play again"
                color: Color.accent
                font.family: root.fontFamily
                font.pixelSize: 12
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.replayLast() }
              }
            }
          }
        }
      }
    }
  }
}
