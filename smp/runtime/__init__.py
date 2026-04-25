"""Process-level runtime adapters: sandboxing and external integrations.

This package houses the *real* execution surface that ``smp/sandbox/*``
and ``smp/pr/create`` delegate to.  Each component is intentionally
small and explicit about its threat model — see the module docstrings
for what is and is not protected.
"""
