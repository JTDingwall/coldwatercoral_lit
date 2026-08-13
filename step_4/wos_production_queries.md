# Web of Science production queries

Frozen Step 3 production queries for the cold-water coral and sponge sedimentation source-discovery project.

Run all searches in Web of Science Core Collection using `TS=` Topic Search, with no date cutoff. Export all results for each query as RIS and retain the query ID in the filename and search log.

## `WOS_SED_SUSPENDED_01`

```text
TS=(
  (
    coral* OR octocoral* OR gorgonian* OR "sea pen*" OR pennatula*
    OR scleractinian* OR antipatharian* OR "black coral*"
    OR Porifera OR poriferan* OR demosponge* OR hexactinellid*
    OR "glass sponge*" OR "deep-sea sponge*" OR "deep sea sponge*"
    OR "cold-water sponge*" OR "cold water sponge*"
  )
  AND
  (
    "suspended sediment*" OR "suspended solid*" OR
    "suspended particle*" OR turbidity OR resuspension
    OR "particle concentration*" OR "sediment plume*"
  )
)
```

Pilot count: 1,538.

## `WOS_SED_DEPOSITION_01`

```text
TS=(
  (
    coral* OR octocoral* OR gorgonian* OR "sea pen*" OR pennatula*
    OR scleractinian* OR antipatharian* OR "black coral*"
    OR Porifera OR poriferan* OR demosponge* OR hexactinellid*
    OR "glass sponge*" OR "deep-sea sponge*" OR "deep sea sponge*"
    OR "cold-water sponge*" OR "cold water sponge*"
  )
  AND
  (
    "sediment deposition" OR "sediment accumulation"
    OR "sediment load*" OR burial OR smother*
    OR "sediment cover*" OR "sediment thickness"
    OR "deposition rate*"
  )
)
```

Pilot count: 1,167.

## `WOS_SED_DRILLING_01`

```text
TS=(
  (
    coral* OR octocoral* OR gorgonian* OR "sea pen*" OR pennatula*
    OR scleractinian* OR antipatharian* OR "black coral*"
    OR Porifera OR poriferan* OR demosponge* OR hexactinellid*
    OR "glass sponge*" OR "deep-sea sponge*" OR "deep sea sponge*"
    OR "cold-water sponge*" OR "cold water sponge*"
  )
  AND
  (
    "drill cutting*" OR "drilling mud*" OR "drilling fluid*"
    OR "drilling discharge*" OR "drilling waste*"
    OR "cuttings pile*" OR
    (
      "offshore drilling"
      AND
      (sediment* OR bentonite OR barite OR particulate* OR discharge*)
    )
  )
)
```

Pilot count: 75.

## `WOS_SED_DREDGING_01`

```text
TS=(
  (
    coral* OR octocoral* OR gorgonian* OR "sea pen*" OR pennatula*
    OR scleractinian* OR antipatharian* OR "black coral*"
    OR Porifera OR poriferan* OR demosponge* OR hexactinellid*
    OR "glass sponge*" OR "deep-sea sponge*" OR "deep sea sponge*"
    OR "cold-water sponge*" OR "cold water sponge*"
  )
  AND
  (
    dredg* OR "dredge plume*" OR "dredging plume*"
    OR resuspension OR "resuspended sediment*"
    OR "sediment plume*" OR "spoil disposal"
    OR "dredged material"
  )
)
```

Pilot count: 671.

## `WOS_SED_TAILINGS_01`

```text
TS=(
  (
    coral* OR octocoral* OR gorgonian* OR "sea pen*" OR pennatula*
    OR scleractinian* OR antipatharian* OR "black coral*"
    OR Porifera OR poriferan* OR demosponge* OR hexactinellid*
    OR "glass sponge*" OR "deep-sea sponge*" OR "deep sea sponge*"
    OR "cold-water sponge*" OR "cold water sponge*"
  )
  AND
  (
    "mine tailing*" OR "mining tailing*" OR "submarine tailing*"
    OR "deep-sea mining" OR "deep sea mining"
    OR "seafloor massive sulphide*" OR "seafloor massive sulfide*"
    OR "mining plume*" OR "marine disposal"
    OR "particulate waste*"
  )
)
```

Pilot count: 80.

## `WOS_MECH_FEEDING_MUCUS_CORAL_01`

```text
TS=(
  (
    coral* OR octocoral* OR gorgonian* OR "sea pen*" OR pennatula*
    OR scleractinian* OR antipatharian* OR "black coral*"
  )
  AND
  (
    sediment* OR turbidity OR "suspended solid*" OR "suspended particle*"
    OR burial OR smother* OR bentonite OR barite OR "drill cutting*"
  )
  AND
  (
    mucus OR mucous OR mucociliary
    OR "sediment rejection" OR "sediment clearance"
    OR "particle rejection"
    OR feeding OR "food capture" OR "prey capture"
    OR "polyp activity" OR "tentacle activity"
  )
)
```

Pilot count: 713.

## `WOS_MECH_FEEDING_PUMPING_SPONGE_01`

```text
TS=(
  (
    Porifera OR poriferan* OR demosponge* OR hexactinellid*
    OR "glass sponge*" OR "deep-sea sponge*" OR "deep sea sponge*"
    OR "cold-water sponge*" OR "cold water sponge*"
  )
  AND
  (
    sediment* OR turbidity OR "suspended solid*" OR "suspended particle*"
    OR bentonite OR barite OR "drill cutting*"
  )
  AND
  (
    pumping OR filtration OR "feeding current*"
    OR "food capture" OR clogging
    OR "particle clearance" OR "clearance rate*"
  )
)
```

Pilot count: 33.

## `WOS_RESP_THRESHOLD_RECOVERY_01`

```text
TS=(
  (
    coral* OR octocoral* OR gorgonian* OR "sea pen*" OR pennatula*
    OR scleractinian* OR antipatharian* OR "black coral*"
    OR Porifera OR poriferan* OR demosponge* OR hexactinellid*
    OR "glass sponge*" OR "deep-sea sponge*" OR "deep sea sponge*"
    OR "cold-water sponge*" OR "cold water sponge*"
  )
  AND
  (
    (
      "suspended sediment*" OR "sediment deposition" OR
      "sediment accumulation" OR "sediment load*" OR turbidity
      OR burial OR smother* OR "drill cutting*" OR
      "drilling mud*" OR "drilling discharge*" OR
      "resuspended sediment*" OR "sediment plume*"
    )
    NEAR/10
    (
      threshold* OR tolerance OR sensitiv*
      OR "dose-response" OR "dose response"
      OR "exposure-response" OR "exposure response"
      OR recovery OR mortality OR survival
      OR "chronic exposure" OR "acute exposure"
    )
  )
)
```

Pilot count: 162.

## Export naming convention

Save each complete RIS export in `step_4/wos/` using the query ID, for example:

```text
WOS_SED_SUSPENDED_01.ris
WOS_SED_DEPOSITION_01.ris
WOS_SED_DRILLING_01.ris
WOS_SED_DREDGING_01.ris
WOS_SED_TAILINGS_01.ris
WOS_MECH_FEEDING_MUCUS_CORAL_01.ris
WOS_MECH_FEEDING_PUMPING_SPONGE_01.ris
WOS_RESP_THRESHOLD_RECOVERY_01.ris
```

The earlier broad `SED_GENERAL` pilot (~11,000 records) is retired and is not part of the production search.
