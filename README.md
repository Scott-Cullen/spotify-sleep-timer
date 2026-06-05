# Spotify Sleep Timer

A HACS-ready Home Assistant custom integration that starts Spotify playback,
runs a sleep timer, stops playback when the timer expires, and keeps a mobile
app notification updated with the remaining time.

## What it does

- Starts a Spotify playlist or resumes the current queue on a selected
  `media_player` entity.
- Exposes a playlist selector with `Current queue` and up to 5 named playlists.
- Connects to an existing Home Assistant Spotify integration entry.
- Creates a Home Assistant sleep timer for the requested duration.
- Creates a single Android chronometer notification that counts down locally.
- Stops the media player when the timer finishes.
- Exposes a sensor with the active timer state.

## Requirements

- Home Assistant with the Spotify integration already configured.
- A Spotify-capable `media_player` entity.
- The Home Assistant Companion App notify entity or legacy notify service for
  your phone.
- HACS for installation as a custom repository.

## Installation

1. Publish this folder as a GitHub repository.
2. In HACS, add it as a custom repository of type `Integration`.
3. Install **Spotify Sleep Timer**.
4. Restart Home Assistant.
5. Add **Spotify Sleep Timer** from **Settings > Devices & services**.
6. Select your existing Spotify integration entry, default Spotify media player,
   and default notify target.

For manual installation, copy `custom_components/spotify_sleep_timer` into your
Home Assistant `config/custom_components` directory and restart Home Assistant.

## Usage

Call the `spotify_sleep_timer.start` service.

```yaml
service: spotify_sleep_timer.start
data:
  duration: 1800
```

The integration uses the default Spotify media player chosen during setup. You
can still pass `media_player` in the service data to override that default for a
specific timer. If `playlist_uri` is omitted, the integration resumes whatever
is currently queued on the Spotify media player, unless you selected a recent
playlist in `select.spotify_sleep_timer_playlist`.

Notifications are sent to the default notify target chosen during setup. You can
still pass `notify_service` in the service data to override that target for a
specific timer.

Select your phone's notify entity during setup. For Android countdown options,
the integration automatically uses the matching Companion App mobile-app notify
action internally when Home Assistant exposes one, because the generic
`notify.send_message` entity action does not accept Android-specific countdown
fields.

To start a specific playlist instead, pass a Spotify playlist URI or link:

```yaml
service: spotify_sleep_timer.start
data:
  playlist_name: Sleep playlist
  playlist_uri: spotify:playlist:37i9dQZF1DX4WYpdgoIcn6
  duration: 1800
```

Every playlist started through this integration is saved into
`select.spotify_sleep_timer_playlist`, keeping the 5 most recent named
playlists. You can also save or rename a playlist without starting a timer:

```yaml
service: spotify_sleep_timer.save_playlist
data:
  playlist_name: Sleep playlist
  playlist_uri: spotify:playlist:37i9dQZF1DX4WYpdgoIcn6
```

The dashboard example includes editable text entities for saving playlists from
the card:

- `text.spotify_sleep_timer_playlist_name`
- `text.spotify_sleep_timer_playlist_url`

Enter a name and URL, tap **Save playlist**, then pick the saved name from
`select.spotify_sleep_timer_playlist`.

To remove a saved playlist, select it in `select.spotify_sleep_timer_playlist`
and call:

```yaml
service: spotify_sleep_timer.remove_playlist
```

The Spotify integration does not expose a general playback history to custom
integrations, so this selector tracks playlists saved or used by the sleep timer
itself.

On Android, the notification is sent once with a persistent tagged chronometer,
so the phone counts down locally instead of receiving a new notification every
minute. The integration clears that notification when the timer finishes or is
cancelled.

Cancel the current timer with:

```yaml
service: spotify_sleep_timer.cancel
data:
  timer_id: spotify_sleep_timer
```

If you omit `timer_id`, the integration uses `spotify_sleep_timer`.

## Dashboard example

For a ready-to-paste Lovelace card with 30, 60, and 90 minute buttons, see
[`examples/dashboard-card.yaml`](examples/dashboard-card.yaml).

```yaml
type: entities
entities:
  - entity: sensor.spotify_sleep_timer
  - entity: select.spotify_sleep_timer_playlist
```

## Notes

The integration delegates playback to Home Assistant's built-in
`media_player.media_play`, `media_player.play_media`, and
`media_player.media_stop` services. If Spotify does not start, first confirm
that the Spotify media player can resume from Home Assistant Developer Tools.
