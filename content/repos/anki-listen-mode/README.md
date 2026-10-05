# Listen Mode — a hands-free, auto-advancing playback mode for Anki

An [Anki](https://apps.ankiweb.net/) add-on that adds a **Listen (Hands-free)**
mode: it reads through a deck (or just the due queue) out loud, card by card,
advancing on its own — no clicking, no grading, just listening. If a note
type happens to have an example-sentence or synonyms field, those get read
too.

## Why this exists, and how it fits into Anki

Anki's core has no concept of "words" — it's a general-purpose spaced
repetition tool, and decks are entirely user-defined. So this add-on is
built to be generic:

- **Hands-free playback** works on *any* note type. It reads the rendered
  question, then the rendered answer (with the repeated front text
  stripped out, since most templates restate `{{FrontSide}}`).
- **Example sentence / synonyms** are opt-in: if a note type happens to
  have a field named `Example` (or `Sentence`, `Usage`, ...) and/or
  `Synonyms` (or `Synonym`, ...), those get shown and read after the
  answer. Field names are configurable in case yours differ
  ([config.md](config.md)).
- **Speech** is not reimplemented here — it hooks into Anki's own
  `{{tts xx_YY:Field}}` engine (`anki.sound.TTSTag` /
  `aqt.sound.av_player`), the same mechanism card templates already use.
  No API keys, no network calls, no bundled TTS engine.
- **Sync is untouched.** This add-on only *reads* cards and notes
  (`card.question()`, `card.answer()`, `note.items()`) — it never writes
  to the collection, so it has zero interaction with Anki's sync system.
  It works identically whether or not you have sync configured.

## Install

1. Copy this folder into your Anki add-ons directory as `listen_mode`:
   - Windows: `%APPDATA%\Anki2\addons21\listen_mode`
   - macOS: `~/Library/Application Support/Anki2/addons21/listen_mode`
   - Linux: `~/.local/share/Anki2/addons21/listen_mode`
2. Restart Anki.

(Packaging as a `.ankiaddon` for AnkiWeb is just zipping this folder's
contents at the top level — `manifest.json` at the zip root.)

## Use

- **Tools → Listen (Hands-free)…** — pick a deck, whether to include the
  whole deck or just what's due, and a play order, then it opens the
  player: Play/Pause, Prev/Next, and it keeps going by itself.
- **Browser → select some notes → Notes → Listen to Selected Notes…** —
  same player, seeded from an arbitrary search/selection instead of a
  deck.

Neither entry point touches scheduling or grades — it's closer to Anki's
own *Preview* than to *Study*, just hands-free and read aloud.

## Configuration

See [config.md](config.md) — speaking rate, gap between fields/cards, TTS
language, and the field-name lists used to detect example/synonyms
fields.

## Development

`textutils.py` (HTML→text cleanup, front/back de-duplication, field
matching) is plain Python with no `anki`/`aqt` import, so it's unit
tested without needing an Anki install:

```bash
python -m unittest discover -s tests -v
```

The rest (`listen.py`, `__init__.py`) is real Qt/`aqt` code and was
checked against Anki 26.8.1's actual `anki`/`aqt` source (not just docs)
for every API it calls, and exercised both by loading it in a real,
isolated Anki profile (`Anki.exe -b <empty base dir>`, so it never
touches a real collection or triggers a sync) and by running its exact
note/card-handling logic against a real `anki.collection.Collection` with
a custom note type. It hasn't been driven through the Qt UI itself
(clicking through the dialog), since that needs a human at a screen —
give it a try and open an issue if something in the dialog itself
misbehaves.

## Contributing

This is a standalone add-on, not a patch to Anki's own core (`ankitects/anki`
is a large Rust + Python + TypeScript/Svelte monorepo with its own build
toolchain — a good add-on is the normal way to ship a new feature like this
without going through that). Contributions, issues and PRs against *this*
repo are welcome. If a maintainer ever wanted a piece of this folded into
Anki core directly, that would be a separate, from-scratch implementation
in Rust/Svelte against their codebase and conventions.

## License

AGPL-3.0, matching `anki`/`aqt`. See [LICENSE](LICENSE).
