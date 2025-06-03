import asyncio
import logging
import datetime
from datetime import datetime
import json

from cryptography.hazmat.primitives.asymmetric import rsa

import websockets

from KalshiDogecoin.state import TradingState
from KalshiDogecoin.clients.base_client import Environment, KalshiBaseClient


class KalshiWebSocketClient(KalshiBaseClient):
    def __init__(
        self,
        key_id: str,
        tickers: list,
        state: TradingState,
        update: asyncio.Event,
        private_key: rsa.RSAPrivateKey,
        environment: Environment = Environment.DEMO,
    ):
        super().__init__(key_id, private_key, environment)
        self.ws = None
        self.url_suffix = "/trade-api/ws/v2"
        self.message_id = 1  # Add counter for message IDs

        if isinstance(tickers, str):
            tickers = [tickers]
        self.tickers = tickers

        self.subscriptions = {}
        self._running = False
        self._sid = None

        self.ob_seq_ = -1
        self.error_count = 0
        self.state = state
        self.update = update
        logging.info("Initialized Web Socket...")

    async def connect(self):
        logging.info("Connecting to websocket...")
        host = self.WS_BASE_URL + self.url_suffix
        auth_headers = self.request_headers("GET", self.url_suffix)
        self.ws = await websockets.connect(host, additional_headers=auth_headers)
        logging.info("Successfully connected to websocket.")

    async def handler(self):
        try:
            async for message in self.ws:
                await self.consume(message)
        except websockets.ConnectionClosed as e:
            await self.close(e.code, e.reason)
        except Exception as e:
            await self.on_error(e)

    async def resubscribe(self):
        self.error_count += 1
        await asyncio.sleep(1)
        logging.info("Attempting to resubscribe...")
        await self.subscribe()

    async def subscribe(self):
        try:
            logging.info("Subscribing to tickers...")
            subscription_message = {
                    "id": self.message_id
                    , "cmd": "subscribe"
                    , "params": {
                        "channels": ["orderbook_delta", "fill"]
                        , "market_tickers": self.tickers
                    }
                }
            await self.ws.send(json.dumps(subscription_message))
            self.message_id += 1
        except Exception as e:
            logging.warning("Failed to subscribe: " + str(e))
            await self.resubscribe()

    async def consume(self, raw_message):
            # logging.info(datetime.now().strftime("%H:%M:%S") + ": Received message:" + raw_message)
            message = json.loads(raw_message)
            if message["type"] == "orderbook_delta" or message["type"] == "orderbook_snapshot":
                msgSeq = message["seq"]

                if msgSeq != (self.ob_seq_ + 1) and self.ob_seq_ != -1:
                    logging.warning("Out of order message received, restarting connection...")
                    await self.ws.close()
                    self._running = False

                self.ob_seq_ = msgSeq

            elif message["type"] == "subscribed":
                logging.info(datetime.now().strftime("%H:%M:%S") + ": Subscribed to " + str(message["msg"]))
            else:
                logging.warning(datetime.now().strftime("%H:%M:%S") + ": Unknown message type: " + message["type"])

            self.update_state(raw_message)

    def update_state(self, message):
        data = json.loads(message)
        if data["type"] == "orderbook_snapshot":
            self.state.set_orderbooks(data["msg"])
        elif data["type"] == "orderbook_delta":
            self.state.update_orderbooks(data["msg"])
        # elif data["type"] == "fill":
        #     self.state.update_positions(data["msg"])

        self.update.set()

    async def on_error(self, error):
        logging.info("WebSocket error:" + str(error))
        self.error_count += 1
        await asyncio.sleep(1)
        logging.info("Attempting to resubscribe...")
        await self.subscribe()

    async def close(self, code, reason):
        logging.info("WebSocket connection closed with code:", code, "and message:", reason)
        if self.ws:
            await self.ws.close()
            self.ws = None
            self._running = False

    async def run(self):
        while True:
            try:
                if not self._running:
                    await self.connect()
                    await self.subscribe()
                    self._running = True
                await self.handler()
            except websockets.WebSocketException as e:
                logging.warning("Connection dropped, restarting...")
                await self.close("WebSocketException", str(e))
                self._running = False
