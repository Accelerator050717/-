"""Fictional unit-NAV paths; no historical threshold search or broker orders."""
import unittest
from h60_global_control import GlobalRisk


class GlobalControllerTests(unittest.TestCase):
    def resume(self,state,day,nav,**overrides):
        kwargs=dict(trend=True,scheduled=True,confirmed_flat=True,no_pending_orders=True,episode_ready=True)
        kwargs.update(overrides)
        return state.try_resume(day,nav,1.,**kwargs)

    def test_two_losses_keep_old_loss_and_recovery_does_not_immediately_repause(self):
        s=GlobalRisk();s.observe(1,.79,1.)
        self.assertEqual(s.mode,'HALTED')
        self.assertFalse(self.resume(s,21,.79))
        self.assertTrue(self.resume(s,22,.79))
        self.assertEqual(s.observe(22,.789,1.),[])
        self.assertEqual(s.mode,'RECOVERY')
        # A further 5% recovery loss reaches .75, leaving too little budget.
        s.observe(24,.749,1.)
        self.assertEqual(s.mode,'REVIEW_LOCKED')
        self.assertFalse(self.resume(s,100,.749))
        self.assertEqual(s.cap(.749,1.),0.)

    def test_recovery_needs_confirmed_exit_and_old_episode_ready(self):
        for flag in ('confirmed_flat','no_pending_orders','episode_ready','trend','scheduled'):
            s=GlobalRisk();s.observe(0,.8-1e-9,1.)
            self.assertFalse(self.resume(s,30,.8,**{flag:False}))

    def test_new_loss_budget_repauses_without_resetting_high_water(self):
        s=GlobalRisk();s.observe(0,.799,1.)
        self.assertTrue(self.resume(s,21,.799))
        events=s.observe(22,.758,1.)
        self.assertEqual(events[0]['event'],'global_pause')
        self.assertEqual(s.mode,'HALTED')
        self.assertTrue(self.resume(s,43,.758))
        self.assertLessEqual(s.cap(.758,1.),.25)
        self.assertGreater(s.recovery_floor,.70)

    def test_lock_never_auto_unlocks_and_budget_breach_is_recorded_once(self):
        s=GlobalRisk();s.observe(0,.74,1.)
        self.assertEqual(s.mode,'REVIEW_LOCKED')
        self.assertEqual(s.observe(1,.65,1.)[0]['event'],'global_budget_breach')
        self.assertEqual(s.observe(2,.64,1.),[])
        self.assertFalse(self.resume(s,100,.99))
        self.assertTrue(s.budget_breached)

    def test_reduction_hysteresis_and_budget_cap(self):
        s=GlobalRisk();s.observe(1,.899,1.)
        self.assertEqual(s.cap(.899,1.),.4)
        s.observe(2,.93,1.);self.assertEqual(s.mode,'REDUCED')
        s.observe(3,.951,1.);self.assertEqual(s.mode,'NORMAL')
        s=GlobalRisk(mode='RECOVERY',resume_unit_nav=.754,recovery_floor=.7163)
        self.assertAlmostEqual(s.cap(.754,1.),(.754-.70)/.754/.30)


if __name__=='__main__':
    unittest.main()
