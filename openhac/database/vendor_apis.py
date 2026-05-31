"""
Vendor API Integration for Live Component Queries

Implements rate-limited access to Digi-Key and Mouser APIs for:
- Real-time stock checks
- Live pricing data
- Datasheet URLs
- Part detail verification

Rate Limits (enforced):
    Digi-Key: 1000 requests/day, no per-minute limit mentioned
    Mouser: 30 requests/minute

Usage:
    from openhac.database.vendor_apis import DigiKeyAPI, MouserAPI

    dk = DigiKeyAPI(client_id="xxx", client_secret="xxx")
    part_info = dk.search("STM32F405RGT6")

    mouser = MouserAPI(api_key="xxx")
    stock = mouser.get_stock("C7862")

API Keys Required:
    Digi-Key: https://developer.digikey.com/ (free, requires registration)
    Mouser: https://www.mouser.com/api-hub/ (free, requires registration)
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from openhac.version_info import user_agent

logger = logging.getLogger("openhac.vendor_apis")

# Cache TTL in seconds (default: 24 hours for API responses)
DEFAULT_CACHE_TTL = 86400
_default_cache_db = os.path.join(os.path.dirname(__file__), "api_cache.db")
CACHE_DB_PATH = os.environ.get("OPENHAC_CACHE_DB", _default_cache_db)


class APICache:
    """SQLite-based cache for vendor API responses.

    Caches API responses to avoid hitting rate limits on repeated lookups.
    Each entry has a TTL (time-to-live) after which it's considered stale.

    Cache keys are hashed MPN + vendor name to create unique lookups.
    """

    def __init__(self, db_path: Optional[str] = None, ttl_seconds: int = DEFAULT_CACHE_TTL):
        import threading
        self.db_path = db_path or CACHE_DB_PATH
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._init_db()
        self._hits = 0
        self._misses = 0

    def _init_db(self):
        """Initialize cache table."""
        import sqlite3
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    vendor TEXT NOT NULL,
                    mpn TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL
                )
            """)
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_expires ON api_cache(expires_at)
            """)
            self.conn.commit()

    def _make_key(self, vendor: str, mpn: str) -> str:
        """Create cache key from vendor + MPN."""
        key = f"{vendor}:{mpn.upper().strip()}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    def get_pinout(self, vendor: str, mpn: str) -> Optional[list[dict]]:
        """Get cached pinout data for a component.
        
        Returns list of pin dicts if available, None otherwise.
        Each pin dict has: num, name, type
        """
        key = self._make_key(f"{vendor}:pinout", mpn)
        
        with self._lock:
            cursor = self.conn.execute(
                "SELECT response_json FROM api_cache WHERE cache_key = ? AND expires_at > datetime('now')",
                (key,)
            )
            row = cursor.fetchone()
        
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None
        return None
    
    def set_pinout(self, vendor: str, mpn: str, pinout: list[dict]):
        """Cache pinout data for a component."""
        import sqlite3
        key = self._make_key(f"{vendor}:pinout", mpn)
        
        # Default TTL: 30 days for pinout (doesn't change often)
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO api_cache 
                   (cache_key, vendor, mpn, response_json, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, f"{vendor}:pinout", mpn, json.dumps(pinout), expires)
            )
            self.conn.commit()

    def get(self, vendor: str, mpn: str) -> Optional[dict]:
        """Get cached response if not expired."""
        import sqlite3
        key = self._make_key(vendor, mpn)

        with self._lock:
            cursor = self.conn.execute(
                "SELECT response_json FROM api_cache WHERE cache_key = ? AND expires_at > datetime('now')",
                (key,)
            )
            row = cursor.fetchone()

        if row:
            self._hits += 1
            logger.debug(f"Cache HIT for {vendor}:{mpn}")
            return json.loads(row[0])

        self._misses += 1
        logger.debug(f"Cache MISS for {vendor}:{mpn}")
        return None

    def set(self, vendor: str, mpn: str, response: dict, ttl: Optional[int] = None):
        """Cache an API response."""
        import sqlite3
        if ttl is None:
            ttl = self.ttl

        key = self._make_key(vendor, mpn)
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO api_cache
                   (cache_key, vendor, mpn, response_json, expires_at)
                   VALUES (?, ?, ?, ?, datetime('now', '+' || ? || ' seconds'))""",
                (key, vendor, mpn.upper().strip(), json.dumps(response), ttl)
            )
            self.conn.commit()
        logger.debug(f"Cached {vendor}:{mpn} (TTL={ttl}s)")

    def clear_expired(self):
        """Remove expired cache entries."""
        with self._lock:
            cursor = self.conn.execute("DELETE FROM api_cache WHERE expires_at < datetime('now')")
            self.conn.commit()
            return cursor.rowcount

    def set_blocked(self, vendor: str, duration_seconds: int = 900):
        """Mark a vendor as blocked (e.g. after a 429 or 403)."""
        key = f"BLOCK:{vendor}"
        expires = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO api_cache 
                   (cache_key, vendor, mpn, response_json, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, "SYSTEM", vendor, json.dumps({"status": "blocked"}), expires)
            )
            self.conn.commit()
        logger.warning(f"Vendor {vendor} is now BLOCKED for {duration_seconds}s to prevent further rate limiting.")

    def is_blocked(self, vendor: str) -> bool:
        """Check if a vendor is currently in a cool-off period."""
        key = f"BLOCK:{vendor}"
        with self._lock:
            cursor = self.conn.execute(
                "SELECT 1 FROM api_cache WHERE cache_key = ? AND expires_at > datetime('now')",
                (key,)
            )
            return cursor.fetchone() is not None

    def clear_all(self):
        """Clear entire cache."""
        with self._lock:
            self.conn.execute("DELETE FROM api_cache")
            self.conn.commit()

    def get_stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            cursor = self.conn.execute("SELECT COUNT(*) FROM api_cache WHERE expires_at > datetime('now')")
            valid_entries = cursor.fetchone()[0]

            cursor = self.conn.execute("SELECT COUNT(*) FROM api_cache")
            total_entries = cursor.fetchone()[0]

        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "valid_entries": valid_entries,
            "total_entries": total_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_percent": round(hit_rate, 2),
        }


# Global cache instance
_api_cache = None


def get_api_cache() -> APICache:
    """Get or create global API cache instance."""
    global _api_cache
    if _api_cache is None:
        _api_cache = APICache()
    return _api_cache


@dataclass
class PartInfo:
    """Standardized part information from any vendor API."""
    mpn: str
    manufacturer: str
    supplier_sku: str
    description: str
    stock: int
    price_breaks: list[dict]  # [{"quantity": 1, "price": 1.23}, ...]
    datasheet_url: Optional[str]
    product_url: Optional[str]
    category: str
    package: str
    rohs: bool
    lead_time_days: Optional[int]
    last_updated: datetime
    # V7 fields - additional data for complete component info
    thermal_data: Optional[dict] = None  # {"r_theta_ja": 45.0, "max_tj": 125}
    package_dimensions: Optional[dict] = None  # {"length": 5.0, "width": 5.0, "height": 1.0}
    lifecycle_status: Optional[str] = None  # Active, NRND, Obsolete
    compliance_flags: Optional[list] = None  # ["RoHS", "REACH"]
    pinout: Optional[list] = None  # [{"num": "1", "name": "VIN", "type": "power"}, ...]
    alternative_mpns: Optional[list] = None  # ["MPN1", "MPN2"]
    manufacturer_info: Optional[dict] = None  # {"location": "CN", "certs": ["ISO9001"]}
    model_3d_url: Optional[str] = None  # Remote URL or UUID for 3D model


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, max_calls: int, period_seconds: int):
        import threading
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls: list[float] = []
        self._lock = threading.Lock()

    def acquire(self):
        """Block until a call slot is available."""
        with self._lock:
            now = time.time()
    
            # Remove old calls outside the window
            cutoff = now - self.period
            self.calls = [c for c in self.calls if c > cutoff]
    
            # Check if we're at the limit
            if len(self.calls) >= self.max_calls:
                # Calculate wait time
                oldest = min(self.calls)
                wait = (oldest + self.period) - now
                if wait > 0:
                    logger.debug(f"Rate limit hit, waiting {wait:.1f}s")
                    time.sleep(wait)
    
            self.calls.append(time.time())


def _mouser_search_results_parts(data: Optional[dict]) -> list:
    """Normalize Mouser JSON: ``SearchResults`` may be null on errors or invalid keys."""
    if not isinstance(data, dict):
        return []
    sr = data.get("SearchResults")
    if not isinstance(sr, dict):
        return []
    parts = sr.get("Parts")
    return parts if isinstance(parts, list) else []


def _tme_calculate_signature(method: str, request_url: str, form_pairs: list[tuple[str, str]], secret: str) -> str:
    """TME ``ApiSignature`` per official reference client (``tme-dev/api-client-go``).

    ``signatureBase = method + "&" + urlQueryEscape(url) + "&" + urlQueryEscape(form.Encode())``
    where ``form`` includes all POST fields *except* ``ApiSignature``. Result is **base64**(HMAC-SHA1).
    """
    form_sorted = sorted(form_pairs, key=lambda kv: (kv[0], kv[1]))
    encoded_form = urllib.parse.urlencode(form_sorted, doseq=True)
    signature_base = "&".join(
        [
            method,
            urllib.parse.quote(request_url, safe=""),
            urllib.parse.quote(encoded_form, safe=""),
        ]
    )
    digest = hmac.new(secret.encode("utf-8"), signature_base.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _tme_response_product_list(data: Optional[dict]) -> list:
    if not isinstance(data, dict):
        return []
    block = data.get("Data")
    if not isinstance(block, dict):
        return []
    pl = block.get("ProductList")
    return pl if isinstance(pl, list) else []


class DigiKeyAPI:
    """Digi-Key API V4 Integration.

    Rate limit: 1000 calls per day (enforced by Digi-Key, we don't need to track)
    Auth: OAuth2 client credentials flow
    """

    API_BASE = "https://api.digikey.com"

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or os.environ.get("DIGIKEY_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("DIGIKEY_CLIENT_SECRET")
        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        base = (os.environ.get("DIGIKEY_API_BASE") or "").strip().rstrip("/")
        if base:
            self.api_base = base
        elif (os.environ.get("DIGIKEY_USE_SANDBOX") or "").strip().lower() in ("1", "true", "yes", "on"):
            self.api_base = "https://sandbox-api.digikey.com"
        else:
            self.api_base = self.API_BASE

    def _get_token(self) -> str:
        """Get or refresh OAuth2 access token."""
        if self._access_token and self._token_expires and datetime.now(timezone.utc) < self._token_expires:
            return self._access_token

        import urllib.request
        import urllib.parse

        if not self.client_id or not self.client_secret:
            raise ValueError("Digi-Key API credentials not configured. Set DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET")

        url = f"{self.api_base}/v1/oauth2/token"
        data = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }).encode()

        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": user_agent(),
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                token_data = json.loads(resp.read().decode())
                self._access_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)
                self._token_expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
                return self._access_token
        except Exception as e:
            logger.error(f"Failed to get Digi-Key access token: {e}")
            raise

    def search(self, keyword: str, limit: int = 10, use_cache: bool = True) -> list[PartInfo]:
        """Search for parts by keyword.

        Args:
            keyword: MPN or search term
            limit: Max results
            use_cache: Check local cache first (default True)
        """
        import urllib.request

        # Check block status
        cache = get_api_cache()
        if cache.is_blocked("digikey"):
            logger.debug("Digi-Key is in cool-off period, skipping search.")
            return []

        # Check cache first
        if use_cache:
            cached = cache.get("digikey", keyword)
            if cached:
                products = cached.get("products", [])
                logger.info(f"Using cached Digi-Key data for {keyword}")
                return [self._parse_product(p) for p in products]

        token = self._get_token()
        url = f"{self.api_base}/products/v4/search/keyword"

        payload = json.dumps({
            "keywords": keyword,
            "limit": limit,
            "offset": 0,
        }).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-DIGIKEY-Client-Id": self.client_id,
            "User-Agent": user_agent(),
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                products = data.get("products", [])

                # Cache the response
                if use_cache and products:
                    cache = get_api_cache()
                    cache.set("digikey", keyword, data)
                    logger.debug(f"Cached Digi-Key response for {keyword}")

                return [self._parse_product(p) for p in products]
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                get_api_cache().set_blocked("digikey")
            logger.warning(f"Digi-Key search failed: {e}")
            return []
        except Exception as e:
            logger.warning(f"Digi-Key search failed: {e}")
            return []

    def get_part(self, digikey_part_number: str, use_cache: bool = True) -> Optional[PartInfo]:
        """Get specific part details by Digi-Key part number."""
        import urllib.request

        # Check cache first
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("digikey", digikey_part_number)
            if cached:
                logger.info(f"Using cached Digi-Key data for {digikey_part_number}")
                return self._parse_product(cached)

        token = self._get_token()
        url = f"{self.api_base}/products/v4/search/digikeypartnumber/{digikey_part_number}"

        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "User-Agent": user_agent(),
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())

                # Cache the response
                if use_cache:
                    cache = get_api_cache()
                    cache.set("digikey", digikey_part_number, data)
                    logger.debug(f"Cached Digi-Key response for {digikey_part_number}")

                return self._parse_product(data)
        except Exception as e:
            logger.warning(f"Digi-Key part lookup failed: {e}")
            return None

    def _parse_product(self, product: dict) -> PartInfo:
        """Parse Digi-Key product response into PartInfo."""
        pricing = product.get("standard_pricing", [])
        price_breaks = [
            {"quantity": p.get("break_quantity", 0), "price": p.get("unit_price", 0)}
            for p in pricing
        ]
        
        # Extract package dimensions if available
        pkg_dims = None
        if "package_dimensions" in product:
            pd = product["package_dimensions"]
            pkg_dims = {
                "length": pd.get("length_mm"),
                "width": pd.get("width_mm"),
                "height": pd.get("height_mm"),
            }
        
        # Extract thermal data if available
        thermal = None
        if "thermal" in product:
            th = product["thermal"]
            thermal = {
                "r_theta_ja": th.get("r_theta_ja"),
                "max_tj": th.get("max_junction_temp"),
                "max_power": th.get("max_power"),
            }
        
        # Extract compliance flags
        compliance = []
        if product.get("rohs_status") == "RoHS Compliant":
            compliance.append("RoHS")
        if product.get("lead_free"):
            compliance.append("LeadFree")
        
        # Extract pinout if available
        pinout = None
        if "pinout" in product:
            pinout = [
                {"num": p.get("pin_number", str(i+1)), "name": p.get("signal_name", ""), "type": p.get("pin_type", "bidirectional")}
                for i, p in enumerate(product["pinout"])
            ]

        return PartInfo(
            mpn=product.get("manufacturer_part_number", ""),
            manufacturer=product.get("manufacturer", {}).get("name", ""),
            supplier_sku=product.get("digi_key_part_number", ""),
            description=product.get("product_description", ""),
            stock=product.get("quantity_available", 0),
            price_breaks=price_breaks,
            datasheet_url=product.get("primary_datasheet_url"),
            product_url=product.get("product_url"),
            category=product.get("category", {}).get("name", ""),
            package=product.get("package_type", {}).get("name", ""),
            rohs=product.get("rohs_status") == "RoHS Compliant",
            lead_time_days=product.get("factory_stock_lead_days"),
            last_updated=datetime.now(timezone.utc),
            # V7 fields
            thermal_data=thermal,
            package_dimensions=pkg_dims,
            lifecycle_status=product.get("lifecycle_status"),
            compliance_flags=compliance if compliance else None,
            pinout=pinout,
            alternative_mpns=product.get("alternate_packaging"),
            manufacturer_info={"certs": product.get("standards"), "location": product.get("manufacturer", {}).get("region")} if product.get("manufacturer") else None,
        )


class MouserAPI:
    """Mouser Search API Integration.

    Rate limit: 30 requests per minute (enforced locally)
    Auth: Simple API key
    """

    API_BASE = "https://api.mouser.com/api/v1"
    RATE_LIMIT = 30  # per minute

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("MOUSER_API_KEY")
        self._rate_limiter = RateLimiter(max_calls=30, period_seconds=60)

    def search(self, keyword: str, limit: int = 10, use_cache: bool = True) -> list[PartInfo]:
        """Search for parts by keyword.

        Args:
            keyword: MPN or part number
            limit: Max results
            use_cache: Check local cache first (default True)
        """
        import urllib.request

        # Check block status
        cache = get_api_cache()
        if cache.is_blocked("mouser"):
            logger.debug("Mouser is in cool-off period, skipping search.")
            return []

        # Check cache first
        if use_cache:
            cached = cache.get("mouser", keyword)
            if cached:
                parts = _mouser_search_results_parts(cached)
                logger.info(f"Using cached Mouser data for {keyword}")
                return [self._parse_part(p) for p in parts[:limit]]

        if not self.api_key:
            raise ValueError("Mouser API key not configured. Set MOUSER_API_KEY")

        self._rate_limiter.acquire()

        url = f"{self.API_BASE}/search/partnumber?apiKey={self.api_key}"
        payload = json.dumps({
            "SearchByPartRequest": {
                "mouserPartNumber": keyword,
                "partSearchOptions": "BeginsWith",
            }
        }).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "User-Agent": user_agent(),
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                parts = _mouser_search_results_parts(data)

                # Cache the response
                if use_cache and parts:
                    cache = get_api_cache()
                    cache.set("mouser", keyword, data)
                    logger.debug(f"Cached Mouser response for {keyword}")

                return [self._parse_part(p) for p in parts[:limit]]
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                get_api_cache().set_blocked("mouser")
            logger.warning(f"Mouser search failed: {e}")
            return []
        except Exception as e:
            logger.warning(f"Mouser search failed: {e}")
            return []

    def search_keyword(self, keyword: str, limit: int = 10, use_cache: bool = True) -> list[PartInfo]:
        """Search by keyword (not part number).

        Args:
            keyword: Search term
            limit: Max results
            use_cache: Check local cache first (default True)
        """
        import urllib.request

        # Check cache first
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("mouser_keyword", keyword)
            if cached:
                parts = _mouser_search_results_parts(cached)
                logger.info(f"Using cached Mouser keyword data for {keyword}")
                return [self._parse_part(p) for p in parts]

        if not self.api_key:
            raise ValueError("Mouser API key not configured. Set MOUSER_API_KEY")

        self._rate_limiter.acquire()

        url = f"{self.API_BASE}/search/keyword?apiKey={self.api_key}"
        payload = json.dumps({
            "SearchByKeywordRequest": {
                "keyword": keyword,
                "records": limit,
                "startingRecord": 0,
            }
        }).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "Content-Type": "application/json",
            "User-Agent": user_agent(),
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                parts = _mouser_search_results_parts(data)

                # Cache the response
                if use_cache and parts:
                    cache = get_api_cache()
                    cache.set("mouser_keyword", keyword, data)
                    logger.debug(f"Cached Mouser keyword response for {keyword}")

                return [self._parse_part(p) for p in parts]
        except Exception as e:
            logger.warning(f"Mouser keyword search failed: {e}")
            return []

    def get_part(self, mouser_part_number: str, use_cache: bool = True) -> Optional[PartInfo]:
        """Get specific part details.

        Args:
            mouser_part_number: Mouser SKU
            use_cache: Check local cache first (default True)
        """
        # Check cache first
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("mouser", mouser_part_number)
            if cached:
                parts = _mouser_search_results_parts(cached)
                if parts:
                    logger.info(f"Using cached Mouser data for {mouser_part_number}")
                    return self._parse_part(parts[0])

        results = self.search(mouser_part_number, limit=1, use_cache=use_cache)
        return results[0] if results else None

    def _parse_part(self, part: dict) -> PartInfo:
        """Parse Mouser part response into PartInfo."""
        pricing = part.get("PriceBreaks", [])
        price_breaks = [
            {"quantity": p.get("Quantity", 0), "price": p.get("Price", "").replace("$", "")}
            for p in pricing
        ]

        availability = part.get("Availability", "")
        stock = 0
        if "In Stock" in availability:
            try:
                stock = int(availability.split()[0])
            except (ValueError, IndexError):
                stock = 1000  # Assume in stock if exact number not parseable

        # Build compliance flags
        compliance = []
        if "RoHS" in part.get("ROHSStatus", ""):
            compliance.append("RoHS")

        return PartInfo(
            mpn=part.get("ManufacturerPartNumber", ""),
            manufacturer=part.get("Manufacturer", ""),
            supplier_sku=part.get("MouserPartNumber", ""),
            description=part.get("Description", ""),
            stock=stock,
            price_breaks=price_breaks,
            datasheet_url=part.get("DataSheetUrl"),
            product_url=part.get("ProductDetailUrl"),
            category=part.get("Category", ""),
            package="",  # Mouser doesn't consistently provide this
            rohs="RoHS" in part.get("ROHSStatus", ""),
            lead_time_days=None,
            last_updated=datetime.now(timezone.utc),
            # V7 fields - Mouser provides limited data
            thermal_data=None,  # Not available from Mouser
            package_dimensions=None,  # Not available from Mouser
            lifecycle_status=None,  # Not available from Mouser
            compliance_flags=compliance if compliance else None,
            pinout=None,  # Not available from Mouser
            alternative_mpns=part.get("AlternatePackaging"),
            manufacturer_info=None,  # Not available from Mouser
        )


class JLCPCBAPI:
    """Resolve LCSC / JLC assembly SKUs (Cxxxxx).

    **Primary (no API key):** JLC's own PCBA parts search endpoint — the same JSON API their
    assembly UI uses::

        POST https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList/v2

    **Partner program:** ``https://api.jlcpcb.com/`` is the *developer portal* for approved
    apps (App ID + Access Key). REST paths are documented **after login** there; OpenHaC does
    not call that OAuth/partner stack yet.

    **Legacy:** ``GET .../api/component/search?sku=&key=`` (``JLCPCB_API_KEY``) — often **404**.

    **Fallback:** public **jlcsearch** mirror (``sync_jlc``): ``https://jlcsearch.tscircuit.com``.

    Env:
        ``JLCPCB_SMT_SEARCH_URL`` — override POST URL for the SMT component list (default above).
        ``JLCPCB_DISABLE_SMT`` — if ``1``, skip the SMT POST (try legacy + jlcsearch only).
        ``JLCPCB_API_KEY`` / ``JLCPCB_API_BASE`` — legacy GET search only.
        ``JLCPCB_DISABLE_JLCSEARCH`` — if ``1``, do not use jlcsearch.
    """

    API_BASE = "https://jlcpcb.com/api"
    JLCSEARCH_BASE = "https://jlcsearch.tscircuit.com"
    # Public JSON API used by jlcpcb.com PCBA component picker (see also @jlcpcb/core).
    DEFAULT_SMT_SEARCH_URL = (
        "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList/v2"
    )
    RATE_LIMIT = 1  # 1 request per second

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("JLCPCB_API_KEY")
        self._limiter = RateLimiter(max_calls=1, period_seconds=1)

    def _legacy_api_base(self) -> str:
        raw = (os.environ.get("JLCPCB_API_BASE") or self.API_BASE).strip()
        return raw.rstrip("/")

    def _smt_search_url(self) -> str:
        return (os.environ.get("JLCPCB_SMT_SEARCH_URL") or self.DEFAULT_SMT_SEARCH_URL).strip()

    def search_by_sku(self, sku: str, use_cache: bool = True) -> Optional[PartInfo]:
        """Search by JLCPCB / LCSC SKU (C132150 format)."""
        from openhac.version_info import user_agent

        if not sku.startswith("C") or not sku[1:].isdigit():
            logger.debug(f"Invalid JLCPCB SKU format: {sku}")
            return None

        if use_cache:
            cache = get_api_cache()
            cached = cache.get("jlcpcb", sku)
            if cached:
                logger.info(f"Using cached JLCPCB data for {sku}")
                blob = cached.get("data", {})
                src = cached.get("source") or "jlcpcb"
                if src == "jlcsearch":
                    return self._parse_jlcsearch_item(blob)
                if src == "smt":
                    return self._parse_smt_list_item(blob)
                return self._parse_product(blob)

        disable_jlcsearch = (os.environ.get("JLCPCB_DISABLE_JLCSEARCH") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        disable_smt = (os.environ.get("JLCPCB_DISABLE_SMT") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )

        part: Optional[PartInfo] = None
        if not disable_smt:
            part = self._search_smt_component_list(sku, use_cache, user_agent())
        if part is None and self.api_key:
            part = self._search_legacy_http(sku, use_cache)
        if part is None and not disable_jlcsearch:
            part = self._search_jlcsearch(sku, use_cache, user_agent())

        return part

    def _search_smt_component_list(self, sku: str, use_cache: bool, ua: str) -> Optional[PartInfo]:
        """POST search used by JLC PCBA parts UI; typically works without an API key."""
        self._limiter.acquire()
        url = self._smt_search_url()
        body = json.dumps(
            {
                "currentPage": 1,
                "pageSize": 20,
                "keyword": sku,
                "searchType": 2,
            }
        ).encode("utf-8")
        try:
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": ua,
                },
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            logger.debug("JLCPCB SMT list API failed for %s: %s", sku, e)
            return None

        if data.get("code") != 200:
            logger.debug("JLCPCB SMT list API code=%s for %s", data.get("code"), sku)
            return None

        rows = (data.get("data") or {}).get("componentPageInfo") or {}
        lst = rows.get("list") or []
        want = sku.strip().upper()
        hit: Optional[dict] = None
        for row in lst:
            code = str(row.get("componentCode") or "").strip().upper()
            if code == want:
                hit = row
                break
        if hit is None and lst:
            # Keyword search can return unrelated rows; do not accept wrong LCSC code.
            logger.debug("JLCPCB SMT list: no row with componentCode=%s", want)
            return None

        if hit is None:
            return None

        if use_cache:
            cache = get_api_cache()
            cache.set("jlcpcb", sku, {"source": "smt", "data": hit})
            logger.debug("Cached JLCPCB SMT response for %s", sku)

        logger.info("JLCPCB resolved %s via SMT component list API", sku)
        return self._parse_smt_list_item(hit)

    def _parse_smt_list_item(self, row: dict) -> PartInfo:
        """Map ``selectSmtComponentList`` row to :class:`PartInfo`."""
        sku = str(row.get("componentCode") or "").strip()
        mpn = str(row.get("componentModelEn") or "").strip()
        mfr = str(row.get("componentBrandEn") or "").strip()
        desc_bits = [
            str(row.get("componentTypeEn") or "").strip(),
            str(row.get("erpComponentName") or "").strip(),
        ]
        description = " — ".join(b for b in desc_bits if b) or mpn or sku
        package = str(row.get("componentSpecificationEn") or "").strip()
        try:
            stock = int(row.get("stockCount") or 0)
        except (TypeError, ValueError):
            stock = 0

        price_breaks: list[dict] = []
        for pr in row.get("componentPrices") or []:
            try:
                q = int(pr.get("startNumber") or 0)
                p = float(pr.get("productPrice"))
                if q > 0:
                    price_breaks.append({"quantity": q, "price": p})
            except (TypeError, ValueError):
                continue

        ds = (row.get("dataManualUrl") or row.get("lcscGoodsUrl") or "").strip() or None
        purl = (row.get("lcscGoodsUrl") or "").strip()
        if not purl and sku:
            purl = f"https://jlcpcb.com/partdetail/{sku}"

        return PartInfo(
            mpn=mpn or sku,
            manufacturer=mfr,
            supplier_sku=sku,
            description=description,
            stock=stock,
            price_breaks=price_breaks,
            datasheet_url=ds,
            product_url=purl,
            category=str(row.get("componentTypeEn") or "").strip(),
            package=package,
            rohs=True,
            lead_time_days=None,
            last_updated=datetime.now(timezone.utc),
            thermal_data=None,
            package_dimensions=None,
            lifecycle_status=None,
            compliance_flags=["RoHS"],
            pinout=None,
            alternative_mpns=None,
            manufacturer_info=None,
        )

    def _search_legacy_http(self, sku: str, use_cache: bool) -> Optional[PartInfo]:
        """Old jlcpcb.com JSON API (often 404 now)."""
        if not self.api_key:
            return None
        self._limiter.acquire()
        base = self._legacy_api_base()
        url = f"{base}/component/search?sku={urllib.parse.quote(sku)}&key={urllib.parse.quote(self.api_key)}"
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            if data.get("code") != 200:
                logger.warning(f"JLCPCB API error: {data.get('message')}")
                return None
            product = data.get("data", {}) or {}
            if not product:
                return None
            if use_cache:
                cache = get_api_cache()
                cache.set("jlcpcb", sku, {"source": "jlcpcb", "data": product})
                logger.debug(f"Cached JLCPCB legacy response for {sku}")
            return self._parse_product(product)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                logger.debug("JLCPCB legacy endpoint HTTP %s for %s", e.code, sku)
            else:
                logger.warning(f"JLCPCB lookup failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"JLCPCB lookup failed: {e}")
            return None

    def _search_jlcsearch(self, sku: str, use_cache: bool, ua: str) -> Optional[PartInfo]:
        """Match LCSC id via jlcsearch (no API key)."""
        try:
            lcsc_id = int(sku[1:])
        except ValueError:
            return None

        self._limiter.acquire()
        q = urllib.parse.quote(str(lcsc_id))
        url = f"{self.JLCSEARCH_BASE}/components/list.json?search={q}&limit=80&full=true"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            logger.warning(f"jlcsearch lookup failed for {sku}: {e}")
            return None

        items = data.get("components") or []
        hit = None
        for it in items:
            if it.get("lcsc") == lcsc_id:
                hit = it
                break
        if hit is None:
            logger.debug("jlcsearch: no exact LCSC match for %s", sku)
            return None

        if use_cache:
            cache = get_api_cache()
            cache.set("jlcpcb", sku, {"source": "jlcsearch", "data": hit})
            logger.debug(f"Cached jlcsearch response for {sku}")

        logger.info("JLCPCB resolved %s via jlcsearch fallback", sku)
        return self._parse_jlcsearch_item(hit)

    def _parse_jlcsearch_item(self, item: dict) -> PartInfo:
        """Map jlcsearch component row to PartInfo."""
        lcsc = item.get("lcsc")
        sku = f"C{lcsc}" if lcsc is not None else ""
        mpn = str(item.get("mfr") or "").strip()
        description = str(item.get("description") or "").strip()
        package = str(item.get("package") or "").strip()
        try:
            stock = int(item.get("stock") or 0)
        except (TypeError, ValueError):
            stock = 0
        cat = (item.get("category") or item.get("subcategory") or "") or ""
        cat = str(cat).strip()

        price_breaks: list[dict] = []
        pr = item.get("price")
        try:
            if isinstance(pr, str) and pr.strip().startswith("["):
                for row in json.loads(pr):
                    q = row.get("qFrom")
                    p = row.get("price")
                    if q is not None and p is not None:
                        price_breaks.append({"quantity": int(q), "price": float(p)})
        except Exception:
            pass

        product_url = f"https://jlcpcb.com/partdetail/{sku}" if sku else ""
        return PartInfo(
            mpn=mpn or sku,
            manufacturer="",
            supplier_sku=sku,
            description=description,
            stock=stock,
            price_breaks=price_breaks,
            datasheet_url=None,
            product_url=product_url,
            category=cat,
            package=package,
            rohs=False,
            lead_time_days=None,
            last_updated=datetime.now(timezone.utc),
            thermal_data=None,
            package_dimensions=None,
            lifecycle_status=None,
            compliance_flags=None,
            pinout=None,
            alternative_mpns=None,
            manufacturer_info=None,
        )
    
    def _parse_product(self, product: dict) -> PartInfo:
        """Parse JLCPCB product response into PartInfo."""
        # JLCPCB provides: SKU, MPN, manufacturer, stock, price, specs
        specs = product.get("componentSpecification", {})
        
        # Extract pinout from specs if available
        pinout = None
        if "pinCount" in specs:
            pin_count = int(specs["pinCount"])
            pinout = [{"num": str(i), "name": str(i), "type": "bidirectional"} for i in range(1, pin_count + 1)]
        
        # Build compliance flags
        compliance = []
        if product.get("isRoHS"):
            compliance.append("RoHS")
        
        return PartInfo(
            mpn=product.get("componentCode", ""),  # e.g., "TPS63001DRCR"
            manufacturer=product.get("brandName", ""),
            supplier_sku=product.get("componentId", ""),  # e.g., "C132150"
            description=product.get("componentName", ""),
            stock=product.get("stockCount", 0),
            price_breaks=[],  # JLCPCB pricing requires separate endpoint
            datasheet_url=product.get("dataSheet"),
            product_url=f"https://jlcpcb.com/partdetail/{product.get('componentId', '')}",
            category=product.get("componentTypeEn", ""),
            package=product.get("package", ""),
            rohs=product.get("isRoHS", False),
            lead_time_days=None,  # Not directly provided
            last_updated=datetime.now(timezone.utc),
            # V7 fields
            thermal_data=None,  # Not directly provided
            package_dimensions=None,  # Would need to parse from specs
            lifecycle_status=product.get("componentStatus"),
            compliance_flags=compliance if compliance else None,
            pinout=pinout,
            alternative_mpns=None,
            manufacturer_info=None,
        )


def vendor_apis_configured() -> bool:
    """Return True if at least one vendor integration has credentials in the environment."""
    if (os.environ.get("DIGIKEY_CLIENT_ID") or "").strip() and (os.environ.get("DIGIKEY_CLIENT_SECRET") or "").strip():
        return True
    if (os.environ.get("MOUSER_API_KEY") or "").strip():
        return True
    if (os.environ.get("TME_API_TOKEN") or "").strip() and (os.environ.get("TME_API_SECRET") or "").strip():
        return True
    if (os.environ.get("JLCPCB_API_KEY") or "").strip():
        return True
    return False


def lookup_part_live(mpn: str, preferred_vendor: str = "auto", 
                     jlcpcb_sku: Optional[str] = None) -> Optional[PartInfo]:
    """Hybrid live lookup from multiple vendor APIs.
    
    Queries multiple APIs in order and merges data for the most complete PartInfo.
    Uses 1 req/sec rate limiting to prevent IP bans.
    
    Args:
        mpn: Manufacturer part number to search
        preferred_vendor: "digikey", "mouser", "tme", "jlcpcb", or "auto" (default)
        jlcpcb_sku: Optional JLCPCB SKU (Cxxxxx) for assembly sourcing
        
    Returns:
        PartInfo with merged data from all available APIs, or None if not found
    """
    results: dict[str, PartInfo] = {}
    
    # Strategy: Query all available APIs and merge
    # Order matters for which data takes precedence
    
    # 1. JLCPCB (if SKU provided) - for assembly/sourcing data
    if jlcpcb_sku or preferred_vendor == "jlcpcb":
        try:
            jlcpcb = JLCPCBAPI()
            sku = jlcpcb_sku or mpn  # Try mpn as SKU if no SKU provided
            result = jlcpcb.search_by_sku(sku)
            if result:
                results["jlcpcb"] = result
                logger.debug(f"JLCPCB found: {result.mpn}")
        except Exception as e:
            logger.debug(f"JLCPCB lookup failed: {e}")
    
    # 2. Digi-Key - for technical specs and pinout
    if preferred_vendor in ("auto", "digikey"):
        try:
            dk = DigiKeyAPI()
            dk_result = dk.search(mpn, limit=1)
            if dk_result:
                results["digikey"] = dk_result[0]
                logger.debug(f"Digi-Key found: {dk_result[0].mpn}")
        except Exception as e:
            logger.debug(f"Digi-Key lookup failed: {e}")
    
    # 3. Mouser - for stock levels and pricing
    if preferred_vendor in ("auto", "mouser"):
        try:
            mouser = MouserAPI()
            mouser_result = mouser.search(mpn, limit=1)
            if mouser_result:
                results["mouser"] = mouser_result[0]
                logger.debug(f"Mouser found: {mouser_result[0].mpn}")
        except Exception as e:
            logger.debug(f"Mouser lookup failed: {e}")
    
    # 4. TME - for dimensions and thermal data
    if preferred_vendor in ("auto", "tme"):
        try:
            tme = TMEAPI()
            tme_result = tme.search(mpn, limit=1)
            if tme_result:
                results["tme"] = tme_result[0]
                logger.debug(f"TME found: {tme_result[0].mpn}")
        except Exception as e:
            logger.debug(f"TME lookup failed: {e}")
    
    # Merge results into single PartInfo
    merged = _merge_part_info(results, mpn)

    # Optional: persist enrichment back into local DB for future offline builds.
    try:
        if merged and (os.environ.get("OPENHAC_ENRICH_DB_ON_LOOKUP") or "").strip().lower() in ("1", "true", "yes", "on"):
            from .db_manager import DatabaseManager

            db = DatabaseManager()
            # Best-effort: update by exact generic_name match if present, else by MPN.
            row = db.get_component(mpn)
            if row is None:
                # try to find by mpn field
                try:
                    import sqlite3

                    with sqlite3.connect(db.db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        cur = conn.execute("SELECT generic_name FROM components WHERE mpn = ? LIMIT 1", (merged.mpn,))
                        hit = cur.fetchone()
                        if hit:
                            row = {"generic_name": hit["generic_name"]}
                except Exception:
                    row = None
            if row and row.get("generic_name"):
                db.update_component_from_vendor(str(row["generic_name"]), merged)
    except Exception:
        pass

    return merged


def _merge_part_info(results: dict[str, PartInfo], mpn: str) -> Optional[PartInfo]:
    """Merge PartInfo from multiple vendors into one complete record.
    
    Priority order for data sources:
    - Pinout: Digi-Key > JLCPCB > None
    - Dimensions: TME > Digi-Key > None  
    - Thermal: TME > Digi-Key > None
    - Pricing: Mouser > Digi-Key > JLCPCB
    - Stock: JLCPCB > Mouser > Digi-Key > TME
    - Compliance: Digi-Key > TME > JLCPCB
    - Lifecycle: Digi-Key > TME > None
    """
    if not results:
        return None
    
    # Use first result as base
    base = list(results.values())[0]
    
    # Initialize with base data
    merged = PartInfo(
        mpn=mpn,
        manufacturer=base.manufacturer,
        supplier_sku=base.supplier_sku,
        description=base.description,
        stock=base.stock,
        price_breaks=base.price_breaks or [],
        datasheet_url=base.datasheet_url,
        product_url=base.product_url,
        category=base.category,
        package=base.package,
        rohs=base.rohs,
        lead_time_days=base.lead_time_days,
        last_updated=datetime.now(timezone.utc),
    )
    
    # Merge V7 fields with priority
    # Pinout: Digi-Key priority
    if "digikey" in results and results["digikey"].pinout:
        merged.pinout = results["digikey"].pinout
        try:
            merged.source_vendor = "digikey"  # type: ignore[attr-defined]
        except Exception:
            pass
    elif "jlcpcb" in results and results["jlcpcb"].pinout:
        merged.pinout = results["jlcpcb"].pinout
        try:
            merged.source_vendor = "jlcpcb"  # type: ignore[attr-defined]
        except Exception:
            pass
    else:
        try:
            merged.source_vendor = "auto"  # type: ignore[attr-defined]
        except Exception:
            pass
    
    # Dimensions: TME priority
    if "tme" in results and results["tme"].package_dimensions:
        merged.package_dimensions = results["tme"].package_dimensions
    elif "digikey" in results and results["digikey"].package_dimensions:
        merged.package_dimensions = results["digikey"].package_dimensions
    
    # Thermal: TME priority
    if "tme" in results and results["tme"].thermal_data:
        merged.thermal_data = results["tme"].thermal_data
    elif "digikey" in results and results["digikey"].thermal_data:
        merged.thermal_data = results["digikey"].thermal_data
    
    # Lifecycle: Digi-Key priority
    if "digikey" in results and results["digikey"].lifecycle_status:
        merged.lifecycle_status = results["digikey"].lifecycle_status
    elif "tme" in results and results["tme"].lifecycle_status:
        merged.lifecycle_status = results["tme"].lifecycle_status
    
    # Compliance: merge all available
    compliance_set = set()
    for r in results.values():
        if r.compliance_flags:
            compliance_set.update(r.compliance_flags)
    if compliance_set:
        merged.compliance_flags = list(compliance_set)
    
    # Stock: sum from all sources (conservative)
    total_stock = sum(r.stock for r in results.values() if r.stock > 0)
    if total_stock > 0:
        merged.stock = total_stock
    
    # Alternative MPNs: Digi-Key priority
    if "digikey" in results and results["digikey"].alternative_mpns:
        merged.alternative_mpns = results["digikey"].alternative_mpns
    
    logger.info(f"Merged data from {len(results)} vendors for {mpn}")
    return merged


def check_stock(supplier_sku: str, sku_type: str = "auto") -> int:
    """Check live stock for a part.

    Args:
        supplier_sku: The SKU (C12345 for LCSC, or Digi-Key/Mouser SKU)
        sku_type: "lcsc", "digikey", "mouser", or "auto" (detects by prefix)

    Returns:
        Stock quantity (0 if not found or error)
    """
    # Auto-detect SKU type
    if sku_type == "auto":
        if supplier_sku.startswith("C") and supplier_sku[1:].isdigit():
            sku_type = "lcsc"
        elif "-" in supplier_sku or len(supplier_sku) > 10:
            sku_type = "digikey"
        else:
            sku_type = "mouser"

    # For LCSC parts, try to extract MPN and search vendors
    if sku_type == "lcsc":
        from .db_manager import DatabaseManager
        db = DatabaseManager()
        comp = db.get_component_by_supplier_sku(supplier_sku)
        if comp and comp.get("mpn"):
            info = lookup_part_live(comp["mpn"])
            return info.stock if info else 0
        return 0

    # Digi-Key direct lookup
    if sku_type == "digikey":
        try:
            dk = DigiKeyAPI()
            info = dk.get_part(supplier_sku)
            return info.stock if info else 0
        except Exception:
            return 0

    # Mouser direct lookup
    if sku_type == "mouser":
        try:
            mouser = MouserAPI()
            info = mouser.get_part(supplier_sku)
            return info.stock if info else 0
        except Exception:
            return 0

    return 0


class TMEAPI:
    """TME (Transfer Multisort Elektronik) API Integration.

    BEST for bulk database population - most generous free tier:
    - Pricing/Stock: 2 requests/second (172,800/day potential)
    - Product Data: 10 requests/second (864,000/day potential)
    - NO hard daily cap - only per-second rate limiting

    Auth: API token + application secret (register at https://developers.tme.eu/).

    Environment: ``TME_API_TOKEN`` = portal **Token**; ``TME_API_SECRET`` = **Application secret**
    used for signing (not the customer number). Keys scoped only to “order” APIs may not allow
    product search — create an app with product/catalog access if searches still fail.

    Note: TME catalog leans toward European stock and industrial components.
    Best used for: Passives, connectors, electromechanical parts.
    Supplement with Digi-Key for specialized ICs.
    """

    API_BASE = "https://api.tme.eu/v1"

    def __init__(self, api_token: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_token = api_token or os.environ.get("TME_API_TOKEN")
        self.api_secret = api_secret or os.environ.get("TME_API_SECRET")
        # 2 req/s for pricing/stock (conservative default)
        self._rate_limiter_products = RateLimiter(max_calls=10, period_seconds=1)
        self._rate_limiter_pricing = RateLimiter(max_calls=2, period_seconds=1)

    def _post_form(self, path: str, pairs: list[tuple[str, str]]) -> dict:
        """POST ``application/x-www-form-urlencoded`` (*path* must start with ``/``)."""
        endpoint = f"{self.API_BASE}{path}"
        sig = _tme_calculate_signature("POST", endpoint, pairs, self.api_secret)
        body_pairs = sorted(pairs + [("ApiSignature", sig)], key=lambda kv: (kv[0], kv[1]))
        body = urllib.parse.urlencode(body_pairs, doseq=True).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": user_agent(),
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def search(self, keyword: str, limit: int = 50, use_cache: bool = True) -> list[PartInfo]:
        """Search for products by keyword.

        Uses TME Products/Search endpoint (10 req/s limit).

        Args:
            keyword: Search term (MPN, category, etc.)
            limit: Max results (default 50, max 1000)
            use_cache: Check local cache first

        Returns:
            List of PartInfo objects
        """
        if not self.api_token or not self.api_secret:
            raise ValueError("TME API credentials not configured. Set TME_API_TOKEN and TME_API_SECRET")

        # Check block status
        cache = get_api_cache()
        if cache.is_blocked("tme"):
            logger.debug("TME is in cool-off period, skipping search.")
            return []

        # Check cache
        if use_cache:
            cached = cache.get("tme_search", keyword)
            if cached:
                products = _tme_response_product_list(cached)
                logger.info(f"Using cached TME data for {keyword}")
                return [self._parse_product(p) for p in products[:limit]]

        self._rate_limiter_products.acquire()

        pairs = [
            ("Token", self.api_token),
            ("SearchPlain", keyword),
            ("SearchWithStock", "true"),
            ("SearchInStock", "false"),
            ("PageSize", str(min(limit, 1000))),
        ]
        try:
            data = self._post_form("/Products/Search.json", pairs)
            products = _tme_response_product_list(data)

            if use_cache and products:
                cache = get_api_cache()
                cache.set("tme_search", keyword, data, ttl_seconds=3600)
                logger.debug(f"Cached TME search for {keyword} ({len(products)} products)")

            return [self._parse_product(p) for p in products]
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                get_api_cache().set_blocked("tme")
            logger.warning(f"TME search failed: {e}")
            return []
        except Exception as e:
            logger.warning(f"TME search failed: {e}")
            return []

    def get_product(self, tme_symbol: str, use_cache: bool = True) -> Optional[PartInfo]:
        """Get specific product by TME Symbol.

        Uses TME Products/GetProducts endpoint (10 req/s limit).

        Args:
            tme_symbol: TME product symbol (e.g., "STM32F405RGT6")
            use_cache: Check cache first

        Returns:
            PartInfo if found, None otherwise
        """
        if not self.api_token or not self.api_secret:
            raise ValueError("TME API credentials not configured")

        # Check cache
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("tme_product", tme_symbol)
            if cached:
                products = _tme_response_product_list(cached)
                if products:
                    logger.info(f"Using cached TME product data for {tme_symbol}")
                    return self._parse_product(products[0])

        self._rate_limiter_products.acquire()

        pairs = [
            ("Token", self.api_token),
            ("Country", "US"),
            ("Language", "EN"),
            ("SymbolList[0]", tme_symbol),
        ]
        try:
            data = self._post_form("/Products/GetProducts.json", pairs)
            products = _tme_response_product_list(data)

            if use_cache and products:
                cache = get_api_cache()
                cache.set("tme_product", tme_symbol, data)

            return self._parse_product(products[0]) if products else None
        except Exception as e:
            logger.warning(f"TME product lookup failed: {e}")
            return None

    def get_pricing_and_stock(self, symbols: list[str]) -> dict[str, dict]:
        """Get pricing and stock for multiple products.

        Uses TME Products/GetPricesAndStocks endpoint (2 req/s limit).
        This is the rate-limited endpoint - use sparingly.

        Args:
            symbols: List of TME product symbols (max 50 per call)

        Returns:
            Dict mapping symbol -> {stock, price, currency}
        """
        if not self.api_token or not self.api_secret:
            raise ValueError("TME API credentials not configured")

        if len(symbols) > 50:
            symbols = symbols[:50]  # API limit

        self._rate_limiter_pricing.acquire()

        pairs: list[tuple[str, str]] = [
            ("Token", self.api_token),
            ("Country", "US"),
            ("Currency", "USD"),
        ]
        for i, sym in enumerate(symbols):
            pairs.append((f"SymbolList[{i}]", sym))

        try:
            data = self._post_form("/Products/GetPricesAndStocks.json", pairs)
            stocks = _tme_response_product_list(data)

            result = {}
            for s in stocks:
                symbol = s.get("Symbol", "")
                result[symbol] = {
                    "stock": s.get("Amount", 0),
                    "price": s.get("Price", {}).get("Amount", 0),
                    "currency": s.get("Price", {}).get("Currency", "USD"),
                    "multiples": s.get("Multiples", 1),
                }
            return result
        except Exception as e:
            logger.warning(f"TME pricing lookup failed: {e}")
            return {}

    def _parse_product(self, product: dict) -> PartInfo:
        """Parse TME product into PartInfo."""
        # Get pricing info if available
        price_list = product.get("PriceList", [])
        price_breaks = []
        for p in price_list:
            amount = p.get("Amount", 0)
            try:
                price = float(p.get("Price", 0))
            except (ValueError, TypeError):
                price = 0
            if amount > 0 and price > 0:
                price_breaks.append({"quantity": amount, "price": price})

        # Stock from Amount field
        stock = product.get("Amount", 0)

        pkg = product.get("Package", "")
        if isinstance(pkg, list):
            pkg = ",".join(str(x) for x in pkg if x is not None)

        return PartInfo(
            mpn=product.get("OriginalSymbol", ""),
            manufacturer=product.get("Manufacturer", ""),
            supplier_sku=product.get("Symbol", ""),
            description=product.get("Description", ""),
            stock=stock,
            price_breaks=price_breaks,
            datasheet_url=product.get("DatasheetUrl"),
            product_url=product.get("ProductInformationPage"),
            category=product.get("Category", ""),
            package=str(pkg or ""),
            rohs=product.get("RoHS", "false").lower() == "true",
            lead_time_days=None,
            last_updated=datetime.now(timezone.utc),
        )


def bulk_sync_from_tme(search_terms: list[str], max_per_term: int = 100) -> int:
    """Bulk populate database using TME API (high-volume friendly).

    TME's 2 req/s (pricing) and 10 req/s (products) limits allow
    for massive database population without hitting daily caps.

    Args:
        search_terms: List of search terms (e.g., ["resistor 0603", "capacitor 100nf"])
        max_per_term: Max results per search term

    Returns:
        Number of components inserted into database
    """
    from .db_manager import DatabaseManager

    db = DatabaseManager()
    tme = TMEAPI()
    total_inserted = 0

    logger.info(f"Starting bulk TME sync: {len(search_terms)} search terms")

    for term in search_terms:
        logger.info(f"Searching TME for: {term}")
        products = tme.search(term, limit=max_per_term)

        for product in products:
            if not product.mpn:
                continue

            # Create generic name from MPN
            generic_name = product.mpn.replace("-", "_").replace(" ", "_")

            # Check if already exists
            if db.get_component(generic_name):
                continue

            component = {
                "generic_name": generic_name,
                "kicad_symbol": "Device:R",  # Default, refine by category
                "kicad_footprint": "",
                "manufacturer": product.manufacturer,
                "mpn": product.mpn,
                "supplier_sku": f"TME:{product.supplier_sku}",
                "description": product.description,
                "category": product.category.lower().replace(" ", "_"),
                "stock": product.stock,
                "jlc_class": "Extended",  # TME parts treated as extended
                "attributes_json": json.dumps({
                    "datasheet_url": product.datasheet_url,
                    "product_url": product.product_url,
                    "rohs": product.rohs,
                }),
            }

            row_id = db.insert_component(component, ignore_duplicate=True)
            if row_id:
                total_inserted += 1

        logger.info(f"Inserted {total_inserted} components from '{term}'")

    logger.info(f"TME bulk sync complete: {total_inserted} total components")
    return total_inserted

