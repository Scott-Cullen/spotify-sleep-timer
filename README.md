# Spotify Sleep Timer

A HACS-ready Home Assistant custom integration that starts a Spotify playlist,
runs a sleep timer, stops playback when the timer expires, and keeps a mobile
app notification updated with the remaining time.

## What it does

- Starts a Spotify playlist on a selected `media_player` entity.
- Creates a Home Assistant sleep timer for the requested duration.
- Updates a mobile app notification with the remaining time.
- Stops the media player when the timer finishes.
- Exposes a sensor with the active timer state.

## Requirements

- Home Assistant with the Spotify integration already configured.
- A Spotify-capable `media_player` entity.
- The Home Assistant Companion App notification service for your phone, such as
  `notify.mobile_app_your_phone`.
- HACS for installation as a custom repository.

## Installation

1. Publish this folder as a GitHub repository.
2. In HACS, add it as a custom repository of type `Integration`.
3. Install **Spotify Sleep Timer**.
4. Restart Home Assistant.
5. Add **Spotify Sleep Timer** from **Settings > Devices & services**.

For manual installation, copy `custom_components/spotify_sleep_timer` into your
Home Assistant `config/custom_components` directory and restart Home Assistant.

## Usage

Call the `spotify_sleep_timer.start` service.

```yaml
service: spotify_sleep_timer.start
data:
  media_player: media_player.spotify_your_name
  playlist_uri: spotify:playlist:37i9dQZF1DX4WYpdgoIcn6
  duration: 1800
  notify_service: notify.mobile_app_your_phone
```

The notification is updated using the same mobile notification tag, so it should
replace itself instead of stacking a new notification every minute.

Cancel the current timer with:

```yaml
service: spotify_sleep_timer.cancel
data:
  timer_id: spotify_sleep_timer
```

If you omit `timer_id`, the integration uses `spotify_sleep_timer`.

## Dashboard example

```yaml
type: entities
entities:
  - entity: sensor.spotify_sleep_timer
```

## Notes

The integration delegates playback to Home Assistant's built-in
`media_player.play_media` and `media_player.media_stop` services. If Spotify
does not start, first confirm that the same playlist URI works through
Home Assistant Developer Tools.
