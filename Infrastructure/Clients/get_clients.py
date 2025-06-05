import logging
import asyncio
import os
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization
from Infrastructure.Clients.base_client import Environment
from Infrastructure.Clients.http_client import KalshiHttpClient
from Infrastructure.Clients.web_client import KalshiWebSocketClient

logging.basicConfig(level=logging.INFO)


def get_http_client():
    # Load environment variables
    load_dotenv()
    env = Environment.PROD  # toggle environment here
    KEYID = os.getenv('DEMO_KEYID') if env == Environment.DEMO else os.getenv('PROD_KEYID')
    KEYFILE = os.getenv('DEMO_KEYFILE') if env == Environment.DEMO else os.getenv('PROD_KEYFILE')

    try:
        with open(KEYFILE, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None  # Provide the password if your key is encrypted
            )
    except FileNotFoundError:
        raise FileNotFoundError(f"Private key file not found at {KEYFILE}")
    except Exception as e:
        raise Exception(f"Error loading private key: {str(e)}")

    # Initialize the HTTP client
    client = KalshiHttpClient(
        key_id=KEYID,
        private_key=private_key,
        environment=env
    )

    return client


def get_websocket_client(tickers, state, update):
    # Load environment variables
    load_dotenv()
    env = Environment.PROD  # toggle environment here
    KEYID = os.getenv('DEMO_KEYID') if env == Environment.DEMO else os.getenv('PROD_KEYID')
    KEYFILE = os.getenv('DEMO_KEYFILE') if env == Environment.DEMO else os.getenv('PROD_KEYFILE')

    try:
        with open(KEYFILE, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None  # Provide the password if your key is encrypted
            )
    except FileNotFoundError:
        raise FileNotFoundError(f"Private key file not found at {KEYFILE}")
    except Exception as e:
        raise Exception(f"Error loading private key: {str(e)}")

    # Initialize the WebSocket client
    ws_client = KalshiWebSocketClient(
        tickers=tickers,
        state=state,
        update=update,
        key_id=KEYID,
        private_key=private_key,
        environment=env
    )
    return ws_client
