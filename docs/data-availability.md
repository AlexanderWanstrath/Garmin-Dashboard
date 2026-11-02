# Data availability (Stage 0)

Result of running `scripts/stage0_check.py` against the real Garmin Personal API on 2026-11-02 with a 30-day look-back. This document lists which data exists and where it comes from. It contains no measured values.

## Decision

**The Garmin Personal API is the only data source.** It provides two kinds of data:

- **JSON endpoints:** run summaries, health and recovery data, heart rate zones.
- **FIT file per activity** (downloaded through the API): per-second samples, laps (km splits) and VO2max.

Manually exported FIT files and Strava are not needed for now. The FIT adapter is still built, but it reads the files downloaded through the API rather than manual exports.

## Activities

| Data | Endpoint | Status | Notes |
|---|---|---|---|
| Activity list | `/activitylist-service/activities/search/activities` | available | Includes summary fields for each run, see below |
| Activity details | `/activity-service/activity/{id}` | available | `summaryDTO` adds min HR, temperature, RPE and feel (`directWorkoutRpe`, `directWorkoutFeel`) |
| Activity workouts | `/activity-service/activity/{id}/workouts` | available | Planned workout linked to the run |
| FIT file | `/download-service/files/activity/{id}` | available | ZIP with one `.fit` file, see below |
| Splits | `/activity-service/activity/{id}/splits` | HTTP 404 | Covered by FIT laps |
| Split summaries | `/activity-service/activity/{id}/split_summaries` | HTTP 404 | Covered by `splitSummaries` in the activity list and FIT `split_summary` |
| HR time in zones | `/activity-service/activity/{id}/hrTimeInZones` | HTTP 404 | Covered by `hrTimeInZone_1..5` in the activity list and FIT `time_in_zone` |

**Run summary fields in the activity list** (present in every run checked):
`activityId`, `startTimeLocal`, `activityType`, `distance`, `duration`, `movingDuration`, `averageSpeed`, `averageHR`, `maxHR`, `elevationGain`, `averageRunningCadenceInStepsPerMinute`, `hrTimeInZone_1..5`, `aerobicTrainingEffect`, `anaerobicTrainingEffect`, `trainingEffectLabel`.

Also available: power (`avgPower`, `normPower`, `powerTimeInZone_1..5`), running dynamics (`avgGroundContactTime`, `avgStrideLength`, `avgVerticalOscillation`, `avgVerticalRatio`), `avgGradeAdjustedSpeed`, fastest splits (`fastestSplit_1000`, `_1609`, `_5000`, `_10000`), `lapCount`, intensity minutes.

**Not in the JSON:** `vO2MaxValue` is empty in every run.

## FIT file

One FIT file per activity, about 120 KB for a one-hour run. Parsed with `fitdecode`.

| Message | Content | Used for |
|---|---|---|
| `record` | One sample per second: time, heart rate, speed, distance, cadence, altitude, power, GPS | Decoupling, efficiency factor, pace and HR curves |
| `lap` | One lap per km (auto lap) | km splits |
| `session` | Whole-activity summary | Cross-check with JSON |
| `time_in_zone` | Time in HR and power zones | Intensity distribution |
| `event` | Start, stop, pauses | Excluding pauses |
| `unknown_140` | Undocumented Garmin message; field 7 holds VO2max (scaled by 3.5 / 65536, community reverse engineering) | VO2max trend |
| `hrv` | Beat-to-beat intervals | **Not present.** Requires a watch setting to log |

Every checked record contained heart rate and speed. VO2max is only written on days with a run; the exact match with the value shown in Garmin Connect is still being verified.

## Health and recovery

| Data | Endpoint | Status | Notes |
|---|---|---|---|
| HRV summaries | `/hrv-service/hrv/daily/{start}/{end}` | available | Per night: `lastNightAvg`, `lastNight5MinHigh`, `weeklyAvg`, `baseline`, `status` |
| HRV single day | `/hrv-service/hrv/{date}` | empty | Not needed, summaries cover it |
| Daily heart rate | `/wellness-service/wellness/dailyHeartRate` | available | Includes `restingHeartRate` |
| Daily summaries | `/usersummary-service/v2/dailysummaries` | available | Entries under `data`: resting HR (`heartRate.restingValue`), body battery, stress, respiration, calories, steps, intensity minutes |
| User summary | `/usersummary-service/usersummary/daily` | available | Daily totals, overlaps with daily summaries |
| Sleep summaries | `/sleep-service/sleep/dailySleepSummariesByDate` | available | Deep, light, REM and awake seconds, sleep scores, sleep need, respiration, sleep stress |
| Body battery | `/wellness-service/wellness/bodyBattery/reports/daily` | available | |
| Stress | `/usersummary-service/stats/stress/daily` | available | |
| Fitness age | `/fitnessage-service/fitnessage/v2/{date}` | available | No VO2max field |
| Heart rate zones | `/biometric-service/heartRateZones/v2` | available | Zone floors, max and resting HR used, per sport |

**Not available (HTTP 404):** everything under `/metrics-service/` that was tried: VO2max (`maxmet`), training status and training readiness. The Personal API appears to expose only an allow-listed set of endpoints.

## History reach

All activities since the watch was set up (about eight weeks before the check) are returned, both with and without a date filter. Windows further back are empty because no older data exists, so a hard API limit could not be observed.

## Consequences for the data model

- `activities`: add power, running dynamics, grade-adjusted speed and training effect fields.
- `activity_samples` and `laps`: filled from the FIT file. GPS coordinates are not stored.
- `daily_health`: add sleep stages and score, body battery, stress and respiration next to resting HR and HRV.
- New: VO2max per activity from FIT message 140.

## Privacy

Raw responses saved with `--save-raw` have email addresses and coordinates replaced by `<redacted>`. They still contain personal health data and stay in the git-ignored `raw_stage0/` folder.
