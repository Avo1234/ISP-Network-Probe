# Roadmap

Phase 1 (collect data + dashboard) is complete. Nothing below is built yet.

## 1. Clock fix and data cleanup (next)

- **Stop it happening again:** at startup `probe.py` waits until the system reports the clock as synchronised before it records anything, with a 3-minute limit so it still runs if the time server is unreachable. It prints a line when recording starts. About 8 lines near the top of `main()`.
- **Clean up the 5 bad stretches:** a one-time script that first makes a backup copy of `probe.db`, finds rows stamped *before* the latest time already recorded (in insertion order), shows the count and time ranges, waits for confirmation, then **moves** (not deletes) them to a `suspect_samples` table.

## 2. Data usage tracking

Measure how much mobile data the Pi really uses, since the 0.5 GB/month figure is an estimate.

- Two nftables counters (bytes sent to / received from non-private addresses), so local traffic (router pings, SSH, dashboard views) isn't counted.
- A small script on a systemd timer, every minute, storing the difference in its own `usage.db` (separate, because reading the counters needs root and shouldn't touch `probe.db`'s permissions). Counter resets at reboot are detected.
- A command-line report: today, last 7 days, this month.
- Limits: counts IP-level bytes, so the ISP's figure will be slightly higher. It only counts from the day it's installed. A hard power cut loses up to a minute of counts.

## 3. Phase 2: availability and probability report

A command-line report for any period you choose, computing the course maths directly and showing the formulas:

- **P(F)** for each target: failures / total pings, with the counts shown.
- **P(A or B)** by the addition rule, checked against the observed count.
- **P(A and B)** compared with P(A) x P(B), with a one-line verdict on whether the two targets are independent.
- The same figures per hour of day.
- Availability %, outage count, longest outage.
- "Probe offline" time reported separately from real outages, and `ignore_windows` skipped.
- A clearly labeled "two lines" calculation under the independence assumption.

## 4. Phase 3: prediction

Needs roughly two weeks of data first.

- **Baseline:** availability by hour of week (for example "evenings are 3x worse").
- **Model:** a small model such as logistic regression estimating the chance of an outage in the next 15-30 minutes, using early-warning signs like rising jitter or loss. Train on a laptop, run the lightweight result on the Pi.
- Truly random outages can't be predicted. Time patterns and early warning signs can.

## 5. Open decision: second line

Does the project need an **actual measured** two-ISP result?

- **A:** one line for now, independence tested between the two targets, second line added later if needed.
- **B:** plan a second Pi on another ISP now, so both lines are measured together from the start.
