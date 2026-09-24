"""Place outbound calls that connect the callee to the realtime voice agent.

Usage:
    uv run python -m app.outbound +15555550199 --dry-run
    uv run python -m app.outbound +15555550199
"""

from __future__ import annotations

import argparse
import re
import sys

import structlog
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from app.config import Settings, get_settings

logger = structlog.get_logger(__name__)

E164_RE = re.compile(r'^\+[1-9]\d{1,14}$')


class OutboundConfigError(ValueError):
    """Raised when the target number or the outbound settings are invalid."""


def outbound_twiml_url(settings: Settings) -> str:
    return f'{settings.public_base_url.rstrip("/")}/twiml/outbound'


def _validate(to: str, settings: Settings) -> None:
    if not E164_RE.match(to):
        raise OutboundConfigError(f'Target number must be in E.164 format like +15555550199, got {to!r}')
    required = {
        'TWILIO_ACCOUNT_SID': settings.twilio_account_sid,
        'TWILIO_AUTH_TOKEN': settings.twilio_auth_token,
        'TWILIO_PHONE_NUMBER': settings.twilio_phone_number,
        'PUBLIC_BASE_URL': settings.public_base_url,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise OutboundConfigError(f'Missing required setting(s) in .env: {", ".join(missing)}')


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
        print(f'Twilio error {exc.code} (HTTP {exc.status}): {exc.msg}', file=sys.stderr)
        return 1

    print(f'Call placed: {call_sid}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
