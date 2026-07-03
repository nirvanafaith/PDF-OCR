from PyQt5.QtCore import Qt
from PyQt5.QtGui import QWheelEvent

ZOOM_MIN = 0.25
ZOOM_MAX = 5.0
ZOOM_STEP_BUTTON = 0.25
ZOOM_STEP_WHEEL = 0.1


def calculate_wheel_zoom(event, current_zoom):
    try:
        if not isinstance(event, QWheelEvent):
            return None
        if not (event.modifiers() & Qt.ControlModifier):
            return None
        delta = event.angleDelta().y()
        if delta == 0:
            return None
        if delta > 0:
            new_zoom = current_zoom + ZOOM_STEP_WHEEL
        else:
            new_zoom = current_zoom - ZOOM_STEP_WHEEL
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, new_zoom))
        if new_zoom == current_zoom:
            return None
        return new_zoom
    except Exception:
        return None