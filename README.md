# shona-translate

Push-to-talk Shona → English speech translation for [Omarchy](https://omarchy.org/).
Click the bar button (or press your keybinding), speak Shona, click again, and
the English translation appears as a caption.

How it works: Google Cloud Speech-to-Text turns the audio into Shona text, then
Meta's NLLB-200 model translates it to English locally, on your GPU if you
have an NVIDIA card.

## Requirements

- Omarchy (Hyprland + the Omarchy shell)
- Python 3.10+
- About 7 GB of disk for the translation model (downloaded on first start)
- An NVIDIA GPU is recommended. Without one, translation runs on the CPU and
  takes several seconds longer per clip.
- Your own Google Cloud Speech-to-Text API key (see below)

## Install

```bash
git clone https://github.com/hosthobbit/shona-translate.git
cd shona-translate
./install.sh
```

This installs the background service, the `shona-translate` command, and the
bar indicator, caption, settings and history plugins.

## Google Speech-to-Text key

Each user needs their own key. **Never commit a key to this repo or share it**:
anyone who has it can run up charges on your Google account.

1. In the [Google Cloud console](https://console.cloud.google.com/), create a
   project (or pick an existing one).
2. Enable the **Cloud Speech-to-Text API** for it. Google requires a billing
   account on the project even if you stay within the free monthly minutes.
   Check Google's current pricing page for the limits.
3. Go to **APIs & Services → Credentials → Create credentials → API key**.
4. Edit the key and, under **API restrictions**, restrict it to the
   **Cloud Speech-to-Text API** only.
5. Save it where shona-translate looks for it, readable only by you:

   ```bash
   mkdir -p ~/.config/shona-translate
   install -m 600 /dev/null ~/.config/shona-translate/google-speech-key
   $EDITOR ~/.config/shona-translate/google-speech-key   # paste the key, save
   systemctl --user restart shona-translate
   ```

If the key is missing, the service logs
`no Google Speech-to-Text key at ~/.config/shona-translate/google-speech-key`
and doesn't start.

## Usage

```bash
shona-translate toggle   # start / stop recording (bind this to a key)
shona-translate status
shona-translate mics     # list microphones and their levels
```

Pick a specific microphone in `~/.config/shona-translate/config.toml`:

```toml
device = "PCM2902 Audio Codec Analog Stereo"
```

Logs and recent translations are in `~/.local/state/shona-translate/`.

## Privacy

Recorded audio is sent to Google for transcription. Translation happens
locally. The last 10 recordings are kept in
`~/.local/state/shona-translate/history/` so you can replay them.
