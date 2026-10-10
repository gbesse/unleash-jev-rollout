# unleash-jev-rollout — contrôle d’adoption · adoption check · comprobación de adopción

## Français

Point de départ local, après la préparation indiquée dans le README :

```sh
python3 rollout.py --demo
```

Deux tentatives avec le même identifiant d’événement ne doivent pas compter deux régressions. Examinez le compteur par flag et environnement avant de brancher un seuil Unleash.

## English

Local starting point, after the setup described in the README:

```sh
python3 rollout.py --demo
```

Two retries with the same event ID must not count two regressions. Inspect the per-flag and per-environment counter before connecting an Unleash threshold.

## Español

Punto de partida local, después de la preparación descrita en el README:

```sh
python3 rollout.py --demo
```

Dos reintentos con el mismo ID de evento no deben contar dos regresiones. Revise el contador por flag y entorno antes de conectar un umbral de Unleash.
## Variante synthétique · Synthetic variation · Variante sintética

```text
event_id="synthetic-1"; retry_count=2; metric_increment=1
```

FR : adaptez une copie de la fixture locale à cette situation, puis vérifiez le comportement décrit ci-dessus. Les valeurs sont illustratives, pas des résultats Jev mesurés.

EN: adapt a copy of the local fixture to this situation, then check the behavior described above. Values are illustrative, not measured Jev output.

ES: adapte una copia de la fixture local a esta situación y compruebe el comportamiento descrito arriba. Los valores son ilustrativos, no resultados Jev medidos.

## Second cas · Second case · Segundo caso

```text
policy_version=1 -> 2; metric_counter=reset
```

**FR :** Une nouvelle version de politique réinitialise la série exportée. Configurez la collecte Prometheus pour interpréter le reset avant d’en faire un garde de déploiement.

**EN:** A new policy version resets the exported series. Configure Prometheus collection to interpret the reset before using it as a rollout safeguard.

**ES:** Una nueva versión de política reinicia la serie exportada. Configure la recopilación de Prometheus para interpretar el reinicio antes de usarlo como protección del despliegue.
