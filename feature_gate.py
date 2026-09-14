"""
Feature Gate Middleware — Flask
================================
Enforces tier-based feature access by checking the Suite Admin Feature Gates API.
The feature map is fetched from Suite Admin and cached for 5 minutes.
User tier is resolved via the Suite Admin verify-token endpoint.

Fail-open policy: if Suite Admin is unreachable, all features are allowed.

Usage:
    from feature_gate import require_feature, init_feature_gates

    @app.route('/analyze', methods=['POST'])
    @login_required
    @require_feature('skin_analysis_basic')
    def analyze():
        ...
"""

import os
import time
import logging
from functools import wraps

import requests as http_requests
from flask import request, session, jsonify, redirect, url_for, flash

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────
ADMIN_URL = os.environ.get("ADMIN_URL", "https://admin.flowgeniq.io").rstrip("/")
APP_SLUG = os.environ.get("APP_SLUG", "hair-studio-360")
CACHE_TTL = 5 * 60  # 5 minutes

# ─── Feature Map Cache ──────────────────────────────────────────────────────
_feature_map_cache = None
_feature_map_last_fetch = 0


def _fetch_feature_map():
    """Fetch the feature map from Suite Admin for this app."""
    global _feature_map_cache, _feature_map_last_fetch

    now = time.time()
    if _feature_map_cache and (now - _feature_map_last_fetch) < CACHE_TTL:
        return _feature_map_cache

    if not ADMIN_URL:
        logger.warning("[FeatureGate] No ADMIN_URL configured, feature gating disabled")
        return None

    try:
        resp = http_requests.get(
            f"{ADMIN_URL}/api/v1/feature-map/{APP_SLUG}",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            tiers = data.get("tiers", data)
            _feature_map_cache = tiers
            _feature_map_last_fetch = now
            logger.info(f"[FeatureGate] Refreshed feature map: {len(tiers)} tiers")
        else:
            logger.warning(f"[FeatureGate] Failed to fetch feature map: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"[FeatureGate] Failed to fetch feature map: {e}")

    return _feature_map_cache


def _get_user_tier():
    """Resolve the user's subscription tier from their session token."""
    token = session.get("token")
    if not token or not ADMIN_URL:
        return "growth"

    try:
        resp = http_requests.post(
            f"{ADMIN_URL}/api/verify-token",
            json={"token": token},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("valid"):
                user = data.get("user", {})
                return user.get("tier", "growth")
    except Exception as e:
        logger.warning(f"[FeatureGate] Failed to resolve user tier: {e}")

    return "growth"


def _is_feature_enabled(feature_map, tier, slug):
    """Check if a feature is enabled for a given tier."""
    if not feature_map:
        return True  # Fail-open

    tier_map = feature_map.get(tier)
    if not tier_map:
        return True  # Unknown tier = fail-open

    feature = tier_map.get(slug)
    if feature is None:
        return True  # Unknown feature = not gated

    return feature.get("enabled", True) is not False


def require_feature(slug, feature_name=None):
    """
    Flask route decorator — gates a route behind a feature slug.
    If the feature is not enabled for the user's tier, returns 403.
    Fails open if Suite Admin is unreachable.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                feature_map = _fetch_feature_map()
                if not feature_map:
                    return f(*args, **kwargs)  # Fail-open

                tier = _get_user_tier()
                enabled = _is_feature_enabled(feature_map, tier, slug)

                if not enabled:
                    display_name = feature_name or slug.replace("_", " ").title()
                    is_api = (
                        request.path.startswith("/api")
                        or "application/json" in (request.headers.get("Accept", ""))
                    )
                    if is_api:
                        return jsonify({
                            "error": "Feature not available on your current plan",
                            "code": "FEATURE_GATED",
                            "feature": slug,
                            "upgradeUrl": "https://suite.flowgeniq.io/suite/plans",
                        }), 403
                    else:
                        flash(
                            f'The "{display_name}" feature requires a higher plan. '
                            f"Please upgrade to access it.",
                            "error",
                        )
                        return redirect(url_for("index"))
            except Exception as e:
                logger.warning(f"[FeatureGate] Error in decorator, failing open: {e}")

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def check_feature(slug):
    """Programmatic check — returns True if the feature is enabled for the current user."""
    try:
        feature_map = _fetch_feature_map()
        if not feature_map:
            return True
        tier = _get_user_tier()
        return _is_feature_enabled(feature_map, tier, slug)
    except Exception:
        return True


def get_entitlements():
    """Get all entitlements for the current user (for frontend consumption)."""
    try:
        feature_map = _fetch_feature_map()
        tier = _get_user_tier()
        tier_features = feature_map.get(tier, {}) if feature_map else {}
        return {"tier": tier, "features": tier_features}
    except Exception:
        return {"tier": "growth", "features": {}}


def init_feature_gates(app):
    """Initialize feature gates — pre-warm the cache and register /api/entitlements."""
    if not ADMIN_URL:
        logger.info("[FeatureGate] No ADMIN_URL configured, feature gating disabled")
        return

    _fetch_feature_map()
    logger.info("[FeatureGate] Initialized")

    @app.route("/api/entitlements")
    def api_entitlements():
        """Return current user's feature entitlements for frontend gating."""
        if "user" not in session:
            return jsonify({"error": "Not authenticated"}), 401
        return jsonify(get_entitlements())
