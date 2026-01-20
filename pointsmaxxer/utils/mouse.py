from __future__ import annotations

"""Human-like mouse movement utilities for PointsMaxxer."""

import asyncio
import random
import math
from typing import Optional, Tuple

import numpy as np
from playwright.async_api import Page


def bezier_curve(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    num_points: int = 50
) -> list[Tuple[float, float]]:
    """Generate points along a cubic Bezier curve.

    Args:
        p0: Start point.
        p1: First control point.
        p2: Second control point.
        p3: End point.
        num_points: Number of points to generate.

    Returns:
        List of (x, y) points along the curve.
    """
    points = []
    for i in range(num_points):
        t = i / (num_points - 1)
        t2 = t * t
        t3 = t2 * t
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt

        x = mt3 * p0[0] + 3 * mt2 * t * p1[0] + 3 * mt * t2 * p2[0] + t3 * p3[0]
        y = mt3 * p0[1] + 3 * mt2 * t * p1[1] + 3 * mt * t2 * p2[1] + t3 * p3[1]
        points.append((x, y))

    return points


def generate_control_points(
    start: Tuple[float, float],
    end: Tuple[float, float],
    deviation: float = 0.3
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Generate random control points for a Bezier curve.

    Args:
        start: Start point.
        end: End point.
        deviation: How much control points can deviate from straight line.

    Returns:
        Tuple of two control points.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]

    # Control point 1: ~1/3 along the path with random deviation
    cx1 = start[0] + dx * 0.33 + random.uniform(-deviation, deviation) * abs(dy)
    cy1 = start[1] + dy * 0.33 + random.uniform(-deviation, deviation) * abs(dx)

    # Control point 2: ~2/3 along the path with random deviation
    cx2 = start[0] + dx * 0.67 + random.uniform(-deviation, deviation) * abs(dy)
    cy2 = start[1] + dy * 0.67 + random.uniform(-deviation, deviation) * abs(dx)

    return ((cx1, cy1), (cx2, cy2))


def add_noise(points: list[Tuple[float, float]], noise_level: float = 1.0) -> list[Tuple[float, float]]:
    """Add small random noise to path points.

    Args:
        points: List of points.
        noise_level: Maximum noise in pixels.

    Returns:
        Points with noise added.
    """
    return [
        (
            x + random.uniform(-noise_level, noise_level),
            y + random.uniform(-noise_level, noise_level)
        )
        for x, y in points
    ]


def calculate_delays(num_points: int, total_time: float) -> list[float]:
    """Calculate delays between mouse movements with easing.

    Uses ease-in-out timing for natural acceleration/deceleration.

    Args:
        num_points: Number of points in path.
        total_time: Total time for movement in seconds.

    Returns:
        List of delay times in seconds.
    """
    delays = []
    for i in range(num_points - 1):
        # Ease-in-out function
        t = i / (num_points - 1)
        # Slower at start and end, faster in middle
        ease = 0.5 - math.cos(t * math.pi) / 2

        # Base delay with easing
        base_delay = total_time / num_points
        delay = base_delay * (0.5 + ease)

        # Add small random variation
        delay *= random.uniform(0.8, 1.2)
        delays.append(delay)

    return delays


class HumanMouse:
    """Simulates human-like mouse movements."""

    def __init__(
        self,
        page: Page,
        speed: float = 1.0,
        deviation: float = 0.3,
        noise: float = 1.0,
    ):
        """Initialize human mouse.

        Args:
            page: Playwright Page instance.
            speed: Speed multiplier (1.0 = normal, 2.0 = twice as fast).
            deviation: Path curvature deviation.
            noise: Noise level in pixels.
        """
        self.page = page
        self.speed = speed
        self.deviation = deviation
        self.noise = noise
        self._current_pos: Optional[Tuple[float, float]] = None

    async def get_current_position(self) -> Tuple[float, float]:
        """Get current mouse position.

        Returns:
            Tuple of (x, y) coordinates.
        """
        if self._current_pos is None:
            # Start from a random position on screen
            viewport = self.page.viewport_size
            if viewport:
                self._current_pos = (
                    random.uniform(100, viewport["width"] - 100),
                    random.uniform(100, viewport["height"] - 100),
                )
            else:
                self._current_pos = (400.0, 300.0)
        return self._current_pos

    async def move_to(
        self,
        x: float,
        y: float,
        duration: Optional[float] = None,
    ) -> None:
        """Move mouse to position with human-like movement.

        Args:
            x: Target x coordinate.
            y: Target y coordinate.
            duration: Movement duration in seconds. Auto-calculated if None.
        """
        start = await self.get_current_position()
        end = (float(x), float(y))

        # Calculate distance
        distance = math.sqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2)

        # Calculate duration based on distance if not provided
        if duration is None:
            # ~200-400ms per 500 pixels
            duration = (distance / 500) * random.uniform(0.2, 0.4) / self.speed

        # Generate path points
        num_points = max(10, int(distance / 10))  # 1 point per 10 pixels minimum
        control_points = generate_control_points(start, end, self.deviation)
        path = bezier_curve(start, control_points[0], control_points[1], end, num_points)
        path = add_noise(path, self.noise)

        # Calculate delays
        delays = calculate_delays(num_points, duration)

        # Execute movement
        for i, (px, py) in enumerate(path):
            await self.page.mouse.move(px, py)
            self._current_pos = (px, py)
            if i < len(delays):
                await asyncio.sleep(delays[i])

    async def click(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        button: str = "left",
        click_count: int = 1,
    ) -> None:
        """Click at position with human-like movement.

        Args:
            x: X coordinate. Uses current position if None.
            y: Y coordinate. Uses current position if None.
            button: Mouse button ('left', 'right', 'middle').
            click_count: Number of clicks.
        """
        if x is not None and y is not None:
            await self.move_to(x, y)

        # Small pause before click
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Click with slight position variation
        pos = await self.get_current_position()
        click_x = pos[0] + random.uniform(-1, 1)
        click_y = pos[1] + random.uniform(-1, 1)

        await self.page.mouse.click(click_x, click_y, button=button, click_count=click_count)

        # Small pause after click
        await asyncio.sleep(random.uniform(0.05, 0.1))

    async def click_element(
        self,
        selector: str,
        button: str = "left",
        timeout: int = 5000,
    ) -> bool:
        """Click on an element with human-like movement.

        Args:
            selector: Element selector.
            button: Mouse button.
            timeout: Wait timeout in milliseconds.

        Returns:
            True if click succeeded.
        """
        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout)
            if element:
                box = await element.bounding_box()
                if box:
                    # Click somewhere within the element, not exactly center
                    x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                    y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
                    await self.click(x, y, button=button)
                    return True
        except Exception:
            pass
        return False

    async def hover(
        self,
        x: float,
        y: float,
        duration: float = 0.5,
    ) -> None:
        """Hover over a position.

        Args:
            x: X coordinate.
            y: Y coordinate.
            duration: How long to hover.
        """
        await self.move_to(x, y)
        await asyncio.sleep(duration * random.uniform(0.8, 1.2))

    async def random_movement(self) -> None:
        """Make a small random mouse movement."""
        pos = await self.get_current_position()
        dx = random.uniform(-100, 100)
        dy = random.uniform(-50, 50)
        await self.move_to(pos[0] + dx, pos[1] + dy)

    async def scroll(
        self,
        amount: int = 300,
        smooth: bool = True,
    ) -> None:
        """Scroll with human-like behavior.

        Args:
            amount: Scroll amount in pixels (positive = down).
            smooth: Whether to scroll smoothly.
        """
        if smooth:
            # Break into smaller scrolls
            num_scrolls = random.randint(3, 6)
            for _ in range(num_scrolls):
                scroll_amount = amount // num_scrolls + random.randint(-20, 20)
                await self.page.mouse.wheel(0, scroll_amount)
                await asyncio.sleep(random.uniform(0.05, 0.15))
        else:
            await self.page.mouse.wheel(0, amount)

        # Pause after scrolling
        await asyncio.sleep(random.uniform(0.2, 0.5))
