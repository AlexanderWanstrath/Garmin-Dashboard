-- Initial schema. Units are part of the column names; speeds are m/s.

-- Every API response, unchanged, so new fields can be extracted later without refetching.
CREATE TABLE raw_responses (
    endpoint   TEXT NOT NULL,
    key        TEXT NOT NULL,   -- activity id or date range
    fetched_at TEXT NOT NULL,
    json       TEXT NOT NULL,
    PRIMARY KEY (endpoint, key)
);

CREATE TABLE activities (
    id                       INTEGER PRIMARY KEY,
    source                   TEXT NOT NULL,
    start_time_local         TEXT NOT NULL,
    start_time_gmt           TEXT,
    type                     TEXT,
    name                     TEXT,
    distance_m               REAL,
    duration_s               REAL,
    elapsed_s                REAL,
    moving_s                 REAL,
    avg_hr                   REAL,
    max_hr                   REAL,
    min_hr                   REAL,
    avg_speed                REAL,
    max_speed                REAL,
    avg_moving_speed         REAL,
    avg_grade_adjusted_speed REAL,
    elevation_gain_m         REAL,
    elevation_loss_m         REAL,
    min_elevation_m          REAL,
    max_elevation_m          REAL,
    avg_cadence_spm          REAL,
    max_cadence_spm          REAL,
    avg_power_w              REAL,
    max_power_w              REAL,
    norm_power_w             REAL,
    total_work_j             REAL,
    ground_contact_ms        REAL,
    stride_length_cm         REAL,
    vertical_oscillation_cm  REAL,
    vertical_ratio_pct       REAL,
    aerobic_te               REAL,
    anaerobic_te             REAL,
    te_label                 TEXT,
    garmin_rpe               INTEGER,  -- as stored by Garmin (scale not yet confirmed)
    garmin_feel              INTEGER,  -- as stored by Garmin (scale not yet confirmed)
    calories_kcal            REAL,
    bmr_calories_kcal        REAL,
    steps                    INTEGER,
    body_battery_change      INTEGER,
    moderate_minutes         INTEGER,
    vigorous_minutes         INTEGER,
    min_temperature_c        REAL,
    max_temperature_c        REAL,
    avg_temperature_c        REAL,
    lap_count                INTEGER,
    fastest_1k_s             REAL,
    fastest_mile_s           REAL,
    fastest_5k_s             REAL,
    fastest_10k_s            REAL,
    hr_zone_1_s              REAL,
    hr_zone_2_s              REAL,
    hr_zone_3_s              REAL,
    hr_zone_4_s              REAL,
    hr_zone_5_s              REAL,
    power_zone_1_s           REAL,
    power_zone_2_s           REAL,
    power_zone_3_s           REAL,
    power_zone_4_s           REAL,
    power_zone_5_s           REAL,
    vo2max                   REAL,     -- from FIT message 140
    fit_path                 TEXT,
    synced_at                TEXT NOT NULL
);
CREATE INDEX activities_start ON activities (start_time_local);

-- Per-second samples from the FIT file. GPS positions are deliberately not stored.
CREATE TABLE activity_samples (
    activity_id             INTEGER NOT NULL REFERENCES activities (id) ON DELETE CASCADE,
    t_offset_s              INTEGER NOT NULL,
    hr                      INTEGER,
    speed                   REAL,
    distance_m              REAL,
    altitude_m              REAL,
    cadence_spm             REAL,
    power_w                 REAL,
    temperature_c           REAL,
    step_length_mm          REAL,
    vertical_oscillation_mm REAL,
    vertical_ratio_pct      REAL,
    stance_time_ms          REAL,
    PRIMARY KEY (activity_id, t_offset_s)
) WITHOUT ROWID;

CREATE TABLE laps (
    activity_id      INTEGER NOT NULL REFERENCES activities (id) ON DELETE CASCADE,
    lap_index        INTEGER NOT NULL,
    start_time       TEXT,
    distance_m       REAL,
    timer_s          REAL,
    elapsed_s        REAL,
    avg_hr           REAL,
    max_hr           REAL,
    avg_speed        REAL,
    max_speed        REAL,
    avg_cadence_spm  REAL,
    avg_power_w      REAL,
    norm_power_w     REAL,
    ascent_m         REAL,
    descent_m        REAL,
    calories_kcal    REAL,
    intensity        TEXT,
    lap_trigger      TEXT,
    PRIMARY KEY (activity_id, lap_index)
);

CREATE TABLE daily_health (
    date                  TEXT PRIMARY KEY,
    -- daily summary
    resting_hr            INTEGER,
    min_hr                INTEGER,
    max_hr                INTEGER,
    steps                 INTEGER,
    step_goal             INTEGER,
    steps_distance_m      REAL,
    floors_up             INTEGER,
    floors_down           INTEGER,
    calories_total_kcal   INTEGER,
    calories_active_kcal  INTEGER,
    calories_resting_kcal INTEGER,
    moderate_minutes      INTEGER,
    vigorous_minutes      INTEGER,
    intensity_goal_min    INTEGER,
    stress_avg            INTEGER,
    stress_max            INTEGER,
    stress_qualifier      TEXT,
    stress_rest_s         REAL,
    stress_low_s          REAL,
    stress_medium_s       REAL,
    stress_high_s         REAL,
    stress_activity_s     REAL,
    body_battery_min      INTEGER,
    body_battery_max      INTEGER,
    body_battery_charged  INTEGER,
    body_battery_drained  INTEGER,
    body_battery_latest   INTEGER,
    respiration_avg       REAL,
    respiration_min       REAL,
    respiration_max       REAL,
    -- HRV (night before this date)
    hrv_avg_ms            INTEGER,
    hrv_5min_high_ms      INTEGER,
    hrv_weekly_avg_ms     INTEGER,
    hrv_baseline_low_ms   INTEGER,
    hrv_baseline_high_ms  INTEGER,
    hrv_status            TEXT,
    -- sleep (night ending on this date)
    sleep_start_local     TEXT,
    sleep_end_local       TEXT,
    sleep_s               INTEGER,
    deep_s                INTEGER,
    light_s               INTEGER,
    rem_s                 INTEGER,
    awake_s               INTEGER,
    nap_s                 INTEGER,
    unmeasurable_s        INTEGER,
    awake_count           INTEGER,
    sleep_score           INTEGER,
    sleep_score_quality   TEXT,
    sleep_need_min        INTEGER,
    sleep_avg_hr          REAL,
    sleep_avg_stress      REAL,
    sleep_respiration_avg REAL,
    sleep_respiration_min REAL,
    sleep_respiration_max REAL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE manual_entries (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,
    activity_id INTEGER REFERENCES activities (id),
    tendon_pain INTEGER,
    rpe         INTEGER,
    fueling     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE sync_state (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
