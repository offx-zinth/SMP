"""Operational observability — metrics, request logging, and admin glue.

This package is deliberately dependency-free: metrics are emitted in
the Prometheus exposition format from a tiny in-process registry so
SMP can be scraped without pulling :mod:`prometheus_client` (or any
similar runtime dep) into the install footprint.
"""
