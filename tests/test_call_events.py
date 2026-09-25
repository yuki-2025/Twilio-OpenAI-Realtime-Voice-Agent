from __future__ import annotations

from datetime import UTC, datetime

from app.call_events import CallEvent, CallEventHub, CallReporter

FIXED_NOW = datetime(2026, 9, 24, 23, 0, 0, tzinfo=UTC)


def event(n: int) -> CallEvent:
    return CallEvent(
        kind='transcript',
        call_sid=f'CA{n}',
        timestamp=datetime(2026, 9, 24, 18, 0, n, tzinfo=UTC),
        direction='outbound',
        remote_number='+15555550199',
        role='user',
        text=f'utterance {n}',
    )


def drain(queue) -> list[CallEvent]:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_subscribers_receive_published_events_in_order():
    hub = CallEventHub()
    first, second = hub.subscribe(), hub.subscribe()

    hub.publish(event(1))
    hub.publish(event(2))

    assert [e.text for e in drain(first)] == ['utterance 1', 'utterance 2']
    assert [e.text for e in drain(second)] == ['utterance 1', 'utterance 2']


def test_unsubscribed_queue_stops_receiving():
    hub = CallEventHub()
    queue = hub.subscribe()
    hub.unsubscribe(queue)

    hub.publish(event(1))

    assert queue.empty()


def test_unsubscribing_an_unknown_queue_is_harmless():
    hub = CallEventHub()
    hub.unsubscribe(CallEventHub().subscribe())


def test_history_keeps_only_the_most_recent_events():
    hub = CallEventHub(history_size=3)

    for n in range(1, 6):
        hub.publish(event(n))

    assert [e.text for e in hub.history()] == ['utterance 3', 'utterance 4', 'utterance 5']


def test_history_includes_events_published_before_subscribing():
    hub = CallEventHub()
    hub.publish(event(1))

    hub.subscribe()

    assert [e.text for e in hub.history()] == ['utterance 1']


def test_full_subscriber_queue_does_not_block_or_starve_other_subscribers():
    hub = CallEventHub(queue_size=2)
    stuck = hub.subscribe()  # a browser tab that stopped draining
    healthy = hub.subscribe()

    hub.publish(event(1))
    hub.publish(event(2))
    assert [e.text for e in drain(healthy)] == ['utterance 1', 'utterance 2']

    hub.publish(event(3))  # `stuck` is full from here on; publish must neither raise nor block
    hub.publish(event(4))

    assert [e.text for e in drain(stuck)] == ['utterance 1', 'utterance 2']
    assert [e.text for e in drain(healthy)] == ['utterance 3', 'utterance 4']
    assert len(hub.history()) == 4


# --- CallReporter ------------------------------------------------------------


def reporter(hub: CallEventHub) -> CallReporter:
    return CallReporter(hub, call_sid='CAxyz', direction='outbound', remote_number='+15555550199', clock=lambda: FIXED_NOW)


def test_reporter_publishes_call_started_with_call_details():
    hub = CallEventHub()

    reporter(hub).started()

    assert hub.history() == [
        CallEvent(
            kind='call_started',
            call_sid='CAxyz',
            timestamp=FIXED_NOW,
            direction='outbound',
            remote_number='+15555550199',
        )
    ]


async def test_reporter_publishes_transcript_with_parsed_utc_timestamp():
    hub = CallEventHub()

    await reporter(hub).transcript('agent', 'Hi there', '2026-09-24T18:00:05.250+00:00')

    assert hub.history() == [
        CallEvent(
            kind='transcript',
            call_sid='CAxyz',
            timestamp=datetime(2026, 9, 24, 18, 0, 5, 250000, tzinfo=UTC),
            direction='outbound',
            remote_number='+15555550199',
            role='agent',
            text='Hi there',
        )
    ]


async def test_reporter_falls_back_to_now_for_missing_or_bad_timestamps():
    hub = CallEventHub()
    rep = reporter(hub)

    await rep.transcript('user', 'hello', '')
    await rep.transcript('user', 'again', 'not-a-timestamp')

    assert [e.timestamp for e in hub.history()] == [FIXED_NOW, FIXED_NOW]


def test_reporter_publishes_call_ended_with_duration():
    hub = CallEventHub()

    reporter(hub).ended(duration_sec=78.4)

    [ended] = hub.history()
    assert (ended.kind, ended.call_sid, ended.duration_sec) == ('call_ended', 'CAxyz', 78.4)
