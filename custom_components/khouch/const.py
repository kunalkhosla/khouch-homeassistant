"""Constants for the Khouch IPTV integration.

Khouch is a self-hosted web UI in front of an Xtream Codes IPTV panel
(repo ``iptv-webui-private``). This integration is a thin HA client over its
``/api/*`` surface: log in (cookie session), search the catalog, resolve a
playable/cast-ready stream URL, and cast it to a media_player.

Two services, by design split so an assistant can keep a human in the loop:
``khouch.search`` returns ALL matches (a query like "CNN" can hit several
channels) for the caller/model to disambiguate; ``khouch.play`` then streams
one specific result (by the opaque ``ref`` search handed back) to a media_player.
"""

from __future__ import annotations

DOMAIN = "khouch"

CONF_URL = "url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"  # noqa: S105
CONF_PROFILE = "profile"  # which Khouch profile to browse as (kid-blocking, etc.)

DEFAULT_SEARCH_LIMIT = 20

SERVICE_SEARCH = "search"
SERVICE_PLAY = "play"

# Khouch buckets a cross-catalog search into these modes.
MODES = ("live", "movie", "series")

# A play target is referenced by an opaque token search hands back, so the
# caller never has to know Khouch's id/mode/extension scheme: "<mode>:<id>:<ext>".
REF_SEP = ":"
