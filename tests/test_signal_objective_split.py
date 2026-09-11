"""Synthetic cohorts: a stopped sample is not mature until its common H60 endpoint."""
import importlib
import unittest

import pandas as pd

from panel_config import SYMBOLS

training = importlib.import_module('50_train_signal_objectives')


def fixture():
    rows=[]
    # Y=2020: 2018 training, 2019 validation, 2020 development.
    for observation,terminal in [('2018-06-01','2018-09-01'),
                                 ('2018-12-01','2019-03-01'),
                                 ('2019-06-01','2019-09-01'),
                                 ('2019-12-01','2020-03-01'),
                                 ('2020-06-01','2020-09-01'),
                                 ('2020-12-01',None)]:
        for symbol in SYMBOLS:
            rows.append(dict(Date=pd.Timestamp(observation),symbol=symbol,
                             exit_60=pd.Timestamp(terminal) if terminal else pd.NaT,
                             stopped_exit_date=pd.Timestamp(observation)+pd.Timedelta(days=2),
                             **{target:.1 if terminal else float('nan')
                                for target in training.CONFIGS.values()}))
    return pd.DataFrame(rows)


class SignalSplitTests(unittest.TestCase):
    def test_early_stop_does_not_bypass_terminal_purge(self):
        train,valid,_=training.split_fold(fixture(),2020)
        self.assertEqual(set(train.Date),{pd.Timestamp('2018-06-01')})
        self.assertEqual(set(valid.Date),{pd.Timestamp('2019-06-01')})

    def test_prediction_cohort_keeps_unmatured_tail(self):
        _,_,develop=training.split_fold(fixture(),2020)
        self.assertEqual(len(develop),2*len(SYMBOLS))
        self.assertEqual(int(develop.exit_60.isna().sum()),len(SYMBOLS))

    def test_incomplete_mature_cross_section_is_rejected(self):
        panel=fixture().drop(index=0)
        with self.assertRaises(ValueError):
            training.split_fold(panel,2020)


if __name__=='__main__':
    unittest.main()
