"""Only fictional bars: unchanged recording, restart and cumulative loss facts."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import numpy as np

import profit_priority_strategy as original
import h60_global_research as new
from test_robust_strategy import fixture
from v12_drawdown_check import fictional_inputs


class ResearchContinuityTests(unittest.TestCase):
    def test_record_only_matches_frozen_original_and_restarts(self):
        dates,bars,spy,scores,groups=fixture()
        args=(scores,bars,spy,groups,dates[[250,255,260,265]],dates[270])
        kwargs=dict(policy=replace(original.Policy(),soft_enabled=False))
        old=original.simulate(*args,**kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fund.sqlite'
            stopped=new.simulate(*args,**kwargs,journal_path=path,scope_id='same-capital',create_journal=True,stop_after_session=9)
            self.assertTrue(stopped['partial'])
            resumed=new.simulate(*args,**kwargs,journal_path=path,scope_id='same-capital',create_journal=False)
            for key in ('daily','trades','positions','targets','events'):
                pd.testing.assert_frame_equal(resumed[key][old[key].columns],old[key],check_exact=True)
            self.assertFalse(resumed['fund_state']['blocked'])
            self.assertEqual(resumed['fund_state']['valuation_cursor'],len(old['daily']))

    def test_global_controller_checkpoint_and_trades_continue_after_restart(self):
        dates,bars,spy,scores,groups=fictional_inputs()
        args=(scores,bars,spy,groups,dates[250:326:5],dates[330])
        kwargs=dict(policy=replace(original.Policy(),soft_enabled=False),global_control=True)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            full=new.simulate(*args,**kwargs,journal_path=root/'full.sqlite',scope_id='full',create_journal=True)
            new.simulate(*args,**kwargs,journal_path=root/'resume.sqlite',scope_id='resume',create_journal=True,stop_after_session=35)
            resumed=new.simulate(*args,**kwargs,journal_path=root/'resume.sqlite',scope_id='resume')
            for key in ('daily','trades','positions','targets','events'):
                pd.testing.assert_frame_equal(resumed[key],full[key],check_exact=False,rtol=1e-12,atol=1e-12)
            self.assertEqual(resumed['fund_state']['risk_state'],full['fund_state']['risk_state'])
            self.assertGreater(resumed['fund_state']['high_water_nav'],resumed['fund_state']['unit_nav'])
            reductions=resumed['trades'].loc[resumed['trades'].reason.isin(['global_flat','global_risk_reduce'])]
            self.assertTrue(reductions.signed_units.le(0).all())


if __name__=='__main__':
    unittest.main()
