"""Local fictional v13 integration tests and immutable-source evidence snapshot."""
from datetime import datetime,timezone
import io
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from h60_research_inputs import sha,save


def main():
    out=ROOT/'data/experiments/continuous_fund_risk_v13'
    started=datetime.now(timezone.utc).isoformat();timer=time.perf_counter()
    log=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_v13*.py')
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (out/'TESTS.log').write_text(log.getvalue(),encoding='utf-8')
    files=list((ROOT/'tests').glob('test_v13*.py'))
    files += [ROOT/name for name in ('strategy_fund_journal.py','h60_global_control.py','h60_global_research.py',
        'h60_fund_risk_bridge.py','h60_fund_control_cycle.py','56_check_fund_continuity.py',
        '57_check_fund_recording.py','58_evaluate_continuous_risk.py','59_summarize_continuous_risk.py')]
    save(out/'TESTS.json',dict(started_at_utc=started,completed_at_utc=datetime.now(timezone.utc).isoformat(),
        runtime_seconds=time.perf_counter()-timer,tests_run=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),skipped=len(result.skipped),passed=result.wasSuccessful(),
        evidence='FICTITIOUS local accounting/controller/execution and synthetic data only',
        command='.venv\\Scripts\\python.exe -B tools/check_v13_tests.py',new_fits=0,
        real_or_paper_orders=0,prices_2026_accessed=False,
        source_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in files},log_sha256=sha(out/'TESTS.log'),
        additional_unchanged_old_regressions='OLD_REGRESSION_TESTS.json'))
    print(f'v13 integration: {result.testsRun} tests, failures={len(result.failures)}, errors={len(result.errors)}; '+
          f'{time.perf_counter()-timer:.3f}s; no broker network or market-data request.')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    sys.exit(main())
