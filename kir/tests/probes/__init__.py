"""Probes that tests run as a SEPARATE process (a race between two processes, an identity swap). They live in the tree, not in `.work/`: a test reading a scratch file was silently skipped on a clean clone (2026-09-07, measured on a frozen copy of the tree).
"""
