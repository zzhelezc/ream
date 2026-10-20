"""ream: one page on an infinite canvas.

Write on the page; when it fills, the next one slides in.  Images and PDFs
live on the canvas around it, and whatever is dragged onto the page goes out
with the PDF - optionally run through the Texturelabs Distressor's textures.
"""
# The one place the version lives (pyproject.toml reads it from here).
# Semantic Versioning 2.0.0 (https://semver.org): MAJOR.MINOR.PATCH -
# MAJOR when .ream files or the plugin API stop working as they did, MINOR
# for new features that keep them working, PATCH for fixes.  Until 1.0.0
# anything may still change.  Every version has its entry in CHANGELOG.md.
__version__ = "0.3.1"
