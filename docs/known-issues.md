# Known issues and untested parts

Honest status as of 2026-10-27.

## Found, not fixed yet

- **Clock problem after restarts.** The Pi has no battery-backed clock. After a boot it can briefly use a stale time, so the first rows after a restart can be stamped *earlier* than rows already saved. A check of 1,712 rows found **5 out-of-order stretches**, each at a restart (in insertion order, a timestamp going backwards, then a jump forward of 1 to 5 minutes). The cause is the most likely explanation, not confirmed. The planned fix is in [roadmap.md](roadmap.md). Until it's fixed, treat the first few minutes after any boot as suspect. `scripts/check-data.py` finds these.

## Not verified

- **Run Test adds no rows to the database.** Designed that way. The before/after row count was never checked.
- **Data use** is estimated (about 0.5 GB/month) but not measured.
- **The greyed-out nav buttons' contrast** on every phone browser.

## Limitations by design

- **No login, no HTTPS** on the dashboard. Anyone on the same Wi-Fi can open it. Don't expose port 8080 to the internet.
- **Health score and status thresholds are guesses**, not validated. For example, a 2-second DNS time costs only a few points.
- **One line only (Telecel).** Two outside targets behind one line are not independent. Comparing ISPs, or testing redundancy, needs a second line measured at the same time.
- **ICMP loss isn't always real loss.** Some servers deprioritise pings. Using two targets helps spot this.
- **Pings in one cycle aren't independent.** Loss tends to come in bursts, so treat per-ping and per-cycle probabilities separately.
- **Only the dashboard's Stability Note honors `ignore_windows`** so far.
- On a fetch error the dashboard's health score keeps showing the last good value.

## Operational notes

- **Gaps are not outages.** If the Pi is off (power cut, unplugged), the database simply has no rows for that time. We saw a gap of about 389 minutes when the Pi was powered off. Any analysis must count "no data" separately from "100% loss".
- **Use `sudo shutdown -h now` before unplugging.** A hard power cut risks SD card corruption and loses up to a minute of readings.
- **Don't run `probe.py` by hand while the service is running**, or you'll get duplicate rows.
- **Known fake outage:** 2026-10-27 10:40:44 to 10:44:38 UTC (see [03b-test-outage.md](03b-test-outage.md)). Exclude it from analysis.
- **A harmless first-run error:** `Permission denied` when running `~/probe/probe.py` directly. Use `python3 ~/probe/probe.py`.
