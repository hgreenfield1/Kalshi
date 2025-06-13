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
                            self.log = pd.concat([self.log, pd.DataFrame({"Time": pd.Timestamp.now(), "Predicted": mid_price_projection, "Bid": [], "Ask": [min(orderbook.asks)]})], ignore_index=True)
                        elif orderbook.bids: 
                            logging.info(f"Traded win probability {self.game.away_team_abv}:{100-max(orderbook.bids)} @ {self.game.home_team_abv}:{max(orderbook.bids)}")
                            self.log = pd.concat([self.log, pd.DataFrame({"Time": pd.Timestamp.now(), "Predicted": mid_price_projection, "Bid": [max(orderbook.bids)], "Ask": []})], ignore_index=True)

                        
                    
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


                # for ticker_dict in self.tickers:
                #     # If game hasn't started - return
                #     # If game has started:
                #     #   Call game.update -> updates the time elapsed and win probability
                #     #   if game.pre_game_odds is None -> get the tick from 5 minutes before game time -> set as an attr
                #     #   try to get statsapi win probability
                #     #   predicted_win_prob = function(pre_game_odds, statsapi_current_odds)
                #
                #
                #      try:
                #         cost = 0
                #         available = []
                #         for ticker, mult in ticker_dict.items():
                #             ob = relevant_orderbooks[ticker]
                #
                #             if mult == 1:  # Buy at ASK
                #                 if not ob.asks:
                #                     raise Exception("Orderbook must have ask liquidity for a buy.")
                #                 else:
                #                     best_ask = min(ob.asks)
                #                     cost += best_ask
                #                     available += [ob.asks[best_ask]]
                #             elif mult == -1:  # Sell at BID
                #                 if not ob.bids:
                #                     raise Exception("Orderbook must have bid liquidity for a buy.")
                #                 else:
                #                     best_bid = max(ob.bids)
                #                     cost += 100 - best_bid
                #                     available += [ob.bids[best_bid]]
                #
                #         logging.warning(f"COST: {cost}")
                #         #self.costs[ticker].append(cost)
                #         if cost < 102:
                #             logging.warning(datetime.now().strftime("%H:%M:%S") + ": PROFITABLE TRADE: " + str(ticker_dict) + f". Total Cost: {cost} Available Contracts: {min(available)}")
                #             with open("log.txt", "a") as log_file:
                #                 log_file.write(f"[{datetime.now()}] PROFITABLE TRADE: " + str(ticker_dict) + f". Total Cost: {cost} Available Contracts: {min(available)}\n")
                #                 log_file.write("TICKERS: " + ", ".join(map(str, ticker_dict.keys())) + "\n")
                #                 log_file.write("MULTIPLIERS: " + ", ".join(map(str, ticker_dict.values())) + "\n")
                #                 for ticker in ticker_dict.keys():
                #                     ob = relevant_orderbooks[ticker]
                #                     log_file.write(f"{ticker} ORDERBOOK: BIDS: " + str(ob.bids) + " ASKS: " + str(ob.asks) + "\n")
                #                 log_file.write("\n")
                #      except Exception as e:
                #         continue

                #logging.info(f"Placing order from strategy: {bid}/{bid_vol}, {ask}/{ask_vol}")
                #await self.order_manager.place_order(bid, bid_vol, ask, ask_vol)