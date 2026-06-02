# Khouch IPTV for Home Assistant

A Home Assistant integration for [Khouch](https://github.com/kunalkhosla/iptv-webui) — a
self-hosted IPTV player (an Xtream Codes web UI). It lets Home Assistant **search** your
Khouch catalog (live channels, movies, series) and **cast** any result to a media player.

It is deliberately small and self-contained: it owns all the IPTV specifics, and exposes
just two services. That keeps it easy to drive from a voice assistant, a dashboard button,
or an automation — and it pairs naturally with an LLM voice agent, because search returns
*all* matches so the agent can confirm the right one with you before playing.

## Install

1. HACS → Custom repositories → add this repo as an **Integration**.
2. Install **Khouch IPTV**, restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *Khouch IPTV*.
4. Enter your **Khouch URL** (e.g. `https://iptv.example.com`), **username**, and
   **password**. The URL can be changed later via the integration's **Reconfigure**
   action — no need to remove and re-add.

## Services

### `khouch.search`
Searches the whole catalog and returns **every match** (a query like `CNN` often hits
several channels), each with an opaque `ref`.

```yaml
action: khouch.search
data:
  query: CNN
  kind: live      # optional: live | movie | series
response_variable: hits
```

Response:

```yaml
query: CNN
count: 3
results:
  - { ref: "live:1201:m3u8", title: "CNN HD",            kind: live, category: "News" }
  - { ref: "live:1202:m3u8", title: "CNN International",  kind: live, category: "News" }
  - { ref: "movie:88431:mp4", title: "CNN: The Eighties", kind: movie, year: 2015 }
```

### `khouch.play`
Streams one result (by its `ref`) to a media player.

```yaml
action: khouch.play
data:
  ref: "live:1201:m3u8"
  entity_id: media_player.kitchen_display
```

## Driving it from a voice assistant (search → confirm → play)

Expose two thin wrapper **scripts** to your assistant. The assistant calls `search`, reasons
over the candidates, confirms the right one with you, then calls `play`. The room→player
mapping lives here (in your config), not in the assistant — so the assistant stays generic.

```yaml
# scripts.yaml
search_tv:
  alias: Search TV
  fields:
    query: { description: What to search for, example: CNN }
    kind:  { description: "Optional: live, movie, or series", example: live }
  sequence:
    - action: khouch.search
      data:
        query: "{{ query }}"
        kind: "{{ kind | default('', true) }}"
      response_variable: hits
    - stop: ""
      response_variable: hits

stream_tv:
  alias: Stream TV
  fields:
    ref:  { description: The ref of the chosen result from search_tv }
    room: { description: Which room, example: kitchen }
  sequence:
    - variables:
        players:
          kitchen: media_player.kitchen_display
          living_room: media_player.living_room_tv
          family_room: media_player.family_room_tv
          basement: media_player.basementht_tv
    - action: khouch.play
      data:
        ref: "{{ ref }}"
        entity_id: "{{ players[room | lower] | default('media_player.kitchen_display') }}"
```

Expose `script.search_tv` and `script.stream_tv` to your assistant (Settings → Voice
assistants → Expose). Then *"stream CNN to the kitchen"* becomes: the assistant searches,
asks *"CNN HD or CNN International?"* if there's more than one, and streams your pick.

## Notes

- **Codecs / casting:** Khouch decides direct-play vs. transcode per item and hands back a
  cast-ready URL, so HLS-only Cast targets and surround audio are handled server-side.
- **Series** currently resolve at the series level; per-episode selection is a future addition.
- Built against the Khouch (`iptv-webui`) `/api/*` surface: `POST /api/login`,
  `GET /api/search/all`, `GET /api/stream/<mode>/<id>.<ext>`.
