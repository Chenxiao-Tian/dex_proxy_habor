from .strategy import Strategy
from .naive_mm import NaiveMM


class StrategyFactory:

    @staticmethod
    def create(config) -> Strategy:
        config = config["strategy"]
        strategy_type = config["type"]
        if strategy_type == "naive_mm":
            return NaiveMM(config)

        raise NotImplementedError(f"Strategy {strategy_type} is not implemented.")
