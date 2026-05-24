from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', case_sensitive=False, extra='ignore')

    app_name: str = Field(default='twilio-openai-realtime-example')
    host: str = Field(default='0.0.0.0')
    port: int = Field(default=8000)
    public_base_url: str = Field(default='')

    openai_api_key: str = Field(default='')
    openai_realtime_model: str = Field(default='gpt-4o-realtime-preview')
    openai_transcription_model: str = Field(default='gpt-4o-transcribe')
    openai_voice: Literal['alloy', 'ash', 'ballad', 'cedar', 'coral', 'echo', 'fable', 'marin', 'nova', 'onyx', 'sage', 'shimmer', 'verse'] = Field(default='marin')
    openai_tts_speed: float = Field(default=1.0)

    agent_instructions: str = Field(default='You are a helpful voice assistant. Keep responses brief and natural.')
    agent_greeting: str = Field(default='Hello, how can I help you today?')

    twilio_account_sid: str = Field(default='')
    twilio_auth_token: str = Field(default='')

    @property
    def websocket_url(self) -> str:
        base = self.public_base_url.rstrip('/')
        if not base:
            return '/twilio/dev-session'
        parsed = urlparse(base)
        scheme = 'wss' if parsed.scheme == 'https' else 'ws'
        return f'{scheme}://{parsed.netloc}/twilio/dev-session'


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
