# Roadmap: Running Analytics Dashboard

Arbeitsdokument für die Entwicklung mit Claude Code. Es beschreibt Ziel, Umfang, Architektur und die Reihenfolge der Arbeitsschritte. Code, Kommentare und die öffentliche README werden auf Englisch geschrieben, dieses Dokument ist auf Deutsch.

---

## 1. Ziel

Ein persönliches Trainings-Dashboard für Lauf- und später Triathlontraining, das Daten direkt von Garmin holt. Bisher wird jeder Lauf als Screenshot in einen Chat geladen und dort manuell ausgewertet. Das Dashboard soll das ersetzen.

Gleichzeitig ist das Projekt ein **öffentliches Portfolio-Projekt** auf GitHub (`github.com/AlexanderWanstrath`). Es soll zeigen: Daten aus einer API abholen, in einer Datenbank ablegen, Kennzahlen sauber berechnen und testen, und das Ergebnis verständlich visualisieren.

**Erfolgskriterien**
- Ein Befehl synchronisiert neue Läufe und Gesundheitsdaten und erzeugt das Dashboard neu.
- Das Dashboard beantwortet auf einen Blick: Wie viel trainiere ich, steigere ich zu schnell, wie entwickelt sich meine Fitness, wie erholt bin ich, wie lange noch bis zum nächsten Rennen.
- Das Repo ist öffentlich, ohne dass persönliche Gesundheitsdaten oder Zugangsdaten darin landen.
- Eine Demo-Version mit synthetischen Daten ist für Außenstehende ohne Installation anklickbar (GitHub Pages).

**Orientierung, nicht Vorlage:** [SimonBassani/marathon-dashboard](https://github.com/SimonBassani/marathon-dashboard) (MIT) hat einen ähnlichen Funktionsumfang. Wir übernehmen Ideen, aber nicht den Ansatz: Dort wird die inoffizielle Bibliothek `garminconnect` mit Klartext-Passwort genutzt und ein Server betrieben. Wir nutzen die **offizielle Garmin Personal API mit API-Schlüssel** und laufen zunächst **lokal ohne Server**. Falls einzelne Codeteile übernommen werden, muss der MIT-Copyright-Hinweis mit ins Repo.

---

## 2. Leitprinzipien

1. **Keine persönlichen Daten im Repo.** SQLite-Datei, Rohdaten, Exporte, manuelle Eingaben, `.env` und `config.yaml` stehen in der `.gitignore`, bevor der erste Commit passiert. Gesundheitswerte werden nie in Logs, Tests oder Beispieldateien geschrieben.
2. **Schlüssel nie im Code, in Argumenten oder im Chat.** Der API-Schlüssel kommt aus der Umgebungsvariable `GARMIN_PERSONAL_API_KEY` oder aus der Schlüsseldatei `~/.config/garmin/connect-personal-api-key`. Der Bearer-Token-Cache liegt ebenfalls dort (vom offiziellen Client verwaltet), nie im Projektordner. Nur `runlog sync` nutzt den Schlüssel. Claude bekommt ihn auf keinem Weg: Der MCP-Server (Stufe 1g) kennt ihn nicht, und eine Deny-Regel in den Claude-Code-Einstellungen sperrt das Lesen von `~/.config/garmin/`.
3. **Persönliches von Code trennen.** Renntermine, Zielzeiten, Pulszonen, HRV-Baseline und Warnschwellen stehen in `config.yaml` (lokal). Im Repo liegt nur `config.example.yaml` mit Platzhaltern.
4. **Austauschbare Datenquellen.** Jede Quelle ist ein Adapter mit derselben Schnittstelle. Hauptquelle: Garmin Personal API, inklusive der FIT-Datei pro Aktivität, die über die API geladen wird (Sekundenwerte, Laps, VO2max). Der FIT-Adapter liest dieselben Dateien auch lokal ein (Grundlage für die Demo). Später optional Strava.
5. **Kennzahlen sind reine Funktionen mit Tests.** Jede Berechnung (Entkopplung, Steigerungsrate, Intensitätsverteilung usw.) bekommt Unit-Tests mit synthetischen Daten. Keine Berechnung im Dashboard-Template.
6. **Inkrementell und schonend gegenüber der API.** Rate Limits sind nicht dokumentiert. Bereits geladene Aktivitäten werden nicht erneut abgefragt, Rohantworten werden lokal gecacht.
7. **Einfach vor elegant.** Lokal lauffähig mit Python 3.12+, ohne Docker, Server oder Build-Schritt für Frontend-Code.

---

## 3. Stand: Stufe 0 (Machbarkeit)

Datei: `stage0_check.py` (liegt im Projektordner).

**Was das Skript macht**
- Nutzt den offiziellen Client [`garmin-connect-personal-api-python`](https://github.com/garmin/connect-personal-api-python) (Apache 2.0, PyPI-Version 1.0.0, Python ≥ 3.12). Basis-URL `https://personal.connectapi.garmin.com`, der Schlüssel wird gegen einen Bearer-Token mit 24 h Laufzeit getauscht.
- Prüft für die letzten N Tage: Aktivitätsliste und Felder der Laufzusammenfassung, Detailansicht des letzten Laufs, drei Split- und Zonen-Endpunkte ohne Wrapper (`/splits`, `/split_summaries`, `/hrTimeInZones`), FIT-Download inklusive Inhalt (sekundengenaue Records mit Puls und Tempo, Laps, HRV-Nachrichten, per `fitdecode`), Reichweite der Historie, HRV (Zusammenfassung und Einzeltag), Tagespuls mit Ruhepuls, Tageszusammenfassungen, Schlaf, Body Battery, Stress und Pulszonen.
- Gibt nur aus, **ob** Daten und Felder vorhanden sind, nie Messwerte. Die Ausgabe darf geteilt werden.
- Mit `--save-raw` werden die Rohantworten nach `raw_stage0/` geschrieben. Dieser Ordner enthält Gesundheitsdaten und ist die Grundlage für den Schema-Entwurf. Er darf nicht committet werden.

Zusätzlich prüft das Skript inzwischen die Historie in mehreren Zeitfenstern, die Feldabdeckung über alle Läufe, VO2max (API-Endpunkte und FIT-Nachricht 140) und schwärzt E-Mail und Koordinaten in den Rohdaten.

**Status: abgeschlossen (2026-11-02).** Ergebnis in [`docs/data-availability.md`](docs/data-availability.md).

**Quellenentscheidung:** Die Personal API ist die einzige Quelle.
- JSON-Endpunkte liefern Laufzusammenfassungen (inkl. Pulszonen, Leistung, Laufdynamik), HRV, Ruhepuls, Schlaf, Body Battery, Stress und Pulszonen.
- Die FIT-Datei pro Aktivität (über die API geladen) liefert Sekundenwerte mit Puls und Tempo, km-Laps und VO2max.
- Die geratenen Endpunkte `/splits`, `/split_summaries`, `/hrTimeInZones` und alles unter `/metrics-service/` (VO2max, Training Status, Training Readiness) liefern HTTP 404. Sie werden nicht gebraucht.
- Die Historie reicht bis zur Einrichtung der Uhr (ca. 8 Wochen vor dem Check). Ein API-Limit war nicht zu beobachten.

Das Abbruchkriterium (weder Läufe mit Puls noch FIT-Dateien) ist nicht eingetreten.

---

## 4. Funktionsumfang

### Ansichten

| Ansicht | Inhalt | Datengrundlage |
|---|---|---|
| Wochenvolumen | Wochenkilometer, Steigerungsrate gegenüber Vorwoche und 3-Wochen-Schnitt, Zielkurve bis zum nächsten Rennen | Aktivitäten |
| Long-Run-Progression | Längster Lauf pro Woche gegen den Plan aus `config.yaml` | Aktivitäten |
| Aerobe Entkopplung | Pro langem Lauf (Pa:HR), Verlauf über die Wochen | FIT-Records oder Splits |
| Intensitätsverteilung | Anteil Zeit in Zone 1 bis 2 gegenüber Zone 3 bis 5 pro Woche (Ziel 80/20), nach den eigenen Garmin-Zonen | `hrTimeInZone_*` oder FIT-Records |
| Erholung | HRV (Nacht-Schnitt) und Ruhepuls gegen die persönliche Baseline, 7-Tage-Schnitt | HRV- und Tagesdaten |
| Fitnesstrend | Efficiency Factor (Tempo pro Pulsschlag) lockerer Läufe über die Wochen | Aktivitäten |
| Countdown | Tage bis zu den Rennen aus `config.yaml` | Config |
| Warnungen | Siehe unten, oben im Dashboard sichtbar | Alle |

### Manuelle Eingaben
Garmin kennt diese Werte nicht, sie werden lokal erfasst:
- Sehnenschmerz 0 bis 10 (pro Tag oder pro Lauf)
- RPE 1 bis 10 pro Long Run
- Fueling pro Long Run (Freitext oder Gramm Kohlenhydrate)

Umsetzung über ein kleines CLI-Kommando, z. B. `runlog log --date 2026-11-08 --tendon 1 --rpe 6 --fuel "2 Gels"`, das in die SQLite-Datenbank schreibt. Eine statische Webseite kann nicht selbst speichern, deshalb kein Formular im Dashboard.

### Warnungen
Schwellen kommen aus `config.yaml`. Startwerte:
- Wochenkilometer steigen um mehr als 10 % gegenüber der Vorwoche
- HRV liegt mehrere Tage in Folge unter der Baseline-Untergrenze
- Ruhepuls liegt deutlich über der Baseline
- Sehnenschmerz über 2 von 10
- Tempoläufe schneller als die geplante Pace

### Kennzahlen: Definitionen
- **Steigerungsrate:** `(km_diese_Woche − km_Vorwoche) / km_Vorwoche`. Zusätzlich gegenüber dem Schnitt der letzten 3 Wochen, weil einzelne Entlastungswochen sonst falsche Warnungen auslösen.
- **Aerobe Entkopplung (Pa:HR):** Lauf in zwei gleich lange Hälften teilen, je Hälfte `EF = Geschwindigkeit / Puls`, dann `(EF_1 − EF_2) / EF_1 × 100 %`. Aufwärmphase optional ausschließen (Config). Werte unter etwa 5 % gelten als gute aerobe Grundlage.
- **Efficiency Factor:** `Geschwindigkeit (m/min) / Durchschnittspuls`, nur für lockere Läufe (Zone 1 bis 2), damit Tempoläufe den Trend nicht verzerren.
- **Intensitätsverteilung:** Zeit in Zonen summiert pro Woche. Zonengrenzen kommen aus dem Garmin-Profil (`/biometric-service/heartRateZones/v2`), mit Override in `config.yaml`.

---

## 5. Architektur

```
Garmin Personal API ─┐
                     ├─> Source-Adapter ─> Normalisierung ─> SQLite ─> Kennzahlen ─┬─> Dashboard (statisches HTML)
FIT-Dateien (lokal) ─┘                                         ▲                    └─> MCP-Server (nur lesend) ─> Claude Code
                                     manuelle Eingaben (CLI) ──┘
```

Der API-Schlüssel wird nur links vom SQLite-Kasten gebraucht (`runlog sync`). Alles rechts davon liest nur die Datenbank.

**Technologie (Vorschlag, Claude Code darf begründet abweichen)**
- Python 3.12+, Paketverwaltung über `pyproject.toml`
- Datenquelle: `garmin-connect-personal-api-python`, `fitdecode`
- Speicher: SQLite über die Standardbibliothek `sqlite3`, Schema-Migrationen als nummerierte SQL-Dateien
- Auswertung: `pandas`
- Dashboard: eine einzige statische HTML-Datei, erzeugt mit Plotly (Python) und Jinja2. Kein JavaScript-Build, öffnet sich per Doppelklick, und dieselbe Datei funktioniert mit Demodaten auf GitHub Pages
- CLI: `typer` oder `argparse`, ein Einstiegspunkt `runlog` mit Unterbefehlen `sync`, `log`, `build`, `demo`, `mcp`
- MCP: Python-SDK `mcp` (FastMCP) als optionales Extra `.[mcp]`, siehe Abschnitt 7a
- Qualität: `pytest`, `ruff`, GitHub Actions für Tests und Linting

**Datenmodell (nach Stufe 0 angepasst)**

Grundsatz: **so viele Werte wie möglich speichern**, im Dashboard wird später ausgewählt. Dafür zwei Ebenen:
1. **Rohdaten vollständig:** Jede API-Antwort landet unverändert in `raw_responses`, jede FIT-Datei unter `data/fit/`. Werden später weitere Felder gebraucht, werden sie aus diesen Rohdaten nachgezogen, ohne die API erneut abzufragen.
2. **Tabellen mit möglichst vielen Spalten**, aus den Rohdaten befüllt. Einzige Ausnahme: GPS-Koordinaten kommen in keine Tabelle (sie bleiben nur in den lokalen FIT-Dateien).

- `raw_responses`: endpoint, key (z. B. Datum oder Aktivitäts-ID), fetched_at, json
- `activities`: id, source, start_time, type, name, distance_m, duration_s, elapsed_s, moving_s, avg_hr, max_hr, min_hr, avg_speed, max_speed, avg_moving_speed, avg_grade_adjusted_speed, elevation_gain, elevation_loss, min/max_elevation, avg/max_cadence, avg/max/norm_power, total_work, ground_contact_ms, stride_length_cm, vertical_oscillation_cm, vertical_ratio, aerobic_te, anaerobic_te, te_label, rpe, feel, calories, bmr_calories, steps, body_battery_change, moderate_minutes, vigorous_minutes, min/max/avg_temperature, lap_count, fastest_1k_s, fastest_mile_s, fastest_5k_s, fastest_10k_s, hr_zone_1_s bis hr_zone_5_s, power_zone_1_s bis power_zone_5_s, vo2max (aus FIT), fit_path
- `activity_samples`: activity_id, t_offset_s, hr, speed, distance_m, altitude, cadence, power (aus FIT, für Entkopplung)
- `laps`: activity_id, index, distance_m, duration_s, avg_hr, max_hr, avg_speed, avg_cadence, avg_power, elevation_gain (aus FIT)
- `daily_health`: date, resting_hr, min_hr, max_hr, hrv_avg, hrv_5min_high, hrv_weekly_avg, hrv_baseline_low/high, hrv_status, sleep_start, sleep_end, sleep_s, deep_s, light_s, rem_s, awake_s, nap_s, awake_count, sleep_score, sleep_need_min, sleep_avg_hr, sleep_avg_stress, sleep_respiration_avg, body_battery_max, body_battery_min, body_battery_charged, body_battery_drained, body_battery_at_wake, stress_avg, stress_max, rest/low/medium/high_stress_s, respiration_avg/min/max, steps, floors_up, floors_down, calories_total, calories_active, calories_resting, moderate_minutes, vigorous_minutes
- `manual_entries`: date, activity_id (optional), tendon_pain, rpe, fueling
- `sync_state`: source, last_synced_until

---

## 6. Repo-Struktur

```
running-analytics-dashboard/
├── README.md                  ← öffentlich, Englisch, mit Screenshot der Demo
├── ROADMAP.md                 ← dieses Dokument
├── LICENSE                    ← MIT
├── pyproject.toml
├── config.example.yaml        ← Platzhalter, wird zu config.yaml kopiert
├── .gitignore                 ← data/, raw_*/, *.db, .env, config.yaml, output/
├── scripts/
│   └── stage0_check.py
├── src/runlog/
│   ├── cli.py
│   ├── config.py
│   ├── db.py
│   ├── sources/
│   │   ├── base.py            ← Schnittstelle für alle Quellen
│   │   ├── garmin_api.py
│   │   └── fit_files.py
│   ├── metrics/               ← reine Funktionen, je Kennzahl eine Datei
│   ├── warnings.py
│   ├── dashboard/             ← Jinja2-Template und Plot-Funktionen
│   └── demo.py                ← erzeugt synthetische Daten
├── tests/
├── docs/
│   └── data-availability.md   ← Ergebnis Stufe 0, ohne Messwerte
├── data/                      ← lokal, ignoriert (SQLite, Rohdaten)
└── .github/workflows/         ← Tests, Linting, Deploy der Demo auf Pages
```

---

## 7. Stufenplan

**Stand (2026-11-03):** Stufen 0, 1a, 1b, 1c, 1d, 1e und 1g sind abgeschlossen, 1f bis auf die Veröffentlichung der Demo.
- 1f: `runlog demo` erzeugt einen ausgedachten Läufer (12 Wochen Marathonaufbau, Sekundenwerte, Workout-Laps, HRV, Schlaf, Morgen-Checks, Plan mit eingebauten Abweichungen) und baut daraus `output/demo/index.html`, deterministisch über einen festen Seed. Screenshot in der README. Entscheidung: Das echte Dashboard wird nicht veröffentlicht, nur die Demo. GitHub Pages für die Demo ist noch offen.
- Relative Pfade in `config.yaml` gelten jetzt relativ zur Config-Datei (vorher: zum Arbeitsordner), in CLI und MCP-Server gleich.
- 1e: `runlog build` schreibt `output/dashboard.html` (eine Datei, `--open` öffnet sie). Inhalt: Wochenkilometer, Kacheln (Morgen-Check, HRV, Ruhepuls, VO2max, Countdown), Ampel und Warnungen, Plan-Tabelle, neun Diagramme (Wochenumfang und Long Run gegen Plan, 80/20 nach Pulsgrenze, Entkopplung, Efficiency Factor, VO2max, HRV mit Baseline-Band, Ruhepuls, Schlafphasen), Läufe der letzten 14 Tage. Hell- und Dunkelmodus über Farbtokens, Umschalter oben rechts, jedes Diagramm mit Tabellenansicht. Daten aus `runlog.tools`, also dieselben Zahlen wie beim MCP-Server. Plotly.js kommt vom CDN, die Diagramme brauchen also Internet.
- Der MCP-Server wird mit `python -m runlog.mcp_server` registriert, nicht über `runlog.exe`: Ein laufender Server sperrt sonst die exe, und `pip install -e .` schlägt fehl.
- 1g: `runlog mcp` startet den lokalen MCP-Server (Python-SDK `mcp` 2.x, dort heißt FastMCP jetzt `MCPServer`). Abfragelogik in `src/runlog/tools.py`, Registrierung in `src/runlog/mcp_server.py`. Zusätzlich zu den geplanten Werkzeugen gibt es `get_plan_status` (Plan-Abgleich). Datenbank doppelt schreibgeschützt, Pfade relativ zur Config-Datei. Tests prüfen Import-Isolation, keinen Zugriff auf die Key-Variable und `~/.config/garmin`, und dass Schreiben fehlschlägt. Registriert mit `claude mcp add --scope local`, Deny-Regel in `.claude/settings.json`.
- 1d: `runlog log` erfasst den Morgen-Check (Patellasehne 0-10, Anlaufschmerz, Beine, Hüfte) und Fueling pro Lauf. RPE kommt aus Garmins Selbsteinschätzung auf der Uhr. `runlog check` zeigt die Ampel (grün/gelb/rot je Signal, das schlechteste entscheidet, mit Empfehlung), Warnungen (Wochenkilometer gegen den 3-Wochen-Schnitt) und den Abgleich mit dem Trainingsplan aus `plan.yaml` (lokal, Vorlage `plan.example.yaml`): Umfang, Pace-Obergrenze und Zeit über der Pulsgrenze bei lockeren Läufen, Wiederholungen von Qualitätseinheiten anhand der Workout-Laps der Uhr, Fueling in g/h, Wochenumfang. „Locker“ ist über eine feste Pulsgrenze aus der Config definiert, nicht über Garmins Zonen, weil Garmin die Zonen zwischendurch verschiebt. `runlog sync --reparse` wertet die gespeicherten FIT-Dateien neu aus, ohne die API abzufragen.
- `runlog sync` lädt Aktivitäten (inkl. FIT-Sekundenwerte, Laps, VO2max) und Gesundheitsdaten in `data/runlog.db`. Zweiter Aufruf lädt nur Neues, Gesundheitsdaten der letzten 3 Tage werden neu geladen, weil Garmin sie nachträglich ergänzt.
- Kennzahlen in `src/runlog/metrics/` als reine Python-Funktionen (ohne pandas, die Datenmengen sind klein): Wochenvolumen mit Steigerungsrate, Long Runs, aerobe Entkopplung, Efficiency Factor lockerer Läufe, Intensitätsverteilung, HRV und Ruhepuls gegen Baseline. Unplausible Aufzeichnungen (z. B. Bahnmodus mit verlorener Distanz) werden beim Efficiency Factor ausgelassen.
- Repo: [github.com/AlexanderWanstrath/Garmin-Dashboard](https://github.com/AlexanderWanstrath/Garmin-Dashboard) (als Remote eingetragen, noch nicht gepusht).

Jede Stufe endet mit einem lauffähigen Zwischenstand und einem Commit. Nach jeder Stufe kurz prüfen, ob noch etwas Persönliches im Git-Index liegt (`git status`, `git diff --cached`).

| Stufe | Inhalt | Fertig, wenn |
|---|---|---|
| **0** | Machbarkeit, siehe Abschnitt 3 | `docs/data-availability.md` existiert, Quellenentscheidung ist getroffen |
| **1a** | Grundgerüst: Struktur, `pyproject.toml`, `.gitignore`, `config.example.yaml`, CLI-Skelett, CI | `runlog --help` läuft, CI ist grün, kein persönliches File im Repo |
| **1b** | Datenaufnahme: Source-Schnittstelle, Garmin-Adapter, FIT-Adapter, SQLite-Schema, inkrementeller Sync | `runlog sync` lädt alle Läufe und Gesundheitsdaten seit Trainingsbeginn, zweiter Aufruf lädt nur Neues |
| **1c** | Kennzahlen mit Tests: Wochenvolumen, Steigerungsrate, Long Run, Entkopplung, EF, Intensitätsverteilung, HRV/Ruhepuls gegen Baseline | Alle Funktionen haben Tests mit synthetischen Daten, Ergebnisse für echte Läufe sind plausibel |
| **1d** | Manuelle Eingaben und Warnungen | `runlog log` schreibt Einträge, Warnungen werden mit Begründung ausgegeben |
| **1e** | Dashboard | `runlog build` erzeugt `output/dashboard.html` mit allen Ansichten aus Abschnitt 4 |
| **1f** | Demo und Veröffentlichung: Generator für synthetische Daten, GitHub-Pages-Deploy, README mit Screenshot und Architekturbild | Demo ist öffentlich erreichbar, README erklärt Setup in unter 5 Schritten |
| **1g** | Lokaler MCP-Server (nach 1d, siehe Abschnitt 7a) | `claude mcp list` zeigt den Server als verbunden, „Wie war meine letzte Trainingswoche?“ wird über die Werkzeuge mit echten Werten beantwortet, Tests grün, keine Datenbank und kein persönlicher Pfad im Git-Index |
| **2** (optional) | Zugriff vom Handy: gehosteter MCP-Server mit HTTPS und OAuth | Erst angehen, wenn Stufe 1g im Alltag genutzt wird und der mobile Zugriff fehlt |

Reihenfolge: 1g kommt nach 1d, weil `get_warnings` und `get_manual_entries` die Warnungen und manuellen Eingaben brauchen. 1g kann vor 1e und 1f umgesetzt werden.

---

## 7a. Stufe 1g: Lokaler MCP-Server

**Ziel:** Claude Code fragt die Trainingsdaten direkt ab, statt dass Screenshots hochgeladen werden. Der Garmin-API-Schlüssel geht dabei nie an Claude. Die zurückgegebenen Messwerte gehen dagegen bewusst an Claude, also an Anthropic, genau wie bisher die Screenshots.

**Architektur: Sync und MCP strikt trennen**
- `runlog sync` ist die einzige Komponente, die den Garmin-API-Schlüssel nutzt. Sie schreibt in die SQLite-Datenbank.
- Der MCP-Server liest nur aus der SQLite-Datenbank. Er importiert den Garmin-Client weder direkt noch indirekt und liest weder den Schlüssel noch die Schlüsseldatei noch `GARMIN_PERSONAL_API_KEY`.
- Der Server läuft lokal als stdio-Server, den Claude Code startet. Kein HTTP, kein offener Port, kein Hosting.

**Umsetzung**
- Python-MCP-SDK (`mcp`, FastMCP), Modul `src/runlog/mcp_server.py`, Start über `runlog mcp`.
- Datenbank doppelt schreibgeschützt öffnen: `sqlite3.connect("file:<pfad>?mode=ro", uri=True)` und zusätzlich `PRAGMA query_only = ON`. Die Datenbank bleibt im Standard-Journalmodus (kein WAL), damit der Nur-Lese-Zugriff zuverlässig funktioniert.
- Die Werkzeuge rufen die bestehenden Funktionen aus `src/runlog/metrics/` und `warnings.py` auf. Keine doppelte Berechnungslogik.
- Rückgaben als kompaktes JSON mit Einheiten im Feldnamen (z. B. `distance_km`, `pace_min_per_km`).
- Der Pfad zur Datenbank kommt aus `config.yaml`, nicht hart codiert.

**Werkzeuge (nur lesend)**
- `get_recent_runs(days: int = 14)`: Läufe mit Datum, Distanz, Pace, Durchschnittspuls, Zonenanteilen
- `get_run_details(activity_id)`: Splits, aerobe Entkopplung, Efficiency Factor (Splits hängen von der Quellenentscheidung aus Stufe 0 ab)
- `get_weekly_volume(weeks: int = 8)`: Wochenkilometer, Steigerungsrate, längster Lauf
- `get_intensity_distribution(weeks: int = 4)`: Anteil locker gegenüber intensiv (80/20)
- `get_recovery_status(days: int = 14)`: HRV und Ruhepuls gegen die Baseline, 7-Tage-Schnitt
- `get_warnings()`: aktive Warnungen mit Begründung
- `get_countdown()`: Tage bis zu den Events aus `config.yaml`
- `get_manual_entries(days: int = 14)`: Sehnenschmerz, RPE, Fueling

**Ausdrücklich nicht**
- kein Werkzeug, das beliebiges SQL ausführt
- kein Werkzeug, das Garmin abfragt oder einen Sync startet
- kein Werkzeug, das in die Datenbank schreibt
- keine Rückgabe von Schlüssel, Token, Dateipfaden oder Roh-JSON von Garmin

**Registrierung in Claude Code**
- Mit `claude mcp add --scope local` registrieren, nicht als `.mcp.json` im Repo, weil darin lokale Pfade stehen.
- Keine Umgebungsvariablen mit Geheimnissen, der Server braucht keine.
- Der Befehl steht in der README, mit Platzhalter für den Pfad, z. B. `claude mcp add runlog --scope local -- <projekt>/.venv/Scripts/python.exe -m runlog.mcp_server`.
- Zusätzlich eine Deny-Regel in den Claude-Code-Einstellungen für `~/.config/garmin/**` (Read, Edit), damit auch die normalen Datei-Werkzeuge den Schlüssel und den Token-Cache nicht lesen. Diese Regel schützt nicht vollständig gegen Shell-Befehle und ersetzt daher nicht die Trennung im Code.

**Tests**
- Jedes Werkzeug mit einer Test-Datenbank aus synthetischen Daten (Generator aus `demo.py`).
- Import-Test in einem eigenen Prozess: Nach `import runlog.mcp_server` steht `garmin_personal_api` nicht in `sys.modules`. Damit fallen auch indirekte Importe über `metrics` oder `config` auf.
- Test, dass der Server `GARMIN_PERSONAL_API_KEY` nicht liest (Umgebungszugriff überwachen) und keine Datei unter `~/.config/garmin/` öffnet.
- Test, dass ein Schreibversuch auf der Datenbank fehlschlägt.

**Später (Stufe 2, nicht jetzt):** Zugriff vom Handy erfordert einen gehosteten Server mit HTTPS und OAuth. Das wird erst geplant, wenn die lokale Variante im Alltag genutzt wird.

---

## 8. Offene Fragen

- ~~Welche Felder liefert die Personal API wirklich?~~ Beantwortet, siehe [`docs/data-availability.md`](docs/data-availability.md).
- ~~Wie weit reicht die Historie zurück?~~ Bis zur Einrichtung der Uhr, ein Limit war nicht zu beobachten.
- VO2max steht nicht im JSON, aber in der FIT-Datei (undokumentierte Nachricht 140, Feld 7). Noch offen: exakter Abgleich mit dem Wert in Garmin Connect (Rundung bzw. Zeitpunkt). Weil das Feld undokumentiert ist, soll der Import fehlende oder unplausible Werte melden.
- Rate Limits sind nicht dokumentiert. Bei HTTP 429 mit Backoff reagieren und die Abfragefrequenz reduzieren.
- Der API-Schlüssel läuft nach maximal einem Jahr ab, auf Wunsch schon nach 30 Tagen (aktuell: 30-Tage-Schlüssel für die Testphase). Das Tool soll einen abgelaufenen Schlüssel klar melden statt mit einem unverständlichen Fehler abzubrechen.

## 9. Referenzen

- Garmin Personal API: [Overview](https://developer.garmin.com/gc-developer-program/personal/personal-api), [FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq/), [Swagger](https://developer.garmin.com/gc-developer-program/personal/swagger-docs/)
- Offizieller Python-Client: [garmin/connect-personal-api-python](https://github.com/garmin/connect-personal-api-python)
- Orientierung: [SimonBassani/marathon-dashboard](https://github.com/SimonBassani/marathon-dashboard)
