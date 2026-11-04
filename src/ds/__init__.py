"""Data-science layer: the modelling, evaluation and MLOps that sit on top of
the consulting pipeline.

    data         one lean loader for the out-of-time panels every module shares
    shrinkage    empirical-Bayes brand share (fixes tiny-denominator noise)
    evaluation   baseline ladder, ranking metrics, gain curves, pre-declared metric
    conformal    calibrated prediction intervals, per prescriber, with coverage
    errors       error analysis and fairness by segment
    causal       double machine learning + omitted-variable sensitivity
    uplift       doubly-robust uplift model, Qini evaluation
    explain      exact per-prescriber explanations (tree SHAP)
    ablation     what each modelling choice is worth
    drift        population stability between years
    contracts    data contracts on every mart the models read
    network      group-practice peer effects
    tracking     MLflow experiment tracking

Every module is runnable on its own (``python -m src.ds.<name>``) and records
its headline in data/manifest.json under a ``ds_`` key.
"""
# LOKY_MAX_CPU_COUNT is set in src/__init__.py, which every import passes through.
