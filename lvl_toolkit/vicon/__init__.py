"""Vicon motion-capture sync tools for Level IMU captures.

A small toolkit for aligning Level IMU recordings with Vicon Nexus mocap:

- :mod:`merge`      — align a Level IMU session with a Vicon CSV and emit a
  merged dataset (desktop single-clock or android two-clock path).
- :mod:`pull_imu`   — pull an IMU session off an Android device via adb.
- :mod:`clock_sync` — record the phone↔PC clock offset for the android path.

Each module exposes a ``main()`` and is installed as a console script
(``lvl-vicon-merge``, ``lvl-vicon-pull``, ``lvl-vicon-clocksync``). The Vicon
CSV these consume (one row per frame·marker, PC-wallclock timestamp per frame)
is written during collection by the Level desktop app.
"""
