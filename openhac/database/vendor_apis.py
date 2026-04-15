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

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("openhac.vendor_apis")

# Cache TTL in seconds (default: 1 hour for API responses)
DEFAULT_CACHE_TTL = 3600
CACHE_DB_PATH = os.environ.get("OPENHAC_CACHE_DB", ":memory:")


class APICache:
    """SQLite-based cache for vendor API responses.

    Caches API responses to avoid hitting rate limits on repeated lookups.
    Each entry has a TTL (time-to-live) after which it's considered stale.

    Cache keys are hashed MPN + vendor name to create unique lookups.
    """

    def __init__(self, db_path: Optional[str] = None, ttl_seconds: int = DEFAULT_CACHE_TTL):
        self.db_path = db_path or CACHE_DB_PATH
        self.ttl = ttl_seconds
        self._init_db()
        self._hits = 0
        self._misses = 0

    def _init_db(self):
        """Initialize cache table."""
        import sqlite3
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
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
        import hashlib
        key = f"{vendor}:{mpn.upper().strip()}"
        return hashlib.sha256(key.encode()).hexdigest()[:32]

    def get_pinout(self, vendor: str, mpn: str) -> Optional[list[dict]]:
        """Get cached pinout data for a component.
        
        Returns list of pin dicts if available, None otherwise.
        Each pin dict has: num, name, type
        """
        key = self._make_key(f"{vendor}:pinout", mpn)
        
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
        expires = datetime.now() + timedelta(days=30)
        
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

    def set(self, vendor: str, mpn: str, response: dict, ttl_seconds: Optional[int] = None):
        """Cache an API response."""
        import sqlite3
        key = self._make_key(vendor, mpn)
        ttl = ttl_seconds or self.ttl

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
        cursor = self.conn.execute("DELETE FROM api_cache WHERE expires_at < datetime('now')")
        self.conn.commit()
        return cursor.rowcount

    def clear_all(self):
        """Clear entire cache."""
        self.conn.execute("DELETE FROM api_cache")
        self.conn.commit()

    def get_stats(self) -> dict:
        """Return cache statistics."""
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


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, max_calls: int, period_seconds: int):
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls: list[float] = []

    def acquire(self):
        """Block until a call slot is available."""
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

    def _get_token(self) -> str:
        """Get or refresh OAuth2 access token."""
        if self._access_token and self._token_expires and datetime.now() < self._token_expires:
            return self._access_token

        import urllib.request
        import urllib.parse

        if not self.client_id or not self.client_secret:
            raise ValueError("Digi-Key API credentials not configured. Set DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET")

        url = f"{self.API_BASE}/v1/oauth2/token"
        data = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }).encode()

        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded"
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                token_data = json.loads(resp.read().decode())
                self._access_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)
                self._token_expires = datetime.now() + timedelta(seconds=expires_in - 60)
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

        # Check cache first
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("digikey", keyword)
            if cached:
                products = cached.get("products", [])
                logger.info(f"Using cached Digi-Key data for {keyword}")
                return [self._parse_product(p) for p in products]

        token = self._get_token()
        url = f"{self.API_BASE}/products/v4/search/keyword"

        payload = json.dumps({
            "keywords": keyword,
            "limit": limit,
            "offset": 0,
        }).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-DIGIKEY-Client-Id": self.client_id,
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
        url = f"{self.API_BASE}/products/v4/search/digikeypartnumber/{digikey_part_number}"

        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": self.client_id,
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
            rohs=product.get("ro_hs_status") == "RoHS Compliant",
            lead_time_days=product.get("factory_stock_lead_days"),
            last_updated=datetime.now(),
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

        # Check cache first
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("mouser", keyword)
            if cached:
                parts = cached.get("SearchResults", {}).get("Parts", [])
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
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                parts = data.get("SearchResults", {}).get("Parts", [])

                # Cache the response
                if use_cache and parts:
                    cache = get_api_cache()
                    cache.set("mouser", keyword, data)
                    logger.debug(f"Cached Mouser response for {keyword}")

                return [self._parse_part(p) for p in parts[:limit]]
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
                parts = cached.get("SearchResults", {}).get("Parts", [])
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
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                parts = data.get("SearchResults", {}).get("Parts", [])

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
                parts = cached.get("SearchResults", {}).get("Parts", [])
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
            last_updated=datetime.now(),
            # V7 fields - Mouser provides limited data
            thermal_data=None,  # Not available from Mouser
            package_dimensions=None,  # Not available from Mouser
            lifecycle_status=None,  # Not available from Mouser
            compliance_flags=compliance if compliance else None,
            pinout=None,  # Not available from Mouser
            alternative_mpns=part.get("AlternatePackaging"),
            manufacturer_info=None,  # Not available from Mouser
        )


class TMEAPI:
    """TME (Transfer Multisort Elektronik) API Integration.
    
    Rate limit: 2 req/s for pricing, 10 req/s for products (very generous free tier)
    Auth: HMAC-SHA1 signature with API token + secret
    
    TME has the most generous free tier for high-volume database population.
    """
    
    API_BASE = "https://api.tme.eu"
    RATE_LIMIT_PRODUCTS = 10  # per second
    RATE_LIMIT_PRICING = 2    # per second
    
    def __init__(self, api_token: Optional[str] = None, api_secret: Optional[str] = None):
        self.api_token = api_token or os.environ.get("TME_API_TOKEN")
        self.api_secret = api_secret or os.environ.get("TME_API_SECRET")
        self._product_limiter = RateLimiter(max_calls=10, period_seconds=1)
        self._pricing_limiter = RateLimiter(max_calls=2, period_seconds=1)
    
    def _generate_signature(self, params: dict) -> str:
        """Generate HMAC-SHA1 signature for TME API authentication."""
        import hmac
        import hashlib
        
        # Sort params alphabetically and create base string
        sorted_params = sorted(params.items())
        base_string = "&".join(f"{k}={v}" for k, v in sorted_params)
        
        # Generate HMAC-SHA1
        signature = hmac.new(
            self.api_secret.encode(),
            base_string.encode(),
            hashlib.sha1
        ).hexdigest()
        return signature
    
    def search(self, keyword: str, limit: int = 10, use_cache: bool = True) -> list[PartInfo]:
        """Search for parts by keyword.
        
        Args:
            keyword: MPN or search term
            limit: Max results
            use_cache: Check local cache first (default True)
        """
        import urllib.request
        import urllib.parse
        
        # Check cache first
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("tme", keyword)
            if cached:
                products = cached.get("data", {}).get("products", [])
                logger.info(f"Using cached TME data for {keyword}")
                return [self._parse_product(p) for p in products[:limit]]
        
        if not self.api_token or not self.api_secret:
            raise ValueError("TME API credentials not configured. Set TME_API_TOKEN and TME_API_SECRET")
        
        self._product_limiter.acquire()
        
        # Build API request
        params = {
            "token": self.api_token,
            "searchPlain": keyword,
            "searchCategory": "",
            "searchParams": json.dumps({"page": 1, "limit": limit}),
        }
        params["signature"] = self._generate_signature(params)
        
        url = f"{self.API_BASE}/products/search"
        data = urllib.parse.urlencode(params).encode()
        
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded"
        })
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                products = data.get("data", {}).get("products", [])
                
                # Cache the response
                if use_cache and products:
                    cache = get_api_cache()
                    cache.set("tme", keyword, {"data": data})
                    logger.debug(f"Cached TME response for {keyword}")
                
                return [self._parse_product(p) for p in products[:limit]]
        except Exception as e:
            logger.warning(f"TME search failed: {e}")
            return []
    
    def _parse_product(self, product: dict) -> PartInfo:
        """Parse TME product response into PartInfo."""
        # TME provides rich data including dimensions and parameters
        params = product.get("parameters", [])
        
        # Extract dimensions if available
        pkg_dims = None
        for p in params:
            if p.get("name") in ["Dimensions", "Package"]:
                try:
                    val = p.get("value", "")
                    # Parse formats like "5.0mm x 5.0mm x 1.0mm"
                    parts = val.lower().replace("mm", "").replace("x", " ").split()
                    if len(parts) >= 2:
                        pkg_dims = {
                            "length": float(parts[0]) if len(parts) > 0 else None,
                            "width": float(parts[1]) if len(parts) > 1 else None,
                            "height": float(parts[2]) if len(parts) > 2 else None,
                        }
                except (ValueError, IndexError):
                    pass
        
        # Extract thermal data if available
        thermal = None
        for p in params:
            if p.get("name") in ["Thermal Resistance", "Power Dissipation"]:
                thermal = thermal or {}
                if "r_theta" in p.get("name", "").lower():
                    try:
                        thermal["r_theta_ja"] = float(p.get("value", "").replace("K/W", "").strip())
                    except ValueError:
                        pass
                if "power" in p.get("name", "").lower():
                    try:
                        thermal["max_power"] = float(p.get("value", "").replace("W", "").strip())
                    except ValueError:
                        pass
        
        # Build compliance flags
        compliance = []
        if product.get("rohs"):
            compliance.append("RoHS")
        
        return PartInfo(
            mpn=product.get("symbol", ""),
            manufacturer=product.get("producer", ""),
            supplier_sku=product.get("id", ""),
            description=product.get("description", ""),
            stock=product.get("amount", 0),
            price_breaks=[],  # TME pricing requires separate API call
            datasheet_url=product.get("files", {}).get("datasheet"),
            product_url=f"https://www.tme.eu/{product.get('id', '')}",
            category=product.get("category", ""),
            package=product.get("package", ""),
            rohs=product.get("rohs", False),
            lead_time_days=product.get("lead_time"),
            last_updated=datetime.now(),
            # V7 fields - TME provides good data
            thermal_data=thermal,
            package_dimensions=pkg_dims,
            lifecycle_status=product.get("status"),
            compliance_flags=compliance if compliance else None,
            pinout=None,  # TME doesn't provide pinout directly
            alternative_mpns=product.get("substitutes"),
            manufacturer_info={"certs": product.get("standards")} if product.get("standards") else None,
        )


def lookup_part_live(mpn: str, preferred_vendor: str = "auto") -> Optional[PartInfo]:
    """Live lookup of part info from vendor APIs.

    Tries vendors in order: Digi-Key first (better data), then Mouser, then TME.

    Args:
        mpn: Manufacturer part number to search
        preferred_vendor: "digikey", "mouser", "tme", or "auto" (default)

    Returns:
        PartInfo if found, None otherwise
    """
    if preferred_vendor in ("auto", "digikey"):
        try:
            dk = DigiKeyAPI()
            results = dk.search(mpn, limit=1)
            if results:
                return results[0]
        except Exception as e:
            logger.debug(f"Digi-Key lookup failed: {e}")

    if preferred_vendor in ("auto", "mouser"):
        try:
            mouser = MouserAPI()
            results = mouser.search(mpn, limit=1)
            if results:
                return results[0]
        except Exception as e:
            logger.debug(f"Mouser lookup failed: {e}")
    
    if preferred_vendor in ("auto", "tme"):
        try:
            tme = TMEAPI()
            results = tme.search(mpn, limit=1)
            if results:
                return results[0]
        except Exception as e:
            logger.debug(f"TME lookup failed: {e}")
        except Exception as e:
            logger.debug(f"Mouser lookup failed: {e}")

    return None


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
        comp = db.get_component_by_sku(supplier_sku)
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

    Auth: API token (register at https://developers.tme.eu/)

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

    def _make_signature(self, params: dict) -> str:
        """Create HMAC-SHA1 signature for TME API request."""
        import hashlib
        import hmac

        # Sort params alphabetically
        sorted_params = sorted(params.items())
        # Create signature base string
        base_string = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in sorted_params)
        # HMAC-SHA1 with api_secret
        signature = hmac.new(
            self.api_secret.encode(),
            base_string.encode(),
            hashlib.sha1
        ).hexdigest()
        return signature

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
        import urllib.request
        import urllib.parse

        if not self.api_token or not self.api_secret:
            raise ValueError("TME API credentials not configured. Set TME_API_TOKEN and TME_API_SECRET")

        # Check cache
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("tme_search", keyword)
            if cached:
                products = cached.get("Data", {}).get("ProductList", [])
                logger.info(f"Using cached TME data for {keyword}")
                return [self._parse_product(p) for p in products[:limit]]

        self._rate_limiter_products.acquire()

        params = {
            "Token": self.api_token,
            "ApiSignature": "",  # Will be calculated
            "SearchPlain": keyword,
            "SearchWithStock": "true",
            "SearchInStock": "false",
            "PageSize": str(min(limit, 1000)),
        }
        params["ApiSignature"] = self._make_signature(params)

        url = f"{self.API_BASE}/Products/Search.json?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
        })

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                products = data.get("Data", {}).get("ProductList", [])

                # Cache response
                if use_cache and products:
                    cache = get_api_cache()
                    cache.set("tme_search", keyword, data, ttl_seconds=3600)
                    logger.debug(f"Cached TME search for {keyword} ({len(products)} products)")

                return [self._parse_product(p) for p in products]
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
        import urllib.request
        import urllib.parse

        if not self.api_token or not self.api_secret:
            raise ValueError("TME API credentials not configured")

        # Check cache
        if use_cache:
            cache = get_api_cache()
            cached = cache.get("tme_product", tme_symbol)
            if cached:
                products = cached.get("Data", {}).get("ProductList", [])
                if products:
                    logger.info(f"Using cached TME product data for {tme_symbol}")
                    return self._parse_product(products[0])

        self._rate_limiter_products.acquire()

        params = {
            "Token": self.api_token,
            "ApiSignature": "",
            "Country": "US",
            "Language": "EN",
            "SymbolList[0]": tme_symbol,
        }
        params["ApiSignature"] = self._make_signature(params)

        url = f"{self.API_BASE}/Products/GetProducts.json?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                products = data.get("Data", {}).get("ProductList", [])

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
        import urllib.request
        import urllib.parse

        if not self.api_token or not self.api_secret:
            raise ValueError("TME API credentials not configured")

        if len(symbols) > 50:
            symbols = symbols[:50]  # API limit

        self._rate_limiter_pricing.acquire()

        params = {
            "Token": self.api_token,
            "ApiSignature": "",
            "Country": "US",
            "Currency": "USD",
        }
        for i, sym in enumerate(symbols):
            params[f"SymbolList[{i}]"] = sym

        params["ApiSignature"] = self._make_signature(params)

        url = f"{self.API_BASE}/Products/GetPricesAndStocks.json?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                stocks = data.get("Data", {}).get("ProductList", [])

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
            package=product.get("Package", []),  # TME returns list
            rohs=product.get("RoHS", "false").lower() == "true",
            lead_time_days=None,
            last_updated=datetime.now(),
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

