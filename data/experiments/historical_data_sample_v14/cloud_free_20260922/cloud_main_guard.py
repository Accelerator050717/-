# v14 data inspection project: use the Research notebook only.
from AlgorithmImports import QCAlgorithm

class V14ReadOnlyResearch(QCAlgorithm):
    def initialize(self):
        raise RuntimeError("Research-only project: Backtest and Live are disabled.")
