import asyncio
import logging
from datetime import datetime, timezone
import pandas as pd
import math
from Infrastructure.Clients.http_client import KalshiHttpClient
from Infrastructure.state import TradingState
from Infrastructure.market import Market
from Baseball.BaseballGame import BaseballGame


class Strategy:

    def __init__(self, market: Market, game: BaseballGame, update: asyncio.Event, state: TradingState, http_client: KalshiHttpClient):
        self.market = market
        self.game = game
        self.update = update
        self.state = state
        self.http_client = http_client

        self.unit_size = 1

        self.log = pd.DataFrame(columns=["Time", "Predicted", "Bid", "Ask"])

    async def run(self):
        while True:
            await self.update.wait()
            self.update.clear()

            try:
                orderbook = self.state.orderbooks
                orderbook = orderbook[self.market.ticker]

                now = datetime.now().timestamp()
                start_ts = datetime.strptime(self.game.start_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                start_ts = int(start_ts.timestamp())

                if now < start_ts:
                    logging.info(f"Awaiting game start for {self.game.away_team_abv} @ {self.game.home_team_abv}")
                    await asyncio.sleep(60)

                else:
                    self.game.update_status()

                    if self.game.status == "In Progress":
                        if self.game.pregame_winProbability == -1:
                            self.game.update_pregame_win_probability(self.market, self.http_client)
                            if self.game.pregame_winProbability == -1:
                                logging.error(f"Unable to get pre-game win probability for {self.game.away_team_abv} @ {self.game.home_team_abv}")

                        mid_price_projection = self.get_mid_price_projection()
                        
                        logging.info(f"\nProjected win probability {self.game.away_team_abv}:{round(100-mid_price_projection, 2)} @ {self.game.home_team_abv}:{round(mid_price_projection, 2)}")
                        if orderbook.asks and orderbook.bids:
                            logging.info(f"Traded win probability {self.game.away_team_abv}:{100-min(orderbook.asks)} @ {self.game.home_team_abv}:{min(orderbook.asks)}")
                            self.log = pd.concat([self.log, pd.DataFrame({"Time": pd.Timestamp.now(), "Predicted": mid_price_projection, "Bid": [max(orderbook.bids)], "Ask": [min(orderbook.asks)]})], ignore_index=True)
                        elif orderbook.asks:
                            logging.info(f"Traded win probability {self.game.away_team_abv}:{100-min(orderbook.asks)} @ {self.game.home_team_abv}:{min(orderbook.asks)}")
                            self.log = pd.concat([self.log, pd.DataFrame({"Time": pd.Timestamp.now(), "Predicted": mid_price_projection, "Bid": [0], "Ask": [min(orderbook.asks)]})], ignore_index=True)
                        elif orderbook.bids: 
                            logging.info(f"Traded win probability {self.game.away_team_abv}:{100-max(orderbook.bids)} @ {self.game.home_team_abv}:{max(orderbook.bids)}")
                            self.log = pd.concat([self.log, pd.DataFrame({"Time": pd.Timestamp.now(), "Predicted": mid_price_projection, "Bid": [max(orderbook.bids)], "Ask": [100]})], ignore_index=True)

                        
                    
                    elif self.game.status == "Final":
                        logging.info(f"Game complete for {self.game.away_team_abv} @ {self.game.home_team_abv}")

            except Exception as e:
                 logging.error(e)

    def get_mid_price_projection(self):
        alpha_t = 4
        alpha_prob = 8
        t = self.game.pctPlayed
        P_pre = self.game.pregame_winProbability
        P_live = self.game.winProbability

        if P_live == -1:
            raise ValueError("Live win probability is not available.")

        # Standard exponential decay weight
        base_weight = math.exp(-alpha_t * t)
        # Confidence factor: 0 at 0.5, 1 at 0 or 1 (scales up live weight as it moves away from 0.5)
        confidence = 1 - math.exp(-alpha_prob * abs(P_live - 50)/100)
        # Adjusted live weight
        live_weight = (1 - base_weight) * confidence
        # Adjusted pre-game weight
        pre_weight = 1 - live_weight

        # Normalize weights to sum to 1 (optional, but recommended)
        total = pre_weight + live_weight
        pre_weight /= total
        live_weight /= total

        return pre_weight * P_pre + live_weight * P_live
    