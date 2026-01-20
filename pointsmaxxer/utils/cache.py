from __future__ import annotations

"""Response caching for PointsMaxxer scrapers."""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from diskcache import Cache


class ResponseCache:
    """Caches scraper responses to disk."""

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        default_ttl_hours: int = 6,
        max_size_gb: float = 1.0,
    ):
        """Initialize response cache.

        Args:
            cache_dir: Directory for cache. Defaults to ~/.pointsmaxxer/cache
            default_ttl_hours: Default cache TTL in hours.
            max_size_gb: Maximum cache size in gigabytes.
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".pointsmaxxer" / "cache"

        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = cache_dir
        self.default_ttl = default_ttl_hours * 3600  # Convert to seconds
        self.max_size = int(max_size_gb * 1024 * 1024 * 1024)  # Convert to bytes

        self._cache = Cache(str(cache_dir), size_limit=self.max_size)

    def _make_key(self, *args, **kwargs) -> str:
        """Generate a cache key from arguments.

        Args:
            *args: Positional arguments to hash.
            **kwargs: Keyword arguments to hash.

        Returns:
            Cache key string.
        """
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()[:32]

    def get(
        self,
        key: str,
        max_age_hours: Optional[int] = None,
    ) -> Optional[Any]:
        """Get cached value.

        Args:
            key: Cache key.
            max_age_hours: Maximum age in hours. Uses default if None.

        Returns:
            Cached value or None if not found/expired.
        """
        try:
            data = self._cache.get(key)
            if data is None:
                return None

            # Check age if specified
            if max_age_hours is not None:
                cached_at = data.get("_cached_at")
                if cached_at:
                    cached_time = datetime.fromisoformat(cached_at)
                    max_age = timedelta(hours=max_age_hours)
                    if datetime.now() - cached_time > max_age:
                        return None

            return data.get("value")
        except Exception:
            return None

    def set(
        self,
        key: str,
        value: Any,
        ttl_hours: Optional[int] = None,
    ) -> None:
        """Set cached value.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl_hours: TTL in hours. Uses default if None.
        """
        ttl = (ttl_hours * 3600) if ttl_hours else self.default_ttl

        data = {
            "value": value,
            "_cached_at": datetime.now().isoformat(),
        }

        self._cache.set(key, data, expire=ttl)

    def delete(self, key: str) -> bool:
        """Delete cached value.

        Args:
            key: Cache key.

        Returns:
            True if key existed and was deleted.
        """
        return self._cache.delete(key)

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    def get_or_fetch(
        self,
        key: str,
        fetch_func,
        ttl_hours: Optional[int] = None,
        max_age_hours: Optional[int] = None,
    ) -> Any:
        """Get cached value or fetch and cache.

        Args:
            key: Cache key.
            fetch_func: Function to call if not cached.
            ttl_hours: TTL for new cache entry.
            max_age_hours: Max age for existing cache entry.

        Returns:
            Cached or fetched value.
        """
        cached = self.get(key, max_age_hours=max_age_hours)
        if cached is not None:
            return cached

        value = fetch_func()
        self.set(key, value, ttl_hours=ttl_hours)
        return value

    async def get_or_fetch_async(
        self,
        key: str,
        fetch_func,
        ttl_hours: Optional[int] = None,
        max_age_hours: Optional[int] = None,
    ) -> Any:
        """Async version of get_or_fetch.

        Args:
            key: Cache key.
            fetch_func: Async function to call if not cached.
            ttl_hours: TTL for new cache entry.
            max_age_hours: Max age for existing cache entry.

        Returns:
            Cached or fetched value.
        """
        cached = self.get(key, max_age_hours=max_age_hours)
        if cached is not None:
            return cached

        value = await fetch_func()
        self.set(key, value, ttl_hours=ttl_hours)
        return value

    def cache_search(
        self,
        origin: str,
        destination: str,
        date: str,
        cabin: str,
        program: str,
    ) -> Optional[dict]:
        """Get cached search results.

        Args:
            origin: Origin airport.
            destination: Destination airport.
            date: Date string (YYYY-MM-DD).
            cabin: Cabin class.
            program: Program code.

        Returns:
            Cached search results or None.
        """
        key = self._make_key(
            "search",
            origin=origin,
            destination=destination,
            date=date,
            cabin=cabin,
            program=program,
        )
        return self.get(key)

    def set_search(
        self,
        origin: str,
        destination: str,
        date: str,
        cabin: str,
        program: str,
        results: dict,
        ttl_hours: Optional[int] = None,
    ) -> None:
        """Cache search results.

        Args:
            origin: Origin airport.
            destination: Destination airport.
            date: Date string (YYYY-MM-DD).
            cabin: Cabin class.
            program: Program code.
            results: Search results to cache.
            ttl_hours: Cache TTL in hours.
        """
        key = self._make_key(
            "search",
            origin=origin,
            destination=destination,
            date=date,
            cabin=cabin,
            program=program,
        )
        self.set(key, results, ttl_hours=ttl_hours)

    def cache_cash_price(
        self,
        origin: str,
        destination: str,
        date: str,
        cabin: str,
    ) -> Optional[float]:
        """Get cached cash price.

        Args:
            origin: Origin airport.
            destination: Destination airport.
            date: Date string (YYYY-MM-DD).
            cabin: Cabin class.

        Returns:
            Cached price or None.
        """
        key = self._make_key(
            "cash_price",
            origin=origin,
            destination=destination,
            date=date,
            cabin=cabin,
        )
        return self.get(key, max_age_hours=24)  # Cash prices valid for 24h

    def set_cash_price(
        self,
        origin: str,
        destination: str,
        date: str,
        cabin: str,
        price: float,
    ) -> None:
        """Cache cash price.

        Args:
            origin: Origin airport.
            destination: Destination airport.
            date: Date string (YYYY-MM-DD).
            cabin: Cabin class.
            price: Cash price.
        """
        key = self._make_key(
            "cash_price",
            origin=origin,
            destination=destination,
            date=date,
            cabin=cabin,
        )
        self.set(key, price, ttl_hours=24)

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache stats.
        """
        return {
            "size_bytes": self._cache.volume(),
            "max_size_bytes": self.max_size,
            "utilization_percent": (self._cache.volume() / self.max_size) * 100,
        }

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._cache.close()

    def close(self) -> None:
        """Close the cache."""
        self._cache.close()
