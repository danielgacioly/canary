# Indicator guide (source for "How to measure and why")

`indicadores.json` holds, for 25 health indicators, how to measure each one in flight, what spaceflight does to it, and
what to do at each colour (green, amber, red). It was written in Portuguese for the team's research, before Canary
existed in its current form, and is the source of the texts for step 7, item C1.

**Use only its texts:** `como_medir`, `efeito_no_espaco`, `acoes`, `frequencia_sugerida`. Rewrite them in English in
the app's tone. Its numbers (`faixas`, `referencia_populacao`) are not Canary's: every limit the app uses comes from
`backend/canary/domain/reference.py` (population ranges, checked against their sources) and
`backend/canary/domain/standards.py` (NASA-STD-3001). Where the guide and those files disagree, the files win.

`id_map.json` maps the guide's ids to Canary's. `kind` says where the id lives: `indicator` (catalog.INDICATORS),
`lab` (a blood or urine row of `data/recipes.json`, read by the risks), `risk` (a risk of `risk.py`) or `none`
(nothing in Canary yet; skip it or add the indicator first). A test checks that every mapped id exists.

| Guide | Canary | Kind |
| --- | --- | --- |
| `pa_sistolica` | `sbp` | indicator |
| `pa_diastolica` | — | none |
| `fc_repouso` | `hr` | indicator |
| `temperatura` | `temp` | indicator |
| `spo2` | `spo2` | indicator |
| `glicemia` | `gluc` | indicator |
| `potassio` | `potassium` | lab |
| `ureia` | — | none |
| `hemoglobina` | `hgb` | lab |
| `leucocitos` | `wbc` | lab |
| `calcio` | `calcium` | lab |
| `exercicio` | `exer` | indicator |
| `sono` | `sleep` | indicator |
| `humor` | `mood` | indicator |
| `radiacao_carreira` | `radiation` | risk |
| `radiacao_evento_solar` | `radiation` | risk |
| `vitamina_d` | `vitamin_d` | lab (simulated only) |
| `testosterona` | — | none |
| `estradiol` | — | none |
| `vo2max` | `vo2` | indicator |
| `forca_muscular` | `grip` | indicator |
| `densidade_ossea_quadril_coluna` | `bone` | indicator |
| `densidade_ossea_colo_femur` | — | none |
| `ingestao_calorica` | — | none |
| `radiacao_30_dias` | — | none |

Canary indicators the guide does not cover (no text yet): `react`, `stress`, `social`, `dsst`, `span`, `kss`, `tlx`,
`water`, `dbp`. Write those from the test descriptions in `domain/selftests.py`, marked as the app's own text.
