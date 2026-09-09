"""建立并检查 5/20/60 日标签，保留相同的开发评分记录。"""
import json
import research_horizons as horizons

if __name__ == "__main__":
    print(json.dumps(horizons.prepare_targets(), indent=2))
    panel = horizons.load_panel()
    print(f"Common panel: {len(panel):,} rows; {panel.Date.nunique():,} dates")
    for h in horizons.HORIZONS:
        train, valid, dev = horizons.split_fold(panel, 2025, h)
        print(f"H{h}: train={len(train)}, valid={len(valid)}, dev={len(dev)}, "
              f"train_last_exit={train[f'exit_{h}'].max().date()}, "
              f"validation_last_exit={valid[f'exit_{h}'].max().date()}")
