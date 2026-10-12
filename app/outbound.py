"""Place outbound calls that connect the callee to the realtime voice agent.

Usage:
    uv run python -m app.outbound +15555550199 --dry-run
    uv run python -m app.outbound +15555550199
"""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

import structlog
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from app.config import Settings, get_settings

logger = structlog.get_logger(__name__)

E164_RE = re.compile(r'^\+[1-9]\d{1,14}$')
ACTIVE_CALL_STATUSES = ('queued', 'ringing', 'in-progress')


class OutboundConfigError(ValueError):
    """Raised when the target number or the outbound settings are invalid."""


@dataclass(frozen=True)
class HangUpReport:
    ended: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]  # (call SID, reason)


def describe_twilio_error(exc: TwilioRestException) -> str:
    return f'Twilio error {exc.code} (HTTP {exc.status}): {exc.msg}'


def outbound_twiml_url(settings: Settings) -> str:
    return f'{settings.public_base_url.rstrip("/")}/twiml/outbound'


def _require_settings(settings: Settings, *, need_public_url: bool) -> None:
    required = {
        'TWILIO_ACCOUNT_SID': settings.twilio_account_sid,
        'TWILIO_AUTH_TOKEN': settings.twilio_auth_token,
        'TWILIO_PHONE_NUMBER': settings.twilio_phone_number,
    }
    if need_public_url:
        required['PUBLIC_BASE_URL'] = settings.public_base_url
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise OutboundConfigError(f'Missing required setting(s): {", ".join(missing)} (set them in .env or the environment)')
    if need_public_url:
        _check_public_base_url(settings.public_base_url)


def _is_unreachable_from_internet(host: str) -> bool:
    if host == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


def _check_public_base_url(url: str) -> None:
    # Twilio fetches <url>/twiml/outbound and then opens wss://<host>/twilio/...; a bad value
    # only shows up after the callee answers, as Twilio's "an application error has occurred".
    parsed = urlparse(url.strip())
    if parsed.scheme != 'https' or not parsed.hostname or _is_unreachable_from_internet(parsed.hostname) or parsed.path.strip('/'):
        raise OutboundConfigError(
            'PUBLIC_BASE_URL must be the public https:// address of this server with no path, '
            f'e.g. https://example.ngrok-free.app or https://<service>.onrender.com; got {url!r}'
        )


def _validate(to: str, settings: Settings) -> None:
    if not E164_RE.match(to):
        raise OutboundConfigError(f'Target number must be in E.164 format like +15555550199, got {to!r}')
    _require_settings(settings, need_public_url=True)


def make_call(to: str, settings: Settings, *, client: Client | None = None) -> str:
    """Place an outbound call from the configured Twilio number and return its Call SID."""
    _validate(to, settings)
    client = client or Client(settings.twilio_account_sid, settings.twilio_auth_token)
    call = client.calls.create(
        to=to,
        from_=settings.twilio_phone_number,
        url=outbound_twiml_url(settings),
        method='POST',
    )
    logger.info('outbound_call_created', call_sid=call.sid, to=to, from_=settings.twilio_phone_number)
    return call.sid


def hang_up_all(settings: Settings, *, client: Client | None = None) -> HangUpReport:
    """End every queued, ringing or in-progress call from or to TWILIO_PHONE_NUMBER, not the rest of the shared account."""
    _require_settings(settings, need_public_url=False)
    client = client or Client(settings.twilio_account_sid, settings.twilio_auth_token)
    number = settings.twilio_phone_number
    # dict keeps order and drops repeats: a call can move from ringing to in-progress between queries.
    sids = dict.fromkeys(
        call.sid
        for status in ACTIVE_CALL_STATUSES
        for party in ({'from_': number}, {'to': number})
        for call in client.calls.list(status=status, **party)
    )
    ended: list[str] = []
    failed: list[tuple[str, str]] = []
    for sid in sids:
        try:
            # 'completed' hangs up in-progress calls and cancels queued or ringing ones.
            client.calls(sid).update(status='completed')
        except TwilioRestException as exc:
            failed.append((sid, describe_twilio_error(exc)))
        else:
            ended.append(sid)
    logger.info('calls_hung_up', ended=ended, failed=[sid for sid, _ in failed])
    return HangUpReport(ended=tuple(ended), failed=tuple(failed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m app.outbound', description='Have the voice agent call a phone number.')
    parser.add_argument('to', help='Number to call, in E.164 format, e.g. +15555550199')
    parser.add_argument('--dry-run', action='store_true', help='Validate and print the call parameters without calling')
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        _validate(args.to, settings)
        if args.dry_run:
            print('DRY RUN - no call placed')
            print(f'To:   {args.to}')
            print(f'From: {settings.twilio_phone_number}')
            print(f'Url:  {outbound_twiml_url(settings)}')
            return 0
        call_sid = make_call(args.to, settings)
    except OutboundConfigError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
    except TwilioRestException as exc:
        print(describe_twilio_error(exc), file=sys.stderr)
        return 1

    print(f'Call placed: {call_sid}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
