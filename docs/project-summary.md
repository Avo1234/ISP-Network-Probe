# How this project maps to the course brief

**Brief:** *ISP Network Downtime & Reliability Monitor.* A Raspberry Pi or laptop script that pings external servers to analyse packet drops and predict availability, using empirical probability, sample spaces, and the addition and multiplication rules for compound events.

## Requirement by requirement

| Brief requirement | This project | Status |
|---|---|---|
| Pi connected to the local router | Pi Zero 2 W on Wi-Fi, pinging the router and two outside targets | Met |
| Ping an external server many times a day | 5 pings every 10 s to each of 1.1.1.1 and 8.8.8.8, about 43,000 pings per target per day (the brief suggests 1,000) | Met, with far more data |
| Empirical probability P(F) = failures / total | Data supports it. Failures per cycle = loss% x 5 / 100 | Data collected, calculation not built yet |
| Sample space and compound events | Each ping is {success, fail}. Events like "both targets fail" can be defined | Data collected, calculation not built yet |
| Addition rule P(A or B) = P(A) + P(B) - P(A and B) | Computable for "1.1.1.1 fails or 8.8.8.8 fails" | Planned for the Phase 2 report |
| Multiplication rule, two lines | **Not covered.** We have one line | Needs a decision, see below |
| Predict availability | Hour-of-week baseline, then a small model | Phase 3, needs about two weeks of data |
| Python `ping` and `scapy` | System `ping`, no `scapy` | Partly (see design-decisions.md) |

## The multiplication rule needs two separate lines

`P(Total Failure) = P(A fails) x P(B fails)` is only valid when the lines fail **independently**, and the only way to check is to measure both at the same time.

With one Pi on one Telecel line, 1.1.1.1 and 8.8.8.8 both travel through the same link. If the link dies, both fail together, so they are not independent. That's still useful: we can test the independence assumption directly. If P(both fail) is much larger than P(1.1.1.1 fails) x P(8.8.8.8 fails), the data shows the multiplication rule does not apply to targets behind one line. That is a result worth reporting, but it does not prove anything about two redundant ISPs. For that, a second line must be measured at the same time (for example a second Pi on another ISP). See the open decision in [roadmap.md](roadmap.md).

## Cautions for the maths

- **Pings in the same cycle aren't independent.** Loss tends to come in bursts. Report P(F) per ping and per 10-second cycle.
- **ICMP loss isn't always real loss.** Some servers deprioritise pings.
- **Gaps aren't failures.** Time when the Pi was off must be excluded, not counted as 100% loss. The known fake outage (2026-10-27 10:40:44 to 10:44:38 UTC) must be excluded too.
- **Clean timestamps first.** The out-of-order rows after restarts need fixing before any time-of-day analysis. See [known-issues.md](known-issues.md).
