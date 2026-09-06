# AIRLOCK-SWE-GATE-001 result

Verdict: **INCONCLUSIVE_AIRLOCK_INIT_FAILURE**

Airlock base: `11e99ee762b4e4a8b593c96cf3a5e175a5edba88`
SWE-Gate: `5f303b30dd53af3499d05558cfd82eda641be22b`
Frozen sample: 12 distinct repos / 12 instances / 24 patch evaluations.

## Pair classes

| Class | Count |
|---|---:|
| DISCRIMINATED | 0 |
| UNDERCONSTRAINED | 1 |
| OVERCONSERVATIVE_OR_INSUFFICIENT | 1 |
| INVERTED | 0 |
| INCONCLUSIVE | 0 |

## Instances

| Repo | Instance | Noncompliant | Gold | Pair |
|---|---|---|---|---|
| falcon | `d2a0c5d0946b4258_falcon_parse_host_unicode_ip` | ? / ? | ? / ? | ? |
| msgpack-python | `msgpack_mingw_sysdep_builtin_order` | NEEDS_EVIDENCE / no_changed_source_module_detected | NEEDS_EVIDENCE / no_changed_source_module_detected | OVERCONSERVATIVE_OR_INSUFFICIENT |
| rich | `6651cfbd432d5c7c_rich_json_path_help` | ? / ? | ? / ? | ? |
| textual | `98d4abd00745540f_03_textual` | ? / ? | ? / ? | ? |
| flake8 | `98d4abd00745540f_05_flake8` | SURVIVED / ALL_CONFIGURED_CHECKS_PASSED | SURVIVED / ALL_CONFIGURED_CHECKS_PASSED | UNDERCONSTRAINED |
| datasets | `datasets_feature_cast_large_list_nulls` | ? / ? | ? / ? | ? |
| typer | `typer__2882fb7be5035f1a__deprecated_help` | ? / ? | ? / ? | ? |
| panel | `panel_param_reprs_array_default_f72291588bb90a6d` | ? / ? | ? / ? | ? |
| cookiecutter | `10017e23de1a99dd_cookiecutter_repo_type` | ? / ? | ? / ? | ? |
| dynaconf | `6bbf427414990a90_dynaconf_int_cast_validation` | ? / ? | ? / ? | ? |
| arq | `10017e23de1a99dd_arq_redis_dsn_scheme` | ? / ? | ? / ? | ? |
| numba | `numba_mingw_checked_size_builtin_order` | ? / ? | ? / ? | ? |

## Interpretation

- `UNDERCONSTRAINED` is the preregistered falsifier: current Airlock admits both a functional-pass/review-fail patch and its functional-pass/review-pass gold control.
- `DISCRIMINATED` means current Airlock withholds the noncompliant patch while admitting the gold control without benchmark-specific configuration.
- Withholding both is conservative/inconclusive, not a success.

No product code, Starter Rules, thresholds, protected paths, or target checks were changed for this benchmark.
