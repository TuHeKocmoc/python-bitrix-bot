from tinkoff_voicekit_client import ClientSTT
from ..config import TINKOFF_API_KEY, TINKOFF_SECRET_KEY
import logging

stt_client = ClientSTT(TINKOFF_API_KEY, TINKOFF_SECRET_KEY)


def transcribe_wav_tinkoff(wav_path: str) -> str:
    config = {
        "encoding": "LINEAR16",
        "sample_rate_hertz": 16000,
        "num_channels": 1,
        "language_code": "ru-RU",
        "enable_automatic_punctuation": False
    }
    response = stt_client.recognize(wav_path, config=config)
    text_segments = []
    logging.debug(f"RAW CONTENT: {response}")
    for result in response["results"]:
        for alt in result["alternatives"]:
            text_segments.append(alt["transcript"])
    return " ".join(text_segments)
