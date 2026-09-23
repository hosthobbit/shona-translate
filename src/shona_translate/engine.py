"""Shona speech to English text, in two stages.

Transcription (Shona audio -> Shona text) is Google Cloud Speech-to-Text,
not a local model. It used to be faster-whisper (large-v3) running on this
machine, but generic Whisper has almost no real Shona in its training data,
and it showed on real use: garbled transcripts, and a tendency to
hallucinate fluent-sounding English ("Thank you for watching", a classic
Whisper artifact from its YouTube-caption training data) on any clip it
couldn't make out, rather than admitting it couldn't hear it. Tested head to
head on the same real recordings, Google's API produced fluent, accurate
Shona on most clips, and on the few it couldn't parse confidently, returned
nothing rather than a confident wrong guess. Needs
~/.config/shona-translate/google-speech-key (an API key restricted to the
Cloud Speech-to-Text API) — see config.google_speech_key().

Translation (Shona text -> English text) is still a dedicated local MT
model (NLLB-200) rather than Google's Translate API — NLLB already benchmarks
as the best readily-available option for Shona on FLORES-101, and keeping it
local avoids a second paid API for a stage that wasn't the problem: once the
Shona text going in is actually correct, this stage does fine with it.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request

import ctranslate2
import numpy as np
from transformers import AutoTokenizer

from .config import (
    GOOGLE_SPEECH_KEY_FILE,
    MT_CT2_DIR,
    MT_MODEL_NAME,
    MT_SOURCE_LANG,
    MT_TARGET_LANG,
    SAMPLE_RATE,
    SOURCE_LANGUAGE,
    google_speech_key,
)

MIN_SAMPLES_AT_16K = 3200  # 0.2s — anything shorter is a misfire, not speech
MAX_TRANSLATED_TOKENS = 256  # generous for one push-to-talk utterance
# Base allowance plus time to upload the clip itself: a long clip is ~1.7MB
# of base64 PCM, which a fixed 15s timed out on while the link was busy.
GOOGLE_STT_TIMEOUT_SECONDS = 15
GOOGLE_STT_ATTEMPTS = 2  # one retry for a dropped/stalled connection
GOOGLE_STT_URL = "https://speech.googleapis.com/v1/speech:recognize"

# Google returns Shona as one unpunctuated, all-lowercase run (it has no
# punctuation model for sn-ZW), and NLLB, trained on sentence-level text,
# falls apart on a 60-word run-on: the tail of a long clip came out as word
# salad. Word timestamps do mark where the speaker paused, though, and a
# pause this long is nearly always a sentence/clause boundary — so each
# stretch between pauses is translated as its own sentence.
SENTENCE_PAUSE_SECONDS = 0.7

# Lowercase from Google, "kuharare" reads to NLLB as a common noun ("went to
# the nursery"); written the standard Shona way, "kuHarare", it's kept as the
# place name. Only these proper nouns are touched — tested against real
# clips, capitalizing or punctuating the rest of the Shona input made NLLB
# drop clauses ("ndirikuda kudya ndinonzara" lost "I'm hungry"), so the
# Shona otherwise goes in exactly as Google heard it.
PLACE_NAMES = (
    "harare", "bulawayo", "mutare", "gweru", "masvingo", "kwekwe", "kadoma",
    "chitungwiza", "marondera", "bindura", "chinhoyi", "hwange", "beitbridge",
    "chegutu", "zvishavane", "kariba", "rusape", "chiredzi", "gokwe", "epworth",
    "zimbabwe", "zambia", "mozambique", "botswana", "malawi", "namibia",
    "johannesburg", "joburg", "england", "london", "america",
)
# Shona locative/possessive/associative prefixes that attach to a noun
# ("kuHarare", "muHarare", "kweHarare", "neZimbabwe").
_PLACE_PREFIXES = "ku|kwa|kwe|mu|pa|pe|ne|na|we|ye|ve|re|dze|rwe|se|sa|che|ze|he|ri|i"
_PLACE_RE = re.compile(
    rf"\b({_PLACE_PREFIXES})?({'|'.join(sorted(PLACE_NAMES, key=len, reverse=True))})\b"
)


class MissingGoogleKey(Exception):
    """No key at GOOGLE_SPEECH_KEY_FILE — nothing to authenticate with."""


class Engine:
    def __init__(self) -> None:
        self._google_key = google_speech_key()
        if not self._google_key:
            raise MissingGoogleKey(
                f"no Google Speech-to-Text key at {GOOGLE_SPEECH_KEY_FILE}"
            )

        # On the GPU via CTranslate2: on CPU (torch) this stage took ~15s
        # for a 13s clip — four fifths of the wait — and ~1s on the GTX
        # 1070 Ti. float32 because Pascal has no fast float16, and it keeps
        # output identical to the CPU model's. Falls back to CPU if CUDA
        # isn't there, rather than refusing to start.
        _ensure_ct2_model()
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        self._mt_tokenizer = AutoTokenizer.from_pretrained(
            MT_MODEL_NAME, src_lang=MT_SOURCE_LANG
        )
        self._mt_model = ctranslate2.Translator(
            str(MT_CT2_DIR), device=device, compute_type="float32"
        )

    def translate(self, audio: np.ndarray) -> str:
        _shona_text, english_text = self.transcribe_and_translate(audio)
        return english_text

    def transcribe_and_translate(self, audio: np.ndarray) -> tuple[str, str]:
        """Both stages' output, so callers can log the Shona text too —

        it's the only way to tell a mishearing (the STT stage) apart from
        an untranslated word (the MT stage) when quality is off.
        """
        if audio.size < MIN_SAMPLES_AT_16K:
            return "", ""
        sentences = self._transcribe(audio)
        if not sentences:
            return "", ""
        english = self._translate_sentences([_mark_place_names(s) for s in sentences])
        return " ".join(sentences), " ".join(english)

    def _transcribe(self, audio: np.ndarray) -> list[str]:
        """Shona text, split into sentences wherever the speaker paused."""
        pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        body = json.dumps({
            "config": {
                "encoding": "LINEAR16",
                "sampleRateHertz": SAMPLE_RATE,
                "languageCode": SOURCE_LANGUAGE,
                "enableWordTimeOffsets": True,
            },
            "audio": {"content": base64.b64encode(pcm16.tobytes()).decode()},
        }).encode()
        request = urllib.request.Request(
            f"{GOOGLE_STT_URL}?key={self._google_key}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = GOOGLE_STT_TIMEOUT_SECONDS + audio.size / SAMPLE_RATE
        for attempt in range(1, GOOGLE_STT_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                raise RuntimeError(f"Google Speech-to-Text request failed ({exc.code}): {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == GOOGLE_STT_ATTEMPTS:
                    reason = getattr(exc, "reason", exc)
                    raise RuntimeError(f"Google Speech-to-Text unreachable: {reason}") from exc

        # Low-confidence audio comes back with no results at all, or a
        # result whose sole alternative has no `transcript` key — Google's
        # way of saying it couldn't make out anything worth returning,
        # rather than guessing. Treated the same as silence.
        sentences = []
        for result in data.get("results", []):
            alternatives = result.get("alternatives", [])
            if alternatives and "transcript" in alternatives[0]:
                sentences.extend(_split_at_pauses(alternatives[0]))
        return [s for s in sentences if s]

    def _translate_sentences(self, sentences: list[str]) -> list[str]:
        """One batched generate call for all of an utterance's sentences."""
        tokenized = [
            self._mt_tokenizer.convert_ids_to_tokens(self._mt_tokenizer.encode(s))
            for s in sentences
        ]
        results = self._mt_model.translate_batch(
            tokenized,
            target_prefix=[[MT_TARGET_LANG]] * len(tokenized),
            max_decoding_length=MAX_TRANSLATED_TOKENS,
            # Was greedy decoding — picks one word at a time and never
            # reconsiders, which both runs away into "ta ta ta ta ..." on a
            # repetitive/garbled source line and gives flatter phrasing.
            # Beam search keeps the best-scoring of several candidates, and
            # no_repeat_ngram_size stops the runaway loops. No
            # repetition_penalty: in CTranslate2 it made the model end long
            # sentences early, dropping their last clause.
            beam_size=5,
            no_repeat_ngram_size=3,
        )
        decoded = [
            self._mt_tokenizer.decode(
                self._mt_tokenizer.convert_tokens_to_ids(r.hypotheses[0][1:]),  # [0] is the language tag
                skip_special_tokens=True,
            )
            for r in results
        ]
        return [_tidy_english(text) for text in decoded if text.strip()]


def _ensure_ct2_model() -> None:
    """Convert the Hugging Face NLLB checkpoint once, into a temp dir then
    renamed, so a conversion interrupted halfway never looks finished."""
    if (MT_CT2_DIR / "model.bin").exists():
        return
    tmp = MT_CT2_DIR.with_name(MT_CT2_DIR.name + ".partial")
    ctranslate2.converters.TransformersConverter(MT_MODEL_NAME).convert(
        str(tmp), force=True
    )
    tmp.replace(MT_CT2_DIR)


def _split_at_pauses(alternative: dict) -> list[str]:
    words = alternative.get("words") or []
    if not words:
        return [alternative["transcript"].strip()]
    sentences: list[list[str]] = [[]]
    previous_end = None
    for word in words:
        start = _seconds(word.get("startTime", "0s"))
        if previous_end is not None and start - previous_end >= SENTENCE_PAUSE_SECONDS:
            sentences.append([])
        sentences[-1].append(word["word"])
        previous_end = _seconds(word.get("endTime", "0s"))
    return [" ".join(s) for s in sentences if s]


def _seconds(duration: str) -> float:
    """Google's Duration JSON form: "1.300s"."""
    try:
        return float(duration.rstrip("s"))
    except ValueError:
        return 0.0


def _mark_place_names(text: str) -> str:
    return _PLACE_RE.sub(lambda m: (m.group(1) or "") + m.group(2).title(), text)


def _tidy_english(text: str) -> str:
    """Capital letter and closing full stop, so joined sentences read as prose.

    Done on the English output rather than the Shona input: it can't change
    what NLLB understood, only how the result looks on the caption card.
    """
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in ".?!\"'":
        text += "."
    return text
