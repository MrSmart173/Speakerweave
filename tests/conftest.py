"""Shared set up for the tests: windows are drawn off screen, on a full HD screen, so a test
sees the window as it is on a normal PC (the plain off screen screen is only 800 pixels)."""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.environ.get("QT_QPA_PLATFORM", "offscreen") == "offscreen":
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + os.path.join(_HERE, "screen.json")
