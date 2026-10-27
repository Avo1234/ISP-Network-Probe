# Design decisions

The "why" behind each choice, including what we chose **not** to build.

## Why a custom probe, not Uptime Kuma or LibreNMS

- **Uptime Kuma** answers "is it up?" with a pass/fail check. We need per-packet loss, latency and jitter history to compute probabilities and train a model. It is also a heavier Node.js app than a 512 MB Pi Zero 2 W needs to carry.
- **LibreNMS** is built for SNMP monitoring of managed network gear, runs as a multi-container stack (database, cache, pollers), and is far too heavy for a Zero 2 W. It also wouldn't give us a path-level view of the ISP link.
- A single Python script and SQLite file is the simplest thing that produces exactly the data we need.

## Why measure the router separately

The router answers from inside itself, so pinging it measures only the local Wi-Fi hop. If the router is fine but the outside targets fail, the fault is the ISP link or beyond. If the router drops too, it's local Wi-Fi. This stops Wi-Fi trouble being blamed on the ISP.

> Earlier in the project we assumed a mobile router's ping would partly reflect the radio link. That was wrong: `192.168.8.1`-style addresses answer from inside the router.

## Why two outside targets

One server's bad moment shouldn't look like an outage. Requiring both to fail before declaring "internet down" filters out single-target problems. A side effect: 1.1.1.1 and 8.8.8.8 both travel through the same line, so they are **not independent** (see [project-summary.md](project-summary.md)).

## Why SQLite with batched writes

One file, no server, easy to analyze later. Readings are written about once a minute instead of every 10 seconds to reduce SD card wear. The cost: a hard power cut loses up to a minute of readings, and the dashboard lags by up to a minute.

## Why system `ping` instead of `scapy`

`ping` needs no root and no extra packages, and it's enough for loss and latency. `scapy` can be added later if raw packet control is needed.

## Why a random DNS name

A fresh made-up subdomain can't be cached, so every lookup goes all the way upstream. That measures the real resolver path. "Name does not exist" counts as success because the question is whether DNS answers, and how fast.

## Why the dashboard serves its own Chart.js

The dashboard is most useful during an outage, which is exactly when a CDN-hosted library would fail to load. The page is served over the local Wi-Fi, so it works when the ISP is down.

## Why Run Test doesn't save

Saved readings feed the probability and prediction work. A manual test would add off-schedule samples and distort the timeline.

## Why Wi-Fi power saving is off

A known cause of random latency spikes on the Zero 2 W's Wi-Fi chip. Left on, it would add noise from our own hardware.

## Why one dashboard page

The original design had four tabs. We kept the layout but built only Overview. The other three nav buttons are greyed out so adding pages later needs no redesign.

## Why `ignore_windows`

The simulated outage left fake data. A small table of start/end times lets analysis skip known-bad windows without deleting anything.
