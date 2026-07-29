"""Vicon motion-capture sync tools for Level IMU captures.

A small toolkit for aligning Level IMU recordings with Vicon Nexus mocap:

- :mod:`bridge`     — log Vicon DataStream frames to a timestamped CSV.
- :mod:`merge`      — align a Level IMU session with a Vicon CSV and emit a
  merged dataset (desktop single-clock or android two-clock path).
- :mod:`pull_imu`   — pull an IMU session off an Android device via adb.
- :mod:`clock_sync` — record the phone↔PC clock offset for the android path.

Each module exposes a ``main()`` and is installed as a console script
(``lvl-vicon-bridge``, ``lvl-vicon-merge``, ``lvl-vicon-pull``,
``lvl-vicon-clocksync``). ``bridge`` additionally needs ``vicon_dssdk`` (ships
with the Vicon DataStream SDK installer; not on PyPI).
"""
