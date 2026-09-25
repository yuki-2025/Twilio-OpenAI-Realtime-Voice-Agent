"""Call console (NiceGUI), mounted at /ui by app.main.

Dial a number and watch every call's transcript live, inbound and outbound alike.
Only reachable from this machine; see app.access_guard.
"""

from __future__ import annotations

import asyncio
import bisect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo

from nicegui import ui
from twilio.base.exceptions import TwilioRestException

from app.call_events import CallEvent, CallEventHub, hub as default_hub, utc_now
from app.config import Settings
from app.outbound import E164_RE, OutboundConfigError, make_call

DIRECTION_ICONS = {'outbound': '↗', 'inbound': '↙'}
SPEAKERS = {'user': 'User', 'agent': 'Agent'}
SPEAKER_CLASSES = {'User': 'text-blue-700', 'Agent': 'text-emerald-700'}


@dataclass(frozen=True)
class Row:
    time: str
    direction: str
    remote: str
    speaker: str
    text: str
    is_status: bool


def format_event(event: CallEvent, tz: tzinfo | None = None) -> Row:
    """Turn an event into display strings; tz=None means this machine's local time zone."""
    if event.kind == 'transcript':
        speaker, text = SPEAKERS.get(event.role or '', ''), event.text
    elif event.kind == 'dialing':
        speaker, text = '', f'Dialing… ({event.call_sid})'
    elif event.kind == 'call_started':
        speaker, text = '', 'Call started'
    else:
        duration = f' ({round(event.duration_sec)}s)' if event.duration_sec is not None else ''
        speaker, text = '', f'Call ended{duration}'
    return Row(
        time=event.timestamp.astimezone(tz).strftime('%H:%M:%S'),
        direction=DIRECTION_ICONS.get(event.direction or '', ''),
        remote=event.remote_number,
        speaker=speaker,
        text=text,
        is_status=event.kind != 'transcript',
    )


@dataclass(frozen=True)
class DialResult:
    ok: bool
    message: str
    call_sid: str | None = None


async def dial(
    number: str,
    settings: Settings,
    *,
    hub: CallEventHub = default_hub,
    place_call: Callable[[str, Settings], str] = make_call,
) -> DialResult:
    """Place an outbound call for the Call button; failures come back as a message, never raise."""
    number = number.strip()
    if not E164_RE.match(number):
        return DialResult(False, 'Enter the number in E.164 format, e.g. +15555550199')
    try:
        # The Twilio SDK is blocking; keep it off the event loop that carries call audio.
        call_sid = await asyncio.to_thread(place_call, number, settings)
    except OutboundConfigError as exc:
        return DialResult(False, str(exc))
    except TwilioRestException as exc:
        return DialResult(False, f'Twilio error {exc.code} (HTTP {exc.status}): {exc.msg}')
    hub.publish(CallEvent(kind='dialing', call_sid=call_sid, timestamp=utc_now(), direction='outbound', remote_number=number))
    return DialResult(True, f'Calling {number} ({call_sid})', call_sid)


def register_console(settings: Settings, hub: CallEventHub = default_hub) -> None:
    @ui.page('/')
    async def console_page() -> None:
        ui.label('Voice Agent Console').classes('text-2xl font-semibold')

        with ui.row().classes('items-center gap-4'):
            number = ui.input('Number to call', placeholder='+15555550199').props('outlined dense').classes('w-64')
            call_button = ui.button('Call', icon='call')
            ui.label(f'Caller ID: {settings.twilio_phone_number or "not set"}').classes('text-sm text-gray-500')

        with ui.scroll_area().classes('w-full h-[75vh] border rounded') as scroll:
            log = ui.column().classes('w-full gap-1 font-mono text-sm p-2')

        timestamps: list[datetime] = []

        def add(event: CallEvent) -> None:
            row = format_event(event)
            # Keep rows chronological: a caller line is only final shortly after the agent starts replying.
            index = bisect.bisect_right(timestamps, event.timestamp)
            timestamps.insert(index, event.timestamp)
            with log:
                with ui.row().classes('w-full gap-3 no-wrap items-start') as line:
                    ui.label(row.time).classes('text-gray-500 shrink-0')
                    ui.label(f'{row.direction} {row.remote}').classes('text-gray-500 shrink-0 w-40')
                    ui.label(row.speaker).classes(f'shrink-0 w-12 font-bold {SPEAKER_CLASSES.get(row.speaker, "")}')
                    ui.label(row.text).classes('italic text-gray-500' if row.is_status else '')
            if index < len(timestamps) - 1:
                line.move(target_index=index)

        for event in hub.history():
            add(event)

        queue = hub.subscribe()
        ui.context.client.on_delete(lambda: hub.unsubscribe(queue))

        def drain() -> None:
            added = False
            while not queue.empty():
                add(queue.get_nowait())
                added = True
            if added:
                scroll.scroll_to(percent=1.0)

        ui.timer(0.2, drain)
        scroll.scroll_to(percent=1.0)

        async def on_call() -> None:
            call_button.disable()
            try:
                result = await dial(number.value or '', settings, hub=hub)
            finally:
                call_button.enable()
            ui.notify(result.message, type='positive' if result.ok else 'negative')

        call_button.on_click(on_call)
        number.on('keydown.enter', on_call)
