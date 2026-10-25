"""Simulated camera and in-memory mood detection (feature F9).

The prototype has no real face model. :class:`SimulatedCamera` renders a tiny
synthetic grey-scale "face" whose eye openness, mouth curve and brow tension
depend on the expression the demo user chooses. :class:`MoodDetector` measures
those regions and classifies the mood.

Privacy requirement: the frame exists only as a NumPy array in RAM. It is
never written to disk or sent over the network, and :meth:`MoodDetector.analyze`
zero-fills the buffer and drops the reference before it returns, so only the
mood label leaves the function.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

MOODS = ["Neutral", "Tired", "Happy", "Stressed"]
FRAME_SIZE = 64

# Region rows in the synthetic frame
_EYES = slice(18, 28)
_MOUTH = slice(42, 52)
_BROW = slice(10, 16)

SUGGESTIONS = {
    "Tired": "You look tired - we added an extra espresso shot.",
    "Happy": "Great mood! How about something sweet or iced?",
    "Stressed": "Take it easy - a low-caffeine, comforting drink is on top.",
    "Neutral": "No strong mood detected - showing your usual favourites.",
}


@dataclass(frozen=True)
class MoodResult:
    """Output of mood detection - the only data that survives the analysis."""

    mood: str
    confidence: float
    suggestion: str


class SimulatedCamera:
    """Produces synthetic face frames for a chosen expression (demo only)."""

    _FEATURES = {
        # eye openness, mouth curve (smile), brow tension, all 0..1
        "Neutral": (0.6, 0.5, 0.3),
        "Tired": (0.15, 0.4, 0.2),
        "Happy": (0.8, 0.9, 0.2),
        "Stressed": (0.7, 0.2, 0.9),
    }

    def __init__(self, seed: int | None = None) -> None:
        """Create the camera.

        Args:
            seed: random seed for the sensor noise (None = random).

        Returns:
            None.
        """
        self._rng = np.random.default_rng(seed)
        self.frames_captured = 0

    def capture(self, expression: str) -> np.ndarray:
        """Grab one frame showing the given expression.

        Args:
            expression: one of :data:`MOODS`.

        Returns:
            np.ndarray: ``FRAME_SIZE x FRAME_SIZE`` float32 image in RAM, values 0..1.
        """
        eyes, mouth, brow = self._FEATURES.get(expression, self._FEATURES["Neutral"])
        frame = np.full((FRAME_SIZE, FRAME_SIZE), 0.5, dtype=np.float32)
        frame[_EYES, :] = eyes
        frame[_MOUTH, :] = mouth
        frame[_BROW, :] = brow
        frame += self._rng.normal(0.0, 0.03, frame.shape).astype(np.float32)
        np.clip(frame, 0.0, 1.0, out=frame)
        self.frames_captured += 1
        return frame


class MoodDetector:
    """Classifies mood from a frame using in-memory inference only."""

    def __init__(self) -> None:
        """Create the detector with privacy counters.

        Returns:
            None.
        """
        self.frames_processed = 0
        self.frames_stored = 0      # always stays 0 - nothing is persisted
        self.last_buffer_cleared = False

    @staticmethod
    def _classify(eyes: float, mouth: float, brow: float) -> tuple[str, float]:
        """Rule-based classifier over the three facial measurements.

        Args:
            eyes: mean intensity of the eye region (openness).
            mouth: mean intensity of the mouth region (smile).
            brow: mean intensity of the brow region (tension).

        Returns:
            tuple[str, float]: (mood label, confidence 0..1).
        """
        scores = {
            "Tired": (0.5 - eyes) * 2.0,
            "Happy": (mouth - 0.6) * 2.5,
            "Stressed": (brow - 0.5) * 2.0 + (0.4 - mouth),
        }
        mood, best = max(scores.items(), key=lambda kv: kv[1])
        if best < 0.25:
            return "Neutral", round(min(1.0, 0.6 + (0.25 - best)), 2)
        return mood, round(min(1.0, 0.5 + best / 2), 2)

    def analyze(self, frame: np.ndarray) -> MoodResult:
        """Detect the mood and immediately destroy the image.

        Args:
            frame: grey-scale frame from the camera (modified in place: zeroed).

        Returns:
            MoodResult: mood label, confidence and drink suggestion text.
        """
        try:
            eyes = float(frame[_EYES, :].mean())
            mouth = float(frame[_MOUTH, :].mean())
            brow = float(frame[_BROW, :].mean())
            mood, confidence = self._classify(eyes, mouth, brow)
            self.frames_processed += 1
        finally:
            frame.fill(0.0)                 # wipe pixel data from memory
            self.last_buffer_cleared = not frame.any()
            del frame                       # drop our reference
        return MoodResult(mood, confidence, SUGGESTIONS[mood])
