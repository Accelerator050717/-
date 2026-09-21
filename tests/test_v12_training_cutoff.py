"""Fictional maturity boundary cohorts; no fitting or production data."""
import importlib
import unittest
import numpy as np
import pandas as pd

training = importlib.import_module('53_train_annual_cutoff')


def fixture():
    return pd.DataFrame([
        ('2018-06-01','2018-09-01',.1,1.),
        ('2018-12-01','2019-03-01',.2,2.),  # Purged from old train AND old validation.
        ('2019-06-01','2019-09-01',.3,3.),
        ('2019-09-01','2020-01-01',.4,4.),  # Strict cutoff: not available.
        ('2019-10-01','2020-02-01',.5,5.),
        ('2019-05-01','2019-08-01',.2,np.nan),
        ('2020-06-01','2020-09-01',.1,6.),
        ('2020-12-01',None,np.nan,7.),
    ],columns=['Date','exit_60','rank_60','x']).assign(
        Date=lambda x:pd.to_datetime(x.Date),exit_60=lambda x:pd.to_datetime(x.exit_60),symbol='TEST')


class AnnualCutoffTests(unittest.TestCase):
    def test_full_panel_recovers_previously_purged_boundary(self):
        rows = training.training_rows(fixture(),2020,['x'])
        self.assertEqual(set(rows.Date.dt.strftime('%Y-%m-%d')),{'2018-06-01','2018-12-01','2019-06-01'})
        self.assertEqual(len(training.training_rows(fixture(),2019,['x'])),1)

    def test_scoring_keeps_unmatured_tail_and_key_order(self):
        panel=fixture(); keys=panel.loc[panel.Date.dt.year.eq(2020),['Date','symbol']].iloc[::-1]
        rows=training.scoring_rows(panel,2020,keys,['x'])
        self.assertEqual(rows.Date.tolist(),keys.Date.tolist())
        self.assertEqual(int(rows.rank_60.isna().sum()),1)

    def test_missing_predictor_is_error_not_dropped_sample(self):
        panel=fixture(); panel.loc[panel.Date.eq('2020-12-01'),'x']=np.nan
        with self.assertRaises(ValueError):
            training.scoring_rows(panel,2020,panel[['Date','symbol']],['x'])


if __name__=='__main__':
    unittest.main()
