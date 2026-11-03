-- Morning check and fueling. tendon_pain is the patellar tendon (0-10); rpe stays unused
-- because Garmin's own self-evaluation is stored in activities.garmin_rpe.
ALTER TABLE manual_entries ADD COLUMN startup_pain INTEGER;  -- 1 = pain when starting to move
ALTER TABLE manual_entries ADD COLUMN legs TEXT;            -- fresh, heavy, very_heavy
ALTER TABLE manual_entries ADD COLUMN hip_pain INTEGER;     -- 1 = hip pain
ALTER TABLE manual_entries ADD COLUMN fuel_g REAL;          -- carbohydrates taken during the activity
ALTER TABLE manual_entries ADD COLUMN note TEXT;
CREATE INDEX manual_entries_date ON manual_entries (date);
