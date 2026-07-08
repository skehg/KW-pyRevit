# Vendor Packages

Place vendored third-party modules in this folder for offline/enterprise deployments.

For the help system, the expected package is:

- markdown (pin to 2.6.11 for IronPython 2.7 compatibility)

Example layout:

vendor/
  markdown/
    __init__.py
    ...

The Create Views tool imports help support lazily, and the help viewer imports markdown lazily.
If markdown is not available at runtime, a friendly message is shown when Help is clicked.
