import asyncio
from Infrastructure.Clients.http_client import KalshiHttpClient
from Infrastructure.state import TradingState
from Infrastructure.market import Market
from Baseball.BaseballGame import BaseballGame
import logging
from datetime import datetime, timezone
import pandas as pd


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
                    if self.game.status == "In Progress":
                        if self.game.pregame_winProbability == -1:
                            self.game.update_pregame_win_probability(self.market, self.http_client)

                        self.game.update_status()

                        mid_price_projection = self.get_mid_price_projection()
                        logging.info(f"Projected win probability {self.game.away_team_abv}:{round(100-mid_price_projection, 2)} @ {self.game.home_team_abv}:{round(mid_price_projection, 2)}")
                        logging.info(f"Traded win probability {self.game.away_team_abv}:{100-min(orderbook.asks)} @ {self.game.home_team_abv}:{min(orderbook.asks)}")
                        self.log = pd.concat([self.log, pd.DataFrame({"Time": pd.Timestamp.now(), "Predicted": mid_price_projection, "Bid": [max(orderbook.bids)], "Ask": [min(orderbook.asks)]})], ignore_index=True)
                    
                    elif self.game.status == "Final":
                        logging.info(f"Game complete for {self.game.away_team_abv} @ {self.game.home_team_abv}")

            except Exception as e:
                logging.error(e)

    def get_mid_price_projection(self):
        return (self.game.pctPlayed * self.game.winProbability) + ((1 - self.game.pctPlayed) * self.game.pregame_winProbability)


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