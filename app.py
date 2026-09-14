from gevent import monkey
monkey.patch_all()

import os
import base64
import shutil
import hashlib
import glob as glob_module
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session, make_response
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image, ImageDraw, ImageFont, ImageOps
import io
import uuid
import requests
from datetime import datetime
from dotenv import load_dotenv
from functools import wraps
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, HRFlowable, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus.flowables import BalancedColumns
from reportlab.pdfgen import canvas

# Google Gemini API
from google import genai
from google.genai import types

# Background removal (rembg / U2Net — open-source, runs server-side)
try:
    from rembg import remove as rembg_remove
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False
    print('[rembg] Not installed — background removal disabled')

# Demo lead-gated module
from demo_leads import demo_bp

# Load environment variables from .env file
load_dotenv()

# Initialize Google Gemini client
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
gemini_client = None
if GEMINI_API_KEY:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    print("[Gemini] WARNING: GEMINI_API_KEY not set, image generation will not work")

# Env-configurable Gemini model names. Gemini 3 Pro Image is the stable
# replacement for the retired Gemini 3 Pro Image Preview endpoint.
GEMINI_IMAGE_MODEL = os.environ.get('GEMINI_IMAGE_MODEL', 'gemini-3-pro-image')
# Keep the standard hair-simulation output at 2K. This is intentionally a
# code default, rather than a Render environment setting, so the migration
# does not require an environment-variable change.
GEMINI_IMAGE_OUTPUT_SIZE = '2K'
GEMINI_VOICE_MODEL = os.environ.get('GEMINI_VOICE_MODEL', 'gemini-2.5-flash')
print(
    f"[Gemini] Image model: {GEMINI_IMAGE_MODEL} ({GEMINI_IMAGE_OUTPUT_SIZE}), "
    f"Voice model: {GEMINI_VOICE_MODEL}"
)


def extract_generated_image(parts):
    """Return the first Gemini inline image as a fully loaded PIL image.

    google-genai 2.x returns a ``google.genai.types.Image`` from
    ``Part.as_image()`` rather than a PIL image. Earlier SDK releases may
    return a PIL image instead. Normalize both forms here so every image
    workflow remains compatible with the configured SDK version.
    """
    for part in parts or []:
        inline_data = getattr(part, 'inline_data', None)
        if inline_data is None:
            continue

        image_bytes = None
        if hasattr(part, 'as_image'):
            generated_image = part.as_image()
            if isinstance(generated_image, Image.Image):
                generated_image.load()
                return generated_image
            image_bytes = getattr(generated_image, 'image_bytes', None)

        if not image_bytes:
            image_bytes = getattr(inline_data, 'data', None)
        if not image_bytes:
            continue
        if isinstance(image_bytes, str):
            import base64 as b64
            image_bytes = b64.b64decode(image_bytes)

        result_image = Image.open(io.BytesIO(image_bytes))
        result_image.load()
        return result_image

    return None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32)
app.config['SESSION_COOKIE_NAME'] = 'flowmediq_hair_studio_360_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get('RENDER'))
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['RESULTS_FOLDER'] = 'static/results'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'webp'}
app.config['TURNTABLE_FOLDER'] = 'static/turntable'


# Feature gate initialization
from feature_gate import init_feature_gates, require_feature
init_feature_gates(app)

# ============================================
# Proxy / Public-URL Configuration
# ============================================
# Render + Cloudflare terminate TLS in front of gunicorn. Without ProxyFix,
# url_for(..., _external=True) emits http:// and the internal Render hostname,
# which causes shared links to be rendered as insecure / non-canonical URLs and
# sometimes leads downstream link-unfurl crawlers to land on a login redirect.
# ProxyFix makes Flask respect the X-Forwarded-Proto and X-Forwarded-Host
# headers set by the proxy so external URLs are always correct (https + public host).
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_for=1, x_prefix=1)

# Always build external URLs with https scheme regardless of proxy behavior.
app.config['PREFERRED_URL_SCHEME'] = 'https'

# Register demo lead-gated blueprint (public, no auth required)
app.register_blueprint(demo_bp)

# Optional hard-override for the canonical public share base URL (e.g. when
# the app is reachable on multiple hosts and we want shares to always point to
# the branded custom domain). If unset, we fall back to the request host.
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')


def build_public_share_url(share_id):
    """Return a fully qualified, publicly accessible URL for a share.

    Prefers the configured PUBLIC_BASE_URL, then falls back to Flask's
    url_for(..., _external=True) which — with ProxyFix enabled above — will
    correctly honor the X-Forwarded-Proto/Host headers set by Render/Cloudflare.
    """
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/shared/{share_id}"
    return url_for('view_share', share_id=share_id, _external=True)

# ============================================
# Multi-App Admin Ecosystem Configuration
# ============================================
ADMIN_URL = os.environ.get('ADMIN_URL', 'https://admin.flowgeniq.io').rstrip('/')
APP_KEY = os.environ.get('APP_KEY', '')
APP_SLUG = os.environ.get('APP_SLUG', 'flowmediq-hair-studio-360')
SUITE_URL = os.environ.get('SUITE_URL', 'https://suite.flowmediq.io').rstrip('/')

# ============================================
# Dynamic Billing — Universal Suite Plans
# ============================================
# All billing sends raw_cost_usd to Suite Admin.
# Admin applies markup multiplier and deducts from shared credit pool.
import logging
import time as time_billing
logger = logging.getLogger(__name__)


class GeminiTransientCapacityError(RuntimeError):
    """Raised when the supported image-model fallback sequence is exhausted."""


# Keep Pro as the default for visual accuracy. Flash Image is a supported,
# separate-capacity fallback only for the explicit 503 high-demand condition.
GEMINI_IMAGE_FALLBACK_MODEL = 'gemini-3.1-flash-image'


def _is_gemini_high_demand_503(error):
    """Return True only for Gemini's temporary HTTP 503 high-demand response."""
    message = str(error).lower()
    return '503' in message and 'high demand' in message


def _is_transient_connection_error(error):
    """Return True for connection failures that justify the final Pro attempt."""
    message = str(error).lower()
    return isinstance(error, (ConnectionError, TimeoutError)) or any(
        marker in message for marker in ('connection', 'connect timeout', 'read timeout', 'network')
    )


def _request_gemini_image(model, contents, config):
    """Make one image request with an explicit model identifier."""
    return gemini_client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )


def generate_gemini_image_content(contents, config):
    """Run the approved Pro → Flash → Pro fallback sequence.

    The Flash attempt is made only after Gemini Pro Image returns a 503
    high-demand response. A final Pro attempt follows only when Flash returns
    the same 503 condition or a transient connection failure. The response and
    exact model used are returned so billing reflects a successful fallback.
    """
    try:
        return _request_gemini_image(GEMINI_IMAGE_MODEL, contents, config), GEMINI_IMAGE_MODEL
    except Exception as pro_error:
        if not _is_gemini_high_demand_503(pro_error):
            raise
        logger.warning('[Generate] Pro Image returned 503 high demand; trying supported Flash Image fallback.')

    try:
        return (
            _request_gemini_image(GEMINI_IMAGE_FALLBACK_MODEL, contents, config),
            GEMINI_IMAGE_FALLBACK_MODEL,
        )
    except Exception as flash_error:
        if not (_is_gemini_high_demand_503(flash_error) or _is_transient_connection_error(flash_error)):
            raise
        logger.warning('[Generate] Flash Image fallback was temporarily unavailable; retrying Pro Image in 5s.')
        time_billing.sleep(5)

    try:
        return _request_gemini_image(GEMINI_IMAGE_MODEL, contents, config), GEMINI_IMAGE_MODEL
    except Exception as final_pro_error:
        if _is_gemini_high_demand_503(final_pro_error) or _is_transient_connection_error(final_pro_error):
            raise GeminiTransientCapacityError(
                'Gemini image generation is temporarily unavailable due to high demand. '
                'No Hair Studio credits were deducted. Please try again in a few minutes.'
            ) from final_pro_error
        raise


# Estimated raw costs per action (USD)
ESTIMATED_RAW_COSTS_USD = {
    'hair_generation': 0.137,         # Gemini 3 Pro Image 2K (~69 credits at 50x)
    'hair_generation_flash': 0.104,   # Gemini 3.1 Flash Image 2K (~52 credits at 50x)
    'turntable_view': 0.137,          # Gemini 3 Pro Image 2K per turntable view
    'image_analysis': 0.02,           # Gemini image analysis for turntable prep (~10 credits at 50x)
    'voice_command': 0.001,           # Gemini 2.5 Flash NLP command
    'voice_tts_per_1k_chars': 0.015,  # OpenAI gpt-4o-mini-tts per 1K characters
}


def get_image_generation_raw_cost(model_used):
    """Return the audited raw cost for the successful 2K image model."""
    if model_used == GEMINI_IMAGE_FALLBACK_MODEL:
        return ESTIMATED_RAW_COSTS_USD['hair_generation_flash']
    return ESTIMATED_RAW_COSTS_USD['hair_generation']

# Pricing config cache (fetched from Suite Admin)
_pricing_config = {
    'markup_multiplier': 50,
    'credit_exchange_rate_usd': 0.10,
    'last_fetched': 0,
    'ttl': 300,  # 5 minutes
}

def fetch_pricing_config():
    """Fetch dynamic pricing config from Suite Admin (cached 5 min)."""
    global _pricing_config
    now = time_billing.time()
    if now - _pricing_config['last_fetched'] < _pricing_config['ttl']:
        return _pricing_config
    try:
        resp = requests.get(
            f"{ADMIN_URL}/api/apps/{APP_SLUG}/pricing",
            headers={'X-App-Key': APP_KEY},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            _pricing_config['markup_multiplier'] = data.get('markup_multiplier', 50)
            _pricing_config['credit_exchange_rate_usd'] = data.get('credit_exchange_rate_usd', 0.10)
            _pricing_config['last_fetched'] = now
            logger.info(f"[Billing] Pricing config refreshed: {_pricing_config['markup_multiplier']}x markup")
    except Exception as e:
        logger.warning(f"[Billing] Failed to fetch pricing config: {e}")
    return _pricing_config

# Graft counts for each area and density level (based on scalp zone diagram)
# Area 7 (Donor) is never selected
GRAFT_COUNTS = {
    'area1': {
        'full': 750,
        'moderate': 600
    },
    'area2': {
        'full': 1250,
        'moderate': 1000
    },
    'area3': {
        'full': 1600,
        'moderate': 1250,
        'camouflage': 900
    },
    'area4': {
        'full': 1200,
        'moderate': 900,
        'camouflage': 600
    },
    'area5a': {
        'full': 750,
        'moderate': 500,
        'camouflage': 350
    },
    'area5b': {
        'full': 750,
        'moderate': 500,
        'camouflage': 350
    },
    'area6a': {
        'full': 600,
        'moderate': 450,
        'camouflage': 300
    },
    'area6b': {
        'full': 600,
        'moderate': 450,
        'camouflage': 300
    }
}

# Area display names and descriptions
# Area display names and descriptions
AREA_INFO = {
    'area1': {
        'name': 'Area 1 – Temporal Peaks (Anterior Corners)',
        'description': (
            'Small triangular zones at the fronto-temporal corners that define the temporal angles '
            'and lateral framing of the face. These zones strongly influence perceived age and '
            'naturalness of the hairline.'
        ),
        'average_size': {
            'finger_width': '1–1.5 fingers (each side)',
            'inches': '0.8–1.2 in depth and height (each side)'
        },
        'densities': ['full', 'moderate', 'camouflage']
    },

    'area2': {
        'name': 'Area 2 – Frontal Hairline Band',
        'description': (
            'The leading frontal band immediately behind the forehead that creates the visible '
            'hairline. Designed for softness, irregularity, and natural transition from skin to hair.'
        ),
        'average_size': {
            'finger_width': '1–1.5 fingers (front-to-back)',
            'inches': '0.8–1.2 in depth, 4.5–5.5 in width'
        },
        'densities': ['full', 'moderate', 'camouflage']
    },

    'area3': {
        'name': 'Area 3 – Frontal Forelock / Central Frontal Zone',
        'description': (
            'The central frontal density zone behind the hairline that provides frontal fullness, '
            'styling strength, and acts as the main visual density anchor.'
        ),
        'average_size': {
            'finger_width': '2–3 fingers depth, 4–5 fingers width',
            'inches': '1.5–2.4 in depth, 3.0–4.0 in width'
        },
        'densities': ['full', 'moderate', 'camouflage']
    },

    'area4': {
        'name': 'Area 4 – Mid-Scalp Bridge Zone',
        'description': (
            'The transitional bridge between frontal zones and the crown, preventing an isolated '
            'frontal island and maintaining continuity toward the posterior scalp.'
        ),
        'average_size': {
            'finger_width': '2–3 fingers depth, 4–6 fingers width',
            'inches': '1.5–2.4 in depth, 3.0–4.8 in width'
        },
        'densities': ['full', 'moderate', 'camouflage']
    },

    'area5a': {
        'name': 'Area 5A – Anterior Crown Peripheral Zone',
        'description': (
            'The front half of the crown peripheral ring, immediately posterior to the mid-scalp. '
            'This zone blends mid-scalp hair flow into the crown and is more visible than the posterior half.'
        ),
        'average_size': {
            'finger_width': '1–1.5 fingers (ring thickness)',
            'inches': '0.8–1.2 in radial thickness'
        },
        'densities': ['full', 'moderate', 'camouflage']
    },

    'area5b': {
        'name': 'Area 5B – Posterior Crown Peripheral Zone',
        'description': (
            'The back half of the crown peripheral ring, closer to the occipital donor area. '
            'Acts as a buffer zone with lower visual priority.'
        ),
        'average_size': {
            'finger_width': '1–1.5 fingers (ring thickness)',
            'inches': '0.8–1.2 in radial thickness'
        },
        'densities': ['full', 'moderate', 'camouflage']
    },

    'area6a': {
        'name': 'Area 6A – Anterior Crown Core',
        'description': (
            'The front half of the crown/vertex center. More cosmetically important than the posterior '
            'core and usually prioritized if partial crown restoration is planned.'
        ),
        'average_size': {
            'finger_width': '1.5–2 fingers (half-core depth)',
            'inches': '1.2–1.6 in depth, 2.4–3.2 in width'
        },
        'densities': ['full', 'moderate', 'camouflage']
    },

    'area6b': {
        'name': 'Area 6B – Posterior Crown Core',
        'description': (
            'The back half of the crown/vertex center with the tightest whorl convergence. '
            'Lowest cosmetic return and often treated last or left untreated.'
        ),
        'average_size': {
            'finger_width': '1.5–2 fingers (half-core depth)',
            'inches': '1.2–1.6 in depth, 2.4–3.2 in width'
        },
        'densities': ['full', 'moderate', 'camouflage']
    },

    'area7': {
        'name': 'Area 7 – Donor Safe Zone',
        'description': (
            'The permanent horseshoe-shaped donor region across the mid-occipital and parietal scalp. '
            'Genetically resistant to androgenic loss and the source of transplantable grafts.'
        ),
        'average_size': {
            'finger_width': '3–4 fingers (vertical height at back)',
            'inches': '2.4–3.2 in safe-zone height (posterior)'
        },
        'densities': ['full', 'moderate', 'camouflage']
    }
}



# Density level descriptions
DENSITY_INFO = {
    'full': {
        'name': 'Full',
        'fu_per_cm2': '40-45',
        'description': 'Maximum density coverage for complete restoration'
    },
    'moderate': {
        'name': 'Moderate',
        'fu_per_cm2': '30-35',
        'description': 'Natural everyday density for balanced coverage'
    },
    'camouflage': {
        'name': 'Camouflage',
        'fu_per_cm2': '20',
        'description': 'Light coverage to reduce scalp visibility'
    }
}

# ============================================
# Global Auth Gate — redirect unauthenticated users to Suite SSO
# ============================================

# Public path prefixes that bypass the global auth gate. Shared result pages
# and their supporting data/static assets MUST remain in this list so shared
# links are always viewable by anyone with the URL, without login.
PUBLIC_PATH_PREFIXES = (
    '/auth/',
    '/health',
    '/static/',          # all share assets (images, turntable frames) live here
    '/login',
    '/api/user-info',
    '/favicon.ico',
    '/shared/',          # public shared-result HTML pages
    '/api/shared/',      # public shared-result JSON API
    '/download/',        # shared image/file downloads (safe-filtered below)
    '/og/',              # OpenGraph / social preview endpoints
    '/demo',             # public lead-gated demo (no login required)
)


@app.before_request
def require_auth():
    if any(request.path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
        return None
    if 'user' in session:
        return None
    return redirect(f'{SUITE_URL}/launch/{APP_SLUG}')


# ============================================
# Authentication Helper Functions
# ============================================

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def _admin_headers(token=None):
    """Build headers for Admin API requests."""
    headers = {'X-App-Key': APP_KEY, 'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def refresh_user_session():
    """Refresh user session data by checking credits with Admin API."""
    if 'user' not in session:
        return None
    try:
        token = session['user'].get('token')
        if not token:
            return None
        # Verify token is still valid
        resp = requests.post(
            f"{ADMIN_URL}/api/verify-token",
            json={'token': token},
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        if resp.status_code != 200 or not resp.json().get('valid'):
            return None
        user_data = resp.json().get('user', {})
        # Fetch credit info
        credit_resp = requests.post(
            f"{ADMIN_URL}/api/credits/check",
            headers=_admin_headers(token),
            timeout=10
        )
        credit_data = credit_resp.json() if credit_resp.status_code == 200 else {}
        session['user'].update({
            'plan': user_data.get('plan_title', session['user'].get('plan', 'Free')),
            'pool_total': credit_data.get('pool_total', 0),
            'pool_remaining': credit_data.get('pool_remaining', 0),
            'unlimited': credit_data.get('unlimited', False),
        })
        session.modified = True
        return session['user']
    except Exception as e:
        print(f"Error refreshing session: {e}")
    return None

def estimate_credits(raw_cost_usd):
    """Estimate credits from raw cost using current pricing config."""
    markup = _pricing_config.get('markup_multiplier', 50)
    rate = _pricing_config.get('credit_exchange_rate_usd', 0.10)
    return round((raw_cost_usd * markup) / rate)


def check_usage_limit(estimated_credits=0):
    """Check if user has enough credits.
    
    Args:
        estimated_credits: Minimum credits required for this action.
                          If 0, just checks pool_remaining > 0.
    """
    if 'user' not in session:
        return False, "Not logged in", None
    user = session.get('user', {})
    if user.get('unlimited'):
        return True, "Unlimited", {
            'pool_remaining': 'Unlimited', 'unlimited': True
        }
    pool_remaining = user.get('pool_remaining', 0)
    usage_data = {
        'pool_remaining': pool_remaining, 'unlimited': False
    }
    if pool_remaining <= 0:
        return False, "No credits remaining", usage_data
    if estimated_credits > 0 and pool_remaining < estimated_credits:
        return False, f"Insufficient credits. You have {pool_remaining} but this action requires ~{estimated_credits} credits.", usage_data
    return True, f"{pool_remaining} credits remaining", usage_data


def check_usage_for_turntable(required_credits=8):
    """Check if user has enough remaining credits for turntable generation (8 credits)."""
    if 'user' not in session:
        return False, "Not logged in", None, 0
    user = session.get('user', {})
    if user.get('unlimited'):
        return True, "Unlimited", {
            'pool_remaining': 'Unlimited', 'unlimited': True
        }, required_credits
    pool_remaining = user.get('pool_remaining', 0)
    usage_data = {
        'pool_remaining': pool_remaining, 'unlimited': False
    }
    if pool_remaining >= required_credits:
        return True, f"{pool_remaining} credits available", usage_data, pool_remaining
    return False, f"Not enough credits. Need {required_credits}, have {pool_remaining}.", usage_data, pool_remaining


def deduct_credits(amount=None, action='generation', token=None, raw_cost_usd=None, description=None):
    """Deduct credits via Admin API using raw_cost_usd (dynamic) or fixed amount (legacy).
    
    Universal Suite Plans: sends raw_cost_usd to Admin, which applies markup
    multiplier and deducts calculated credits from the shared pool.
    """
    tok = token or (session.get('user', {}).get('token') if 'user' in session else None)
    if not tok:
        return False, {'error': 'No auth token'}
    try:
        body = {
            'action': action,
            'description': description or f'FlowMediQ Hair Studio - {action}',
        }
        # Prefer raw_cost_usd (dynamic billing) over fixed amount
        if raw_cost_usd is not None and raw_cost_usd > 0:
            body['raw_cost_usd'] = round(raw_cost_usd, 6)
        elif amount is not None and amount > 0:
            body['amount'] = amount
        else:
            # Nothing to deduct
            return True, {'success': True, 'credits_deducted': 0}

        resp = requests.post(
            f"{ADMIN_URL}/api/credits/deduct",
            headers=_admin_headers(tok),
            json=body,
            timeout=15
        )
        data = resp.json()
        if resp.status_code == 200 and data.get('success'):
            logger.info(f"[Billing] {action}: raw_cost=${raw_cost_usd or 0:.4f}, credits_deducted={data.get('credits_deducted', '?')}")
            # Update session with new credit info if in request context
            try:
                if 'user' in session:
                    session['user']['pool_remaining'] = data.get('pool_remaining', 0)
                    session.modified = True
            except RuntimeError:
                pass  # Background thread, no session access
            return True, data
        logger.warning(f"[Billing] {action} deduction failed: {data.get('error', 'unknown')}")
        return False, data
    except Exception as e:
        logger.error(f"[Billing] {action} billing error: {e}")
        return False, {'error': str(e)}


def increment_usage(model_used=GEMINI_IMAGE_MODEL):
    """Deduct credits for hair generation using the successful model's raw cost."""
    raw_cost = get_image_generation_raw_cost(model_used)
    success, data = deduct_credits(
        action='hair_generation',
        raw_cost_usd=raw_cost,
        description=f'Hair generation ({model_used})'
    )
    if success:
        logger.info(
            f"[Billing] hair_generation ({model_used}) deduction OK: "
            f"{data.get('credits_deducted', '?')} credits"
        )
    else:
        logger.warning(f"[Billing] hair_generation ({model_used}) deduction FAILED: {data}")
    return success

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def build_prompt(area_selections):
    """Build a precise prompt based on selected areas and their density levels"""
    
    # Detailed prompts for each area and density combination
    # Detailed prompts for each area and density combination (each prompt is fully independent)
# Global landmark rules used inside each prompt:
# - Pronasale = tip of nose; Nasion = nasal root between eyes
# - Anterior Hairline Curve (AHC): measure vertical distance pronasale→nasion, project same distance superiorly from nasion onto scalp;
#   that projected central point is on the AHC; extend laterally in a natural curve to both temporal angles.
# - Crown Center (V): the natural vertex/whorl center on the crown.
# - Finger width ≈ 1.8–2.0 cm

    area_prompts = {

        'area1': {
            'full': (
                'Area 1 – Temporal Peaks (Anterior Corners). '
                'Location: Two bilateral triangular zones located at the fronto-temporal corners (left and right), on the hair-bearing scalp just above the temples. '
                'Anterior border (absolute): The anterior border is the segment of the Anterior Hairline Curve (AHC) at the temporal angles; '
                'AHC is defined by measuring the vertical distance from pronasale (tip of nose) to nasion and projecting the same distance superiorly from the nasion onto the scalp, '
                'then extending that line laterally as a gentle curve to each temporal angle. '
                'Shape & Size: Each side is a small triangle with its base on the AHC measuring ~2.5–3.0 cm, tapering posteriorly to an apex ~1.0 cm wide, '
                'with a posterior depth of ~2–3 cm (≈1–1.5 finger widths). '
                'Restore with full coverage at ~40–45 follicular units/cm². '
                'Create soft, feathered temporal angles with subtle asymmetry, acute forward-and-downward angulation, and micro-irregularities '
                'to frame the face naturally without a boxed or artificial look.'
            ),
            'moderate': (
                'Area 1 – Temporal Peaks (Anterior Corners). '
                'Location: Bilateral fronto-temporal corner triangles on the hair-bearing scalp just above the temples. '
                'Anterior border (absolute): The anterior edge lies on the Anterior Hairline Curve (AHC) at each temporal angle; '
                'AHC is defined by the pronasale-to-nasion distance projected superiorly from the nasion to the scalp and curved laterally to the temporal angles. '
                'Shape & Size: Each triangle has a base of ~2.5–3.0 cm along the AHC, narrows to an apex posteriorly, and extends ~2–3 cm in depth. '
                'Restore with moderate coverage at ~30–35 follicular units/cm². '
                'Maintain age-appropriate temporal recession, soft feathered edges, and realistic asymmetry while reducing transparency.'
            ),
            'camouflage': (
                'Area 1 – Temporal Peaks (Anterior Corners). '
                'Location: Bilateral triangular regions at the fronto-temporal corners above the temples. '
                'Anterior border (absolute): The front edge follows the Anterior Hairline Curve (AHC) at the temporal angles, '
                'where AHC is set by pronasale-to-nasion distance projected superiorly from nasion and curved laterally. '
                'Shape & Size: Triangles ~2.5–3.0 cm wide at the hairline base and ~2–3 cm deep. '
                'Add light camouflage at ~20 follicular units/cm². '
                'Place fine hairs strategically to reduce corner transparency while preserving a delicate, natural temple outline.'
            )
        },

        'area2': {
            'full': (
                'Area 2 – Frontal Hairline Band. '
                'Location: The leading frontal scalp band immediately behind the forehead, spanning across the front of the scalp from left temporal angle to right temporal angle. '
                'Anterior border (absolute): The anterior border is the Anterior Hairline Curve (AHC), defined by measuring vertical distance pronasale→nasion, '
                'projecting the same distance superiorly from the nasion onto the scalp (central hairline point), then extending laterally as a natural curve to both temporal angles. '
                'Shape & Size: A curved horizontal band ~2–3 cm deep (≈1–1.5 finger widths) and ~11–14 cm wide across the frontal scalp. '
                'Restore with full coverage at ~45–50 follicular units/cm². '
                'Design a soft, irregular, feathered hairline with micro- and macro-irregularities and a seamless transition into the denser frontal zone behind.'
            ),
            'moderate': (
                'Area 2 – Frontal Hairline Band. '
                'Location: Curved frontal band directly behind the forehead from temple to temple. '
                'Anterior border (absolute): The anterior border is the Anterior Hairline Curve (AHC) determined by pronasale→nasion distance mirrored above the nasion onto the scalp, '
                'then curved laterally to both temporal angles. '
                'Shape & Size: Band ~2–3 cm deep and ~11–14 cm wide. '
                'Restore with moderate coverage at ~30–35 follicular units/cm². '
                'Maintain a natural, age-appropriate hairline with soft irregularity and smooth blending into the region behind it.'
            ),
            'camouflage': (
                'Area 2 – Frontal Hairline Band. '
                'Location: Curved anterior frontal scalp band immediately behind the forehead from temple to temple. '
                'Anterior border (absolute): The Anterior Hairline Curve (AHC) defined via pronasale→nasion distance projected superiorly from nasion to scalp and curved laterally. '
                'Shape & Size: Band ~2–3 cm deep across the frontal scalp. '
                'Add light camouflage at ~20 follicular units/cm². '
                'Subtly soften the hairline and reduce scalp visibility while preserving a delicate, feathered leading edge.'
            )
        },

        'area3': {
            'full': (
                'Area 3 – Central Frontal Zone. '
                'Location: Central frontal scalp zone on the midline, positioned 1.5 fingers thickness behind the frontal hairline band and before the mid-scalp. '
                'Anterior border (absolute): A curved line drawn parallel to the Anterior Hairline Curve (AHC) and located exactly 2–3 cm posterior to the AHC '
                '(measured straight back from the AHC along the scalp surface). '
                'Shape & Size: Inverted triangular or trapezoidal region centered on the sagittal midline; '
                'anterior apex width ~3–4 cm; posterior base width ~9–11 cm; posterior depth ~4–6 cm (≈2–3 finger widths). '
                'Restore with full coverage at ~40–45 follicular units/cm². '
                'Build strong frontal density and volume to serve as the primary visual anchor for styling.'
            ),
            'moderate': (
                'Area 3 – Frontal Forelock / Central Frontal Zone. '
                'Location: Central frontal scalp zone on the sagittal midline 1.5 fingers thickness behind the hairline region and before the mid-scalp. '
                'Anterior border (absolute): A line parallel to the Anterior Hairline Curve (AHC) located 2–3 cm posterior to the AHC. '
                'Shape & Size: Tapered triangle/trapezoid centered on midline; ~4–6 cm depth; ~9–11 cm width at posterior base. '
                'Restore with moderate coverage at ~30–35 follicular units/cm². '
                'Create balanced density to reduce scalp show-through while maintaining natural layering and direction.'
            ),
            'camouflage': (
                'Area 3 – Frontal Forelock / Central Frontal Zone. '
                'Location: Central frontal scalp zone 1.5 fingers thickness behind the hairline region, centered on the sagittal midline. '
                'Anterior border (absolute): Curved line parallel to AHC and positioned 2–3 cm posterior to AHC. '
                'Shape & Size: Tapered triangle/trapezoid ~4–6 cm deep. '
                'Add light camouflage at ~20 follicular units/cm². '
                'Strategically place hairs to soften visibility with subtle, realistic coverage and natural direction.'
            )
        },

        'area4': {
            'full': (
                'Area 4 – Mid-Scalp Bridge Zone. '
                'Location: Central top-of-scalp zone between the frontal region and the crown dome, centered on the sagittal midline. '
                'Anterior border (absolute): A transverse line positioned 6–9 cm posterior to the Anterior Hairline Curve (AHC), '
                'measured along the sagittal midline over the scalp surface. '
                'Shape & Size: Broad rectangular/oval band ~4–6 cm deep (≈2–3 finger widths) and ~10–14 cm wide across the scalp. '
                'Restore with full coverage at ~40–45 follicular units/cm². '
                'Ensure seamless continuity toward the crown with posteriorly directed flow and natural density layering.'
            ),
            'moderate': (
                'Area 4 – Mid-Scalp Bridge Zone. '
                'Location: Central top-of-scalp bridge zone centered on the sagittal midline, anterior to the crown curvature. '
                'Anterior border (absolute): Line located 6–9 cm posterior to the Anterior Hairline Curve (AHC) along the midline. '
                'Shape & Size: Broad band ~4–6 cm deep and ~10–14 cm wide. '
                'Restore with moderate coverage at ~30–35 follicular units/cm². '
                'Blend naturally with gradual density transition and consistent posterior flow.'
            ),
            'camouflage': (
                'Area 4 – Mid-Scalp Bridge Zone. '
                'Location: Central top-of-scalp bridge between frontal and crown regions, centered on the sagittal midline. '
                'Anterior border (absolute): Line positioned 6–9 cm posterior to AHC along the midline. '
                'Shape & Size: Band ~4–6 cm deep. '
                'Add light camouflage at ~20 follicular units/cm². '
                'Use strategic placement to improve continuity and reduce scalp show-through without heavy density.'
            )
        },

        'area5a': {
            'full': (
                'Area 5A – Anterior Crown Peripheral Zone. '
                'Location: Anterior half of the crown peripheral ring surrounding the crown center (V) from the front side of the crown. '
                'Anterior border (absolute): The outer anterior arc of a ring centered on the Crown Center (V), located ~5–7 cm anterior to V '
                '(outer radius = crown core radius ~3–4 cm plus ring thickness ~2–3 cm). '
                'Shape & Size: Semi-circular ring segment (anterior half of the ring) with ring thickness ~2–3 cm (≈1–1.5 finger widths), '
                'centered on V and following the crown curvature. '
                'Restore with full coverage at ~40–45 follicular units/cm². '
                'Blend smoothly into the crown’s radial pattern while maintaining natural direction change and realistic layering.'
            ),
            'moderate': (
                'Area 5A – Anterior Crown Peripheral Zone. '
                'Location: Anterior half of the crown peripheral ring centered on Crown Center (V). '
                'Anterior border (absolute): Outer anterior arc of the ring centered at V at an outer radius of ~5–7 cm from V. '
                'Shape & Size: Semi-circular ring segment with thickness ~2–3 cm. '
                'Restore with moderate coverage at ~30–35 follicular units/cm². '
                'Create a natural peripheral crown bridge with controlled radial direction and efficient density.'
            ),
            'camouflage': (
                'Area 5A – Anterior Crown Peripheral Zone. '
                'Location: Anterior arc of the crown peripheral ring centered on Crown Center (V). '
                'Anterior border (absolute): Outer anterior ring arc at ~5–7 cm radius from V. '
                'Shape & Size: Ring segment ~2–3 cm thick. '
                'Add light camouflage at ~20 follicular units/cm². '
                'Reduce transparency while preserving optical blending and natural radial orientation.'
            )
        },

        'area5b': {
            'full': (
                'Area 5B – Posterior Crown Peripheral Zone. '
                'Location: Posterior half of the crown peripheral ring centered on the Crown Center (V), on the back side of the crown. '
                'Anterior border (absolute): A coronal dividing line passing through Crown Center (V) that separates anterior vs posterior crown halves; '
                'this line forms the front edge of the posterior ring segment (5B). '
                'Shape & Size: Semi-circular ring segment (posterior half of the ring) with ring thickness ~2–3 cm (≈1–1.5 finger widths); '
                'outer radius from V is ~5–7 cm (core radius ~3–4 cm plus ring thickness ~2–3 cm). '
                'Restore with full coverage at ~40–45 follicular units/cm². '
                'Maintain realistic radial direction and blend naturally toward the posterior scalp with correct angulation.'
            ),
            'moderate': (
                'Area 5B – Posterior Crown Peripheral Zone. '
                'Location: Posterior half of the crown peripheral ring centered on Crown Center (V). '
                'Anterior border (absolute): Coronal dividing line through V separating anterior and posterior crown halves. '
                'Shape & Size: Posterior semi-circular ring segment ~2–3 cm thick, outer radius ~5–7 cm from V. '
                'Restore with moderate coverage at ~30–35 follicular units/cm². '
                'Support crown appearance with conservative, natural density and correct radial orientation.'
            ),
            'camouflage': (
                'Area 5B – Posterior Crown Peripheral Zone. '
                'Location: Posterior arc of the crown peripheral ring centered on Crown Center (V). '
                'Anterior border (absolute): Coronal dividing line through V that defines the anterior edge of the posterior ring. '
                'Shape & Size: Ring segment ~2–3 cm thick, outer radius ~5–7 cm from V. '
                'Add light camouflage at ~20 follicular units/cm². '
                'Subtly reduce scalp visibility with minimal graft usage while preserving radial direction.'
            )
        },

        'area6a': {
            'full': (
                'Area 6A – Anterior Crown Core. '
                'Location: Anterior half of the crown core centered on the Crown Center (V), covering the front half of the whorl region. '
                'Anterior border (absolute): The anterior arc of the crown core circle centered at V, with crown core radius ~3–4 cm '
                '(i.e., the most anterior boundary of the core is ~3–4 cm anterior to V). '
                'Shape & Size: Semi-circular core segment (anterior half of the core) within a circle of diameter ~6–8 cm centered on V; '
                'anterior half depth ~3–4 cm. '
                'Restore with full coverage at ~40–45 follicular units/cm². '
                'Create a natural spiral/whorl pattern with precise angulation and smooth radial convergence.'
            ),
            'moderate': (
                'Area 6A – Anterior Crown Core. '
                'Location: Anterior half of the crown core centered on Crown Center (V). '
                'Anterior border (absolute): Anterior arc of the crown core circle at ~3–4 cm radius from V. '
                'Shape & Size: Anterior semi-circle of the core within a 6–8 cm diameter circle centered on V. '
                'Restore with moderate coverage at ~30–35 follicular units/cm². '
                'Maintain whorl direction with realistic spacing to reduce scalp show-through.'
            ),
            'camouflage': (
                'Area 6A – Anterior Crown Core. '
                'Location: Anterior half of the crown core centered on Crown Center (V). '
                'Anterior border (absolute): Anterior arc of the core circle at ~3–4 cm radius from V. '
                'Shape & Size: Anterior semi-circle of the crown core, ~3–4 cm deep. '
                'Add light camouflage at ~20 follicular units/cm². '
                'Follow whorl orientation precisely to achieve optical improvement with subtle, natural coverage.'
            )
        },

        'area6b': {
            'full': (
                'Area 6B – Posterior Crown Core. '
                'Location: Posterior half of the crown core centered on Crown Center (V), covering the back half of the whorl region. '
                'Anterior border (absolute): A coronal dividing line passing through Crown Center (V) that splits the crown core into anterior and posterior halves; '
                'this line is the front edge of the posterior core (6B). '
                'Shape & Size: Semi-circular core segment (posterior half of the core) within a circle of diameter ~6–8 cm centered on V; '
                'posterior half depth ~3–4 cm. '
                'Restore with full coverage at ~40–45 follicular units/cm². '
                'Maintain tight spiral convergence and accurate angulation to keep the crown whorl natural.'
            ),
            'moderate': (
                'Area 6B – Posterior Crown Core. '
                'Location: Posterior half of the crown core centered on Crown Center (V). '
                'Anterior border (absolute): Coronal dividing line through V that separates anterior and posterior crown halves. '
                'Shape & Size: Posterior semi-circle of the crown core within a 6–8 cm diameter circle centered on V. '
                'Restore with moderate coverage at ~30–35 follicular units/cm². '
                'Preserve natural whorl direction with conservative density and realistic spacing.'
            ),
            'camouflage': (
                'Area 6B – Posterior Crown Core. '
                'Location: Posterior half of the crown core centered on Crown Center (V). '
                'Anterior border (absolute): Coronal dividing line through V defining the anterior edge of the posterior core. '
                'Shape & Size: Posterior semi-circle of the crown core, ~3–4 cm deep. '
                'Add light camouflage at ~20 follicular units/cm². '
                'Subtly reduce scalp visibility while strictly respecting the tight whorl convergence and natural direction.'
            )
        }
    }


    
    # Build combined prompt
    prompt_parts = []
    
    for selection in area_selections:
        area = selection.get('area')
        density = selection.get('density', 'moderate')
        
        if area in area_prompts and density in area_prompts[area]:
            prompt_parts.append(area_prompts[area][density])
    
    if not prompt_parts:
        return "Add natural hair growth matching the existing hair color, texture, and style."
    
    # Combine all area prompts
    combined_prompt = " ".join(prompt_parts)
    
    # Add general instructions
    general_instructions = " Match the existing hair color, texture, and style perfectly. Ensure all added hair looks completely natural and realistic. Maintain the person's facial features, skin tone, and overall appearance. The result should look like a professional photograph, not digitally altered. Hair should follow natural growth directions and patterns. IMPORTANT: There shouldn't be any area numbers or any numbers overlayed on the generated image"
    
    return combined_prompt + general_instructions

def calculate_graft_summary(area_selections):
    """Calculate total graft estimates based on selected areas and densities"""
    summary = []
    total = 0
    
    for selection in area_selections:
        area = selection.get('area')
        density = selection.get('density', 'moderate')
        
        if area in GRAFT_COUNTS and density in GRAFT_COUNTS[area]:
            grafts = GRAFT_COUNTS[area][density]
            total += grafts
            
            area_info = AREA_INFO.get(area, {})
            density_info = DENSITY_INFO.get(density, {})
            
            summary.append({
                'area': area_info.get('name', area),
                'density': density_info.get('name', density),
                'fu_per_cm2': density_info.get('fu_per_cm2', ''),
                'grafts': grafts
            })
    
    return {
        'areas': summary,
        'total': total
    }

# ============================================
# Authentication Routes
# ============================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            # Authenticate against Multi-App-Admin API
            response = requests.post(
                f"{ADMIN_URL}/api/login",
                json={'username': username, 'password': password},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                user_data = data.get('user', {})
                token = data.get('token')
                # Store user info in session
                session['user'] = {
                    'id': user_data.get('id'),
                    'username': user_data.get('username'),
                    'email': user_data.get('username'),
                    'plan': user_data.get('plan_title', 'Free'),
                    'token': token,
                }
                # Fetch credit info from Admin API
                try:
                    credit_resp = requests.post(
                        f"{ADMIN_URL}/api/credits/check",
                        headers=_admin_headers(token),
                        timeout=10
                    )
                    if credit_resp.status_code == 200:
                        cd = credit_resp.json()
                        session['user'].update({
                            'pool_total': cd.get('pool_total', 0),
                            'pool_remaining': cd.get('pool_remaining', 0),
                            'unlimited': cd.get('unlimited', False),
                        })
                except Exception as ce:
                    print(f"Warning: Could not fetch credit info: {ce}")
                return redirect(url_for('index'))
            else:
                error_msg = response.json().get('error', 'Invalid credentials')
                return render_template('login.html', error=error_msg)
        except requests.exceptions.RequestException as e:
            return render_template('login.html', error='Authentication service unavailable')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Handle user logout"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/auth/sso')
def sso_login():
    """
    Single Sign-On endpoint.
    Called by the FlowMediQ AI Suite hub to log users in via JWT token.
    Usage: /auth/sso?token=JWT_TOKEN
    """
    token = request.args.get('token', '').strip()
    if not token:
        return redirect(url_for('login'))

    # Verify the token with Admin API
    try:
        resp = requests.post(
            f"{ADMIN_URL}/api/verify-token",
            json={'token': token},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('valid'):
                user_data = data.get('user', {})
                session['user'] = {
                    'id': user_data.get('id'),
                    'username': user_data.get('username'),
                    'email': user_data.get('username'),
                    'plan': user_data.get('plan_title', 'Free'),
                    'token': token,
                }
                # Fetch credit info
                try:
                    credit_resp = requests.post(
                        f"{ADMIN_URL}/api/credits/check",
                        headers=_admin_headers(token),
                        timeout=10
                    )
                    if credit_resp.status_code == 200:
                        cd = credit_resp.json()
                        session['user'].update({
                            'pool_total': cd.get('pool_total', 0),
                            'pool_remaining': cd.get('pool_remaining', 0),
                            'unlimited': cd.get('unlimited', False),
                        })
                except Exception as ce:
                    print(f"Warning: Could not fetch credit info via SSO: {ce}")
                return redirect(url_for('index'))
    except Exception as e:
        print(f"SSO error: {e}")

    return redirect(url_for('login'))

@app.route('/api/user-info')
@login_required
def get_user_info():
    """Get current user info and usage"""
    user = session.get('user', {})
    can_generate, usage_msg, usage_data = check_usage_limit()
    
    return jsonify({
        'username': user.get('username') or user.get('email'),
        'plan': user.get('plan', 'Free'),
        'usage': usage_data,
        'canGenerate': can_generate,
        'usageMessage': usage_msg
    })

# ============================================
# Main Application Routes
# ============================================

@app.route('/transplant')
@login_required
def transplant_studio():
    refresh_user_session()
    user = session.get('user', {})
    can_generate, usage_msg, usage_data = check_usage_limit()
    # Load this user's custom cost tiers (falls back to defaults if not set)
    user_id = str(user.get('id', ''))
    all_cost_settings = load_user_cost_settings()
    user_data = all_cost_settings.get(user_id, DEFAULT_COST_TIERS) if user_id else DEFAULT_COST_TIERS
    # Handle new dict format {tiers: [...], _pin_hash: '...'}
    if isinstance(user_data, dict):
        user_cost_tiers = user_data.get('tiers', DEFAULT_COST_TIERS)
    else:
        user_cost_tiers = user_data
    # Embed mode: ?embed=1 hides all practitioner-only controls (settings, shares, logout)
    # so clients see a clean app with the practitioner's custom pricing.
    embed_mode = request.args.get('embed', '0') == '1'
    return render_template('index.html', 
                         user=user, 
                         usage=usage_data, 
                         can_generate=can_generate,
                         suite_url=SUITE_URL,
                         cost_tiers=user_cost_tiers,
                         embed_mode=embed_mode)

@app.route('/api/areas', methods=['GET'])
def get_areas():
    """Return area information for the frontend"""
    return jsonify({
        'areas': AREA_INFO,
        'densities': DENSITY_INFO,
        'graftCounts': GRAFT_COUNTS
    })

@app.route('/upload', methods=['POST'])
@login_required
def upload_image():
    """Handle image upload"""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        # Generate unique filename — always save as PNG to preserve transparency
        base_name = uuid.uuid4().hex
        filename = f"{base_name}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Verify decoded image contents before accepting an upload.
        try:
            image = Image.open(file.stream)
            if image.width * image.height > 40000000:
                return jsonify({'error': 'Image exceeds 40 megapixels.'}), 400
            image.load()
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.save(filepath, 'PNG')
        except Exception:
            return jsonify({'error': 'Please upload a valid PNG, JPEG or WEBP image.'}), 400

        # Silently remove background using rembg (U2Net model)
        if REMBG_AVAILABLE:
            try:
                with open(filepath, 'rb') as f_in:
                    img_bytes = f_in.read()
                result_bytes = rembg_remove(img_bytes)
                with open(filepath, 'wb') as f_out:
                    f_out.write(result_bytes)
                print(f'[rembg] Background removed: {filename}')
            except Exception as rembg_err:
                print(f'[rembg] Background removal failed (using original): {rembg_err}')

        return jsonify({
            'success': True,
            'filename': filename,
            'imageId': studio360_adopt_upload(filename),
            'url': f'/static/uploads/{filename}'
        })

    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/rotate', methods=['POST'])
@login_required
def rotate_image():
    """Rotate a previously uploaded image by a multiple of 90 degrees and overwrite it.

    Body JSON: { "filename": "<uploaded filename>", "degrees": 90 }
    Positive degrees rotate clockwise. Free action (no credits deducted).
    """
    data = request.json or {}
    filename = data.get('filename')
    try:
        degrees = int(data.get('degrees', 90))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid degrees value'}), 400

    # Normalize to one of 0/90/180/270
    degrees = degrees % 360
    if degrees % 90 != 0:
        return jsonify({'error': 'Degrees must be a multiple of 90'}), 400

    if not filename:
        return jsonify({'error': 'No filename provided'}), 400

    # Guard against path traversal; only operate within the upload folder
    safe_name = secure_filename(filename)
    if safe_name != filename:
        return jsonify({'error': 'Invalid filename'}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Image not found'}), 404

    if degrees == 0:
        return jsonify({'success': True, 'filename': safe_name, 'url': f'/static/uploads/{safe_name}'})

    try:
        with Image.open(filepath) as img:
            img = img.convert('RGB') if img.mode in ('P', 'RGBA', 'LA') else img
            # PIL rotate is counter-clockwise; negate so positive == clockwise
            rotated = img.rotate(-degrees, expand=True)
            rotated.save(filepath)
    except Exception as exc:
        logger.warning(f"[Rotate] Failed to rotate {safe_name}: {exc}")
        return jsonify({'error': 'Could not rotate image'}), 500

    # Cache-busting token so the browser reloads the updated image
    return jsonify({
        'success': True,
        'filename': safe_name,
        'imageId': studio360_adopt_upload(safe_name),
        'url': f'/static/uploads/{safe_name}?r={uuid.uuid4().hex[:8]}'
    })

@app.route('/generate', methods=['POST'])
@login_required
def generate_hair():
    """Generate hair growth on selected areas using Google Gemini API"""
    
    # Pre-flight credit check with estimated cost
    estimated = estimate_credits(ESTIMATED_RAW_COSTS_USD['hair_generation'])
    can_generate, usage_msg, usage_data = check_usage_limit(estimated_credits=estimated)
    if not can_generate:
        return jsonify({'error': f'Usage limit reached. {usage_msg}', 'limitReached': True, 'usage': usage_data}), 403
    
    data = request.json
    filename = data.get('filename')
    area_selections = data.get('areaSelections', [])
    
    if not filename:
        return jsonify({'error': 'No filename provided'}), 400
    
    if not area_selections:
        return jsonify({'error': 'No areas selected'}), 400
    
    original_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(original_path):
        return jsonify({'error': 'Original image not found'}), 404
    
    try:
        # Build prompt based on selected areas and densities
        prompt = build_prompt(area_selections)
        
        # Calculate graft summary
        graft_summary = calculate_graft_summary(area_selections)
        
        # Load the image using PIL
        input_image = Image.open(original_path)
        
        # Call Google Gemini API with env-configurable model and safety settings
        if not gemini_client:
            return jsonify({'error': 'Gemini API not configured. Set GEMINI_API_KEY.'}), 500
        response, model_used = generate_gemini_image_content(
            contents=[prompt, input_image],
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
                image_config=types.ImageConfig(image_size=GEMINI_IMAGE_OUTPUT_SIZE),
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                ]
            )
        )
        
        # Extract the generated image from response
        parts = None
        if hasattr(response, 'parts') and response.parts:
            parts = response.parts
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                parts = candidate.content.parts

        result_image = extract_generated_image(parts)
        
        if result_image is None:
            logger.warning("[Generate] Gemini returned no image in response")
            return jsonify({'error': 'No image generated in response'}), 500
        
        # Save result image
        result_filename = f"result_{uuid.uuid4().hex}.png"
        result_path = os.path.join(app.config['RESULTS_FOLDER'], result_filename)
        result_image.save(result_path)
        
        # Image validation: dimensions > 10px and file size > 1KB
        w, h = result_image.size
        file_size = os.path.getsize(result_path)
        if w <= 10 or h <= 10 or file_size < 1024:
            logger.warning(f"[Generate] Image validation failed: {w}x{h}, {file_size} bytes")
            os.remove(result_path)
            return jsonify({'error': 'Generated image failed validation (too small or corrupt). Please try again.'}), 500
        
        # Deduct credits AFTER successful, validated generation
        billing_ok = increment_usage(model_used)
        if not billing_ok:
            logger.warning("[Generate] Billing deduction failed but image was generated")
        
        # Refresh session credits after deduction
        refresh_user_session()
        
        # Get updated usage info
        _, _, updated_usage = check_usage_limit()
        
        return jsonify({
            'success': True,
            'resultUrl': f'/static/results/{result_filename}',
            'originalUrl': f'/static/uploads/{filename}',
            'graftSummary': graft_summary,
            'modelUsed': model_used,
            'usage': updated_usage
        })
        
    except GeminiTransientCapacityError as error:
        logger.warning('[Generate] Gemini capacity retries exhausted')
        return jsonify({'error': str(error), 'retryable': True}), 503
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"[Generate] Generation error: {error_details}")
        return jsonify({'error': f'Generation failed: {str(e)}'}), 500

def draw_page_border(canvas, doc):
    """Draw decorative page border on each page"""
    canvas.saveState()
    
    # Page dimensions
    page_width, page_height = letter
    margin = 0.4 * inch
    border_width = 2
    
    # Define colors
    primary_dark = colors.HexColor('#1a1a2e')
    accent_gold = colors.HexColor('#d4af37')
    
    # Outer border (dark)
    canvas.setStrokeColor(primary_dark)
    canvas.setLineWidth(border_width)
    canvas.rect(margin, margin, page_width - 2*margin, page_height - 2*margin)
    
    # Inner decorative border (gold) - slightly inset
    inner_margin = margin + 4
    canvas.setStrokeColor(accent_gold)
    canvas.setLineWidth(1)
    canvas.rect(inner_margin, inner_margin, page_width - 2*inner_margin, page_height - 2*inner_margin)
    
    canvas.restoreState()

@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    """Generate elegant single-page PDF report with before/after images and summary"""
    data = request.json
    
    try:
        before_image_url = data.get('beforeImage')
        after_image_url = data.get('afterImage')
        selections = data.get('selections', [])
        total = data.get('total', 0)
        report_date = data.get('date', datetime.now().strftime('%B %d, %Y'))
        
        # Create PDF buffer
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.6*inch,
            leftMargin=0.6*inch,
            topMargin=0.6*inch,
            bottomMargin=0.6*inch
        )
        
        # Define colors
        primary_dark = colors.HexColor('#1a1a2e')
        accent_coral = colors.HexColor('#e94560')
        accent_gold = colors.HexColor('#d4af37')
        text_gray = colors.HexColor('#4a5568')
        light_bg = colors.HexColor('#f8f9fa')
        
        # Styles
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=26,
            spaceAfter=4,
            alignment=TA_CENTER,
            textColor=primary_dark,
            fontName='Helvetica-Bold'
        )
        
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=6,
            alignment=TA_CENTER,
            textColor=text_gray
        )
        
        date_style = ParagraphStyle(
            'Date',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=12,
            alignment=TA_CENTER,
            textColor=accent_gold,
            fontName='Helvetica-Bold'
        )
        
        # Beautiful centered section title style
        section_title_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=0,
            spaceAfter=0,
            alignment=TA_CENTER,
            textColor=primary_dark,
            fontName='Helvetica-Bold'
        )
        
        label_style = ParagraphStyle(
            'Label',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            textColor=text_gray,
            fontName='Helvetica-Bold'
        )
        
        disclaimer_style = ParagraphStyle(
            'Disclaimer',
            parent=styles['Normal'],
            fontSize=8,
            spaceBefore=8,
            alignment=TA_JUSTIFY,
            textColor=colors.HexColor('#6b5a3e'),
            leading=11
        )
        
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=9,
            alignment=TA_CENTER,
            textColor=text_gray
        )
        
        # Build PDF content
        story = []
        
        # ===== HEADER SECTION =====
        # ===== HEADER SECTION =====
        story.append(Spacer(1, 12))
        story.append(Paragraph("FlowMediQ AI Hair Studio", title_style))
        story.append(Spacer(1, 8))  # Space between title and subtitle
        story.append(Paragraph("Hair Restoration Visualization Report", subtitle_style))
        story.append(Paragraph(f"Generated: {report_date}", date_style))

        
        # Gold decorative line
        story.append(HRFlowable(width="50%", thickness=2.5, color=accent_gold, spaceBefore=3, spaceAfter=15))
        
        # ===== BEFORE & AFTER IMAGES =====
        before_path = '.' + before_image_url
        after_path = '.' + after_image_url
        
        if os.path.exists(before_path) and os.path.exists(after_path):
            # Larger image size for better visibility
            img_width = 2.2 * inch
            img_height = 2.2 * inch
            
            before_img = RLImage(before_path, width=img_width, height=img_height, kind='proportional')
            after_img = RLImage(after_path, width=img_width, height=img_height, kind='proportional')
            
            # Create elegant image comparison table with borders
            img_table_data = [
                [
                    Table([[before_img]], style=[
                        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#d0d0d0')),
                        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                        ('LEFTPADDING', (0, 0), (-1, -1), 4),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ]),
                    Spacer(0.4*inch, 0),
                    Table([[after_img]], style=[
                        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#10b981')),
                        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                        ('LEFTPADDING', (0, 0), (-1, -1), 4),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ])
                ],
                [
                    Paragraph("BEFORE", label_style),
                    '',
                    Paragraph('<font color="#10b981"><b>AFTER</b></font>', ParagraphStyle('AfterLabel', parent=label_style, textColor=colors.HexColor('#10b981')))
                ]
            ]
            
            img_table = Table(img_table_data, colWidths=[2.7*inch, 0.4*inch, 2.7*inch])
            img_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 1), (-1, 1), 10),
            ]))
            
            story.append(img_table)
        
        story.append(Spacer(1, 18))
        
        # ===== TREATMENT SUMMARY SECTION =====
        # Beautiful centered title with decorative elements
        story.append(HRFlowable(width="30%", thickness=1, color=accent_gold, spaceBefore=0, spaceAfter=6))
        story.append(Paragraph("✦  Treatment Summary  ✦", section_title_style))
        story.append(HRFlowable(width="30%", thickness=1, color=accent_gold, spaceBefore=6, spaceAfter=12))
        
        # Create centered summary table with new columns
        table_data = [['Treatment Area', 'Density', 'FU/cm²', 'Est. Grafts']]
        
        for selection in selections:
            table_data.append([
                selection['area'],
                selection['density'],
                selection.get('fuPerCm2', ''),
                str(selection['grafts'])
            ])
        
        # Total row
        table_data.append(['', '', 'TOTAL', str(total)])
        
        # Centered table with better styling
        summary_table = Table(table_data, colWidths=[2.2*inch, 1.0*inch, 0.8*inch, 1.0*inch])
        summary_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), primary_dark),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            # Data rows
            ('BACKGROUND', (0, 1), (-1, -2), light_bg),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            # Total row
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fff0f0')),
            ('FONTNAME', (2, -1), (-1, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (-1, -1), (-1, -1), accent_coral),
            ('FONTSIZE', (-1, -1), (-1, -1), 10),
            # Alignment - all centered
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d0d0d0')),
            ('LINEBELOW', (0, 0), (-1, 0), 2, accent_gold),
        ]))
        
        # Center the table on the page
        centered_table = Table([[summary_table]], colWidths=[7.3*inch])
        centered_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        
        story.append(centered_table)
        story.append(Spacer(1, 15))
        
        # ===== DISCLAIMER SECTION =====
        disclaimer_text = """<b>Important Disclaimer:</b> This visualization is a rough estimate generated by AI for illustrative purposes only. It does not guarantee actual surgical results. Individual outcomes vary based on hair characteristics, donor area quality, scalp laxity, and surgical technique. The graft estimates are approximations. Please consult with a qualified hair restoration specialist for accurate assessment."""
        
        disclaimer_table = Table(
            [[Paragraph(disclaimer_text, disclaimer_style)]],
            colWidths=[6.0*inch]
        )
        disclaimer_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fffbeb')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#f0d78c')),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))
        
        # Center the disclaimer
        centered_disclaimer = Table([[disclaimer_table]], colWidths=[7.3*inch])
        centered_disclaimer.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        
        story.append(centered_disclaimer)
        story.append(Spacer(1, 15))
        
        # ===== FOOTER =====
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#d0d0d0'), spaceBefore=0, spaceAfter=12))
        story.append(Paragraph("Powered by <b>FlowMediQ AI Hair Studio</b>", footer_style))
        
        # Build PDF with page border
        doc.build(story, onFirstPage=draw_page_border, onLaterPages=draw_page_border)
        
        # Return PDF
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'fuesian_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        )
        
    except Exception as e:
        import traceback
        print(f"PDF generation error: {traceback.format_exc()}")
        return jsonify({'error': f'PDF generation failed: {str(e)}'}), 500

@app.route('/download/<path:filename>')
def download_file(filename):
    """Download result image"""
    if filename.startswith('result_'):
        filepath = os.path.join(app.config['RESULTS_FOLDER'], filename)
    else:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'error': 'File not found'}), 404

# ============================================
# 360° Turntable Generation
# ============================================

import threading
import json
import time as time_module

# In-memory store for turntable generation progress
turntable_sessions = {}

# Persistence file for completed turntable sessions (survives restarts)
TURNTABLE_DATA_FILE = os.path.join('static', 'turntable', 'sessions.json')

# Unified shares persistence file (supports both before/after only AND before/after + turntable)
SHARES_DATA_FILE = os.path.join('static', 'shares', 'shares.json')

# Per-user cost settings persistence file
USER_COST_SETTINGS_FILE = os.path.join('static', 'data', 'user_cost_settings.json')

# Default cost tiers (mirrors the hardcoded values in app.js)
DEFAULT_COST_TIERS = [
    {'maxGrafts': 1500,  'label': 'Under 1,500 grafts',     'min': 7000,  'max': 7500,  'fixed': None},
    {'maxGrafts': 2500,  'label': '1,500 - 2,499 grafts',   'min': 7500,  'max': 8250,  'fixed': None},
    {'maxGrafts': 3000,  'label': '2,500 - 2,999 grafts',   'min': 8250,  'max': 8750,  'fixed': None},
    {'maxGrafts': 3500,  'label': '3,000 - 3,499 grafts',   'min': 8750,  'max': 9500,  'fixed': None},
    {'maxGrafts': 4000,  'label': '3,500 - 3,999 grafts',   'min': 9500,  'max': 10000, 'fixed': None},
    {'maxGrafts': None,  'label': '4,000+ grafts',           'min': None,  'max': None,  'fixed': 10500},
]

def load_user_cost_settings():
    """Load all users cost settings from disk."""
    try:
        if os.path.exists(USER_COST_SETTINGS_FILE):
            with open(USER_COST_SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading user cost settings: {e}")
    return {}

def save_user_cost_settings(settings_data):
    """Save all users cost settings to disk."""
    try:
        os.makedirs(os.path.dirname(USER_COST_SETTINGS_FILE), exist_ok=True)
        with open(USER_COST_SETTINGS_FILE, 'w') as f:
            json.dump(settings_data, f)
    except Exception as e:
        print(f"Error saving user cost settings: {e}")

def load_persisted_turntable_sessions():
    """Load completed turntable sessions from disk."""
    try:
        if os.path.exists(TURNTABLE_DATA_FILE):
            with open(TURNTABLE_DATA_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading turntable sessions: {e}")
    return {}

def persist_turntable_session(session_id, session_data):
    """Save a completed turntable session to disk for sharing."""
    try:
        os.makedirs(os.path.dirname(TURNTABLE_DATA_FILE), exist_ok=True)
        persisted = load_persisted_turntable_sessions()
        persisted[session_id] = {
            'images': session_data.get('images', []),
            'before_image': session_data.get('before_image', ''),
            'after_image': session_data.get('after_image', ''),
            'graft_summary': session_data.get('graft_summary', None),
            'created_at': datetime.now().isoformat(),
            'status': 'complete'
        }
        with open(TURNTABLE_DATA_FILE, 'w') as f:
            json.dump(persisted, f)
    except Exception as e:
        print(f"Error persisting turntable session: {e}")

def load_shares():
    """Load all shares from disk."""
    try:
        if os.path.exists(SHARES_DATA_FILE):
            with open(SHARES_DATA_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading shares: {e}")
    return {}

def save_shares(shares_data):
    """Save shares to disk."""
    try:
        os.makedirs(os.path.dirname(SHARES_DATA_FILE), exist_ok=True)
        with open(SHARES_DATA_FILE, 'w') as f:
            json.dump(shares_data, f)
    except Exception as e:
        print(f"Error saving shares: {e}")

# 8 standard turntable views with explicit names and descriptions
TURNTABLE_VIEWS = [
    {
        'angle': 0,
        'name': 'Front View',
        'short': 'Front',
        'description': (
            'Direct front view. The person faces the camera straight on. '
            'Both eyes fully visible, face perfectly symmetrical, both ears equidistant. '
            'The nose points directly at the camera.'
        )
    },
    {
        'angle': 45,
        'name': 'Right Front Oblique',
        'short': 'R-Front',
        'description': (
            'The person has turned their head 45 degrees to THEIR RIGHT (toward the RIGHT side of the image). '
            'The nose points toward the RIGHT side of the image. '
            'We see more of the LEFT side of the persons face (left cheek, left ear visible). '
            'The persons LEFT ear is clearly visible. The right side of the face is foreshortened.'
        )
    },
    {
        'angle': 90,
        'name': 'Right View',
        'short': 'Right',
        'description': (
            'The person faces directly to the RIGHT of the image. Perfect profile view. '
            'The nose points to the RIGHT edge of the image. '
            'We see ONLY the LEFT side of the face. The LEFT ear is fully visible. '
            'The right ear is completely hidden behind the head. '
            'This is a left-side profile shot with the person looking right.'
        )
    },
    {
        'angle': 135,
        'name': 'Right Back Oblique',
        'short': 'R-Back',
        'description': (
            'The person is turned 135 degrees to their right, now mostly facing AWAY from camera '
            'and toward the RIGHT side of the image. We see the back-left of the head. '
            'The LEFT ear is visible from a rear angle. Very little face visible - '
            'the person is looking away to the right. Mostly the back and left side of the head visible.'
        )
    },
    {
        'angle': 180,
        'name': 'Back View',
        'short': 'Back',
        'description': (
            'Direct back view. The person faces completely AWAY from the camera. '
            'We see ONLY the back of the head, neck, and shoulders. '
            'NO face visible at all. Hair visible from behind. Both ears may be partially visible.'
        )
    },
    {
        'angle': 225,
        'name': 'Left Back Oblique',
        'short': 'L-Back',
        'description': (
            'The person is turned 225 degrees (or equivalently 135 degrees to their left), '
            'now mostly facing AWAY from camera and toward the LEFT side of the image. '
            'We see the back-right of the head. The RIGHT ear is visible from a rear angle. '
            'Very little face visible - the person is looking away to the left. '
            'Mostly the back and right side of the head visible.'
        )
    },
    {
        'angle': 270,
        'name': 'Left View',
        'short': 'Left',
        'description': (
            'The person faces directly to the LEFT of the image. Perfect profile view. '
            'The nose points to the LEFT edge of the image. '
            'We see ONLY the RIGHT side of the face. The RIGHT ear is fully visible. '
            'The left ear is completely hidden behind the head. '
            'This is a right-side profile shot with the person looking left.'
        )
    },
    {
        'angle': 315,
        'name': 'Left Front Oblique',
        'short': 'L-Front',
        'description': (
            'The person has turned their head 45 degrees to THEIR LEFT (toward the LEFT side of the image). '
            'The nose points toward the LEFT side of the image. '
            'We see more of the RIGHT side of the persons face (right cheek, right ear visible). '
            'The persons RIGHT ear is clearly visible. The left side of the face is foreshortened.'
        )
    }
]


def build_front_view_prompt(description):
    """Build a special prompt for generating the front view (0°) from any input angle.
    Uses the detected viewing_angle to explicitly instruct the rotation needed."""
    hair_desc = description.get('hair', 'current hairstyle')
    face_desc = description.get('face', 'current facial features')
    clothing_desc = description.get('clothing', 'current clothing')
    background_desc = description.get('background', 'studio background')
    skin_desc = description.get('skin', 'current skin tone')
    viewing_angle = description.get('viewing_angle', 'unknown angle')
    
    return (
        f"The reference image shows a person from this angle: {viewing_angle}.\n\n"
        f"Generate the EXACT same person but rotated to face the camera DIRECTLY - a perfect FRONT VIEW.\n\n"
        f"ABSOLUTE REQUIREMENTS FOR FRONT VIEW:\n"
        f"- The person must face the camera STRAIGHT ON\n"
        f"- The face must be PERFECTLY SYMMETRICAL in the image\n"
        f"- BOTH eyes must be fully visible and equidistant from center\n"
        f"- The nose must point DIRECTLY at the camera (toward the viewer)\n"
        f"- BOTH ears should be equally visible on each side\n"
        f"- The head should NOT be turned to the left or right AT ALL\n\n"
        f"CRITICAL FRAMING: Head-and-shoulders portrait, subject centered in frame. "
        f"Head positioned in upper-center of canvas with consistent size. "
        f"Show from mid-chest up. Face/head must occupy the same proportion of the canvas.\n\n"
        f"Keep ALL of these IDENTICAL to the reference:\n"
        f"- Facial features: {face_desc}\n"
        f"- Hair: {hair_desc}\n"
        f"- Skin tone: {skin_desc}\n"
        f"- Clothing: {clothing_desc}\n"
        f"- Background: {background_desc}\n"
        f"- Lighting: professional studio lighting, same direction and intensity\n\n"
        f"This is the FRONT VIEW - the person looks directly at the camera with a neutral expression."
    )


def build_turntable_prompt(view_info, description):
    """Build a rotation prompt for a specific turntable view.
    The prompt uses ABSOLUTE positioning (not relative to reference) to avoid
    angle drift when the reference image is not a perfect front view.
    
    Args:
        view_info: dict with 'angle', 'name', 'short', 'description' keys
        description: dict with person attributes from image analysis
    """
    hair_desc = description.get('hair', 'current hairstyle')
    face_desc = description.get('face', 'current facial features')
    clothing_desc = description.get('clothing', 'current clothing')
    background_desc = description.get('background', 'studio background')
    skin_desc = description.get('skin', 'current skin tone')
    
    view_name = view_info['name']
    view_desc = view_info['description']
    angle = view_info['angle']
    
    # Consistent framing instruction for ALL angles
    framing = (
        "CRITICAL FRAMING: Head-and-shoulders portrait, subject centered in frame. "
        "Head positioned in upper-center of canvas with consistent size. "
        "Show from mid-chest up. Same zoom level and crop as reference image. "
        "Face/head must occupy the same proportion of the canvas in every image."
    )
    
    # Build the identity features list
    identity = (
        f"Keep ALL of these IDENTICAL across every angle:\n"
        f"- Facial features: {face_desc}\n"
        f"- Hair: {hair_desc}\n"
        f"- Skin tone: {skin_desc}\n"
        f"- Clothing: {clothing_desc}\n"
        f"- Background: {background_desc}\n"
        f"- Lighting: professional studio lighting, same direction and intensity"
    )
    
    return (
        f"The reference image shows this person from a FRONT VIEW (facing the camera directly).\n\n"
        f"Now generate the EXACT same person but at this ABSOLUTE angle:\n"
        f"VIEW: {view_name} ({angle} degrees from front)\n\n"
        f"EXACT POSE DESCRIPTION: {view_desc}\n\n"
        f"{framing}\n\n"
        f"{identity}\n\n"
        f"IMPORTANT DIRECTION GUIDE: "
        f"'RIGHT side of the image' means the right edge of the picture as the viewer sees it. "
        f"'LEFT side of the image' means the left edge of the picture as the viewer sees it. "
        f"If the description says 'nose points to the RIGHT of the image', the nose must literally point toward the right edge of the picture. "
        f"If it says 'LEFT ear is visible', the person's own left ear (which appears on the RIGHT side of the image when facing right) must be visible.\n\n"
        f"The reference shows the FRONT VIEW. You must rotate the person to the exact angle described above. "
        f"Maintain perfect consistency - same person, same clothes, same background, different angle."
    )


def analyze_image_for_turntable(image_path):
    """Use Gemini to analyze the after-image and extract person description for consistent turntable generation."""
    import traceback as tb
    
    input_image = Image.open(image_path)
    analysis_prompt = (
        "Analyze this portrait photo and provide a brief, precise description of the following attributes. "
        "Return ONLY a JSON object with these keys: hair, face, skin, clothing, background, viewing_angle. "
        "Each value should be a short descriptive phrase (10-20 words max) that could be used in an image generation prompt. "
        "For viewing_angle, describe what angle the person is viewed from (e.g., 'front view', 'three-quarter left view', 'right profile', etc.). "
        "Example format: {\"hair\": \"short dark brown hair with natural texture\", \"face\": \"oval face with defined jawline, brown eyes, short stubble beard\", "
        "\"skin\": \"light olive skin tone\", \"clothing\": \"navy blue crew neck t-shirt\", \"background\": \"light gray studio background\", "
        "\"viewing_angle\": \"front view facing camera\"}"
    )
    
    if not gemini_client:
        raise ValueError('Gemini API not configured. Set GEMINI_API_KEY.')
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"[Analysis] Attempt {attempt + 1}/{max_retries}...")
            response = gemini_client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=[analysis_prompt, input_image],
                config=types.GenerateContentConfig(
                    response_modalities=['TEXT'],
                    safety_settings=[
                        types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                    ]
                )
            )
            
            # Parse the JSON response
            text = response.text.strip()
            print(f"[Analysis] Raw response: {text[:300]}")
            
            # Remove markdown code block if present
            if text.startswith('```'):
                text = text.split('\n', 1)[1] if '\n' in text else text[3:]
                if text.endswith('```'):
                    text = text[:-3]
                text = text.strip()
                if text.startswith('json'):
                    text = text[4:].strip()
            
            description = json.loads(text)
            print(f"[Analysis] Successfully parsed description")
            return description
            
        except Exception as e:
            error_trace = tb.format_exc()
            print(f"[Analysis] Attempt {attempt + 1} failed: {e}")
            print(f"[Analysis] Traceback: {error_trace}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 3
                print(f"[Analysis] Retrying in {wait_time}s...")
                time_module.sleep(wait_time)
    
    # Return generic description as fallback after all retries
    print(f"[Analysis] All retries failed, using fallback description")
    return {
        'hair': 'same hairstyle as reference',
        'face': 'same facial features as reference',
        'skin': 'same skin tone',
        'clothing': 'same clothing as reference',
        'background': 'same studio background',
        'viewing_angle': 'unknown'
    }


def increment_usage_for_turntable(user_token, model_used=GEMINI_IMAGE_MODEL):
    """Deduct a turntable-view cost for the model that generated the image."""
    if not user_token:
        return False
    success, data = deduct_credits(
        action='turntable_view',
        token=user_token,
        raw_cost_usd=get_image_generation_raw_cost(model_used),
        description=f'Turntable view generation ({model_used})'
    )
    if success:
        logger.info(f"[Billing] turntable_view deduction OK: {data.get('credits_deducted', '?')} credits")
    else:
        logger.warning(f"[Billing] turntable_view deduction FAILED: {data}")
    return success


def _call_gemini_with_retry(prompt, image, max_retries=3, response_modalities=None):
    """Generate a turntable image through the shared Pro → Flash → Pro policy.

    ``max_retries`` remains in the signature for backward compatibility; the
    shared policy owns the approved three-attempt model sequence.
    Returns (image_result, error_message, model_used).
    """
    if response_modalities is None:
        response_modalities = ['TEXT', 'IMAGE']

    if not gemini_client:
        return None, 'Gemini API not configured. Set GEMINI_API_KEY.', None

    config_kwargs = {
        'response_modalities': response_modalities,
        'safety_settings': [
            types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
            types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
        ],
    }
    if 'IMAGE' in response_modalities:
        config_kwargs['image_config'] = types.ImageConfig(image_size=GEMINI_IMAGE_OUTPUT_SIZE)

    try:
        response, model_used = generate_gemini_image_content(
            contents=[prompt, image],
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as error:
        logger.warning('[Turntable] Gemini image request failed: %s', type(error).__name__)
        return None, str(error), None

    if response_modalities == ['TEXT']:
        return response, None, model_used

    parts = None
    if hasattr(response, 'parts') and response.parts:
        parts = response.parts
    elif hasattr(response, 'candidates') and response.candidates:
        candidate = response.candidates[0]
        if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
            parts = candidate.content.parts

    result_image = extract_generated_image(parts)
    if result_image is not None:
        print(f"  [Gemini] Success - image generated with {model_used}")
        return result_image, None, model_used
    return None, 'No image in response', model_used


def generate_turntable_images_thread(session_id, after_image_path, turntable_folder, user_token=None):
    """Background thread to generate 8 turntable images.
    
    Strategy:
    1. Analyze the after-image to extract person description and detect viewing angle
    2. Generate the Front View (0°) image FIRST regardless of original angle
    3. Use the front-view image as the primary reference for all subsequent angles
    4. Generate remaining 7 images sequentially
    5. Deduct 1 credit per successfully generated image (8 total)
    """
    import traceback as tb
    total_views = len(TURNTABLE_VIEWS)  # 8
    
    try:
        print(f"\n{'='*60}")
        print(f"[Turntable] Starting generation for session: {session_id}")
        print(f"[Turntable] After image path: {after_image_path}")
        print(f"[Turntable] Path exists: {os.path.exists(after_image_path)}")
        print(f"[Turntable] Absolute path: {os.path.abspath(after_image_path)}")
        print(f"{'='*60}")
        
        turntable_sessions[session_id]['status'] = 'analyzing'
        
        # Verify the image file exists and is readable
        if not os.path.exists(after_image_path):
            # Try absolute path
            abs_path = os.path.abspath(after_image_path)
            if os.path.exists(abs_path):
                after_image_path = abs_path
                print(f"[Turntable] Using absolute path: {abs_path}")
            else:
                raise FileNotFoundError(f"After image not found at: {after_image_path} or {abs_path}")
        
        # Step 1: Analyze the after-image to get consistent description
        print(f"[Turntable] Step 1: Analyzing image...")
        description = analyze_image_for_turntable(after_image_path)
        print(f"[Turntable] Analysis result: {json.dumps(description, indent=2)[:500]}")
        turntable_sessions[session_id]['description'] = description
        turntable_sessions[session_id]['status'] = 'generating'
        turntable_sessions[session_id]['total'] = total_views
        
        # Load the original after-image
        original_image = Image.open(after_image_path)
        print(f"[Turntable] Original image loaded: {original_image.size}, mode={original_image.mode}")
        
        # Step 2: Generate the FRONT VIEW (0°) first
        front_view_info = TURNTABLE_VIEWS[0]  # Front View at 0°
        turntable_sessions[session_id]['current_angle'] = 0
        turntable_sessions[session_id]['current_view'] = front_view_info['name']
        turntable_sessions[session_id]['completed'] = 0
        
        print(f"[Turntable] Step 2: Generating Front View (0°)...")
        front_view_prompt = build_front_view_prompt(description)
        
        front_view_image, front_error, front_model_used = _call_gemini_with_retry(
            front_view_prompt, original_image
        )
        
        # Save front view
        img_filename = f"{session_id}_angle_000.png"
        img_path = os.path.join(turntable_folder, img_filename)
        generated_images = []
        
        if front_view_image:
            front_view_image.save(img_path)
            print(f"[Turntable] Front view generated and saved: {img_path}")
        else:
            # Fallback: use original image for front view
            original_image.save(img_path)
            print(f"[Turntable] Front view FALLBACK (using original): {front_error}")
        
        generated_images.append({
            'angle': 0,
            'name': front_view_info['name'],
            'short': front_view_info['short'],
            'filename': img_filename,
            'url': f'/static/turntable/{img_filename}'
        })
        turntable_sessions[session_id]['completed'] = 1
        turntable_sessions[session_id]['images'] = list(generated_images)  # Update images progressively
        
        # Deduct 1 credit for front view generation
        increment_usage_for_turntable(user_token, front_model_used or GEMINI_IMAGE_MODEL)
        turntable_sessions[session_id]['credits_used'] = 1
        
        # Step 3: Load the front view as the PRIMARY reference for all other angles
        ref_image = Image.open(img_path)
        print(f"[Turntable] Reference image loaded: {ref_image.size}")
        
        time_module.sleep(5)  # Longer delay between turntable calls to avoid rate limiting
        
        # Step 4: Generate remaining 7 images
        for i, view_info in enumerate(TURNTABLE_VIEWS[1:], start=1):
            angle = view_info['angle']
            print(f"\n[Turntable] Step 4.{i}: Generating {view_info['name']} ({angle}°)...")
            
            turntable_sessions[session_id]['current_angle'] = angle
            turntable_sessions[session_id]['current_view'] = view_info['name']
            
            try:
                prompt = build_turntable_prompt(view_info, description)
                
                result_image, gen_error, model_used = _call_gemini_with_retry(prompt, ref_image)
                
                img_filename = f"{session_id}_angle_{angle:03d}.png"
                img_path = os.path.join(turntable_folder, img_filename)
                
                if result_image:
                    result_image.save(img_path)
                    print(f"[Turntable] {view_info['name']} generated and saved")
                else:
                    # Fallback: use front view reference
                    ref_image.save(img_path)
                    print(f"[Turntable] {view_info['name']} FALLBACK (using ref): {gen_error}")
                
                generated_images.append({
                    'angle': angle,
                    'name': view_info['name'],
                    'short': view_info['short'],
                    'filename': img_filename,
                    'url': f'/static/turntable/{img_filename}'
                })
                
                # Update progress after each successful generation
                turntable_sessions[session_id]['completed'] = i + 1
                turntable_sessions[session_id]['images'] = list(generated_images)  # Update progressively
                
                # Deduct 1 credit for this image generation
                increment_usage_for_turntable(user_token, model_used or GEMINI_IMAGE_MODEL)
                turntable_sessions[session_id]['credits_used'] = turntable_sessions[session_id].get('credits_used', 0) + 1
                
                # Delay to avoid rate limiting (longer between requests)
                time_module.sleep(5)
                
            except Exception as e:
                error_trace = tb.format_exc()
                print(f"[Turntable] ERROR generating {view_info['name']} ({angle}°): {e}")
                print(f"[Turntable] Traceback: {error_trace}")
                # Use front view reference as fallback
                img_filename = f"{session_id}_angle_{angle:03d}.png"
                img_path = os.path.join(turntable_folder, img_filename)
                ref_image.save(img_path)
                generated_images.append({
                    'angle': angle,
                    'name': view_info['name'],
                    'short': view_info['short'],
                    'filename': img_filename,
                    'url': f'/static/turntable/{img_filename}'
                })
                turntable_sessions[session_id]['completed'] = i + 1
                turntable_sessions[session_id]['images'] = list(generated_images)
        
        turntable_sessions[session_id]['status'] = 'complete'
        turntable_sessions[session_id]['completed'] = total_views
        turntable_sessions[session_id]['images'] = generated_images
        
        # Persist completed session for sharing
        persist_turntable_session(session_id, turntable_sessions[session_id])
        
        print(f"\n{'='*60}")
        print(f"[Turntable] COMPLETE - Generated {len(generated_images)} images for session {session_id}")
        print(f"{'='*60}\n")
        
    except Exception as e:
        error_trace = tb.format_exc()
        print(f"\n{'='*60}")
        print(f"[Turntable] FATAL ERROR for session {session_id}: {e}")
        print(f"[Turntable] Full traceback:\n{error_trace}")
        print(f"{'='*60}\n")
        turntable_sessions[session_id]['status'] = 'error'
        turntable_sessions[session_id]['error'] = str(e)


@app.route('/generate-turntable', methods=['POST'])
@login_required
def generate_turntable():
    """Start 360° turntable image generation in the background."""
    data = request.json
    after_image_url = data.get('afterImageUrl')
    
    if not after_image_url:
        return jsonify({'error': 'No after image provided'}), 400
    
    # Check if user has enough credits (8 required for turntable)
    can_generate, usage_msg, usage_data, remaining = check_usage_for_turntable(required_credits=8)
    if not can_generate:
        return jsonify({
            'error': f'Insufficient credits for 360° turntable. {usage_msg}',
            'limitReached': True,
            'creditsNeeded': 8,
            'creditsAvailable': remaining
        }), 403
    
    # Get the file path from the URL
    after_image_path = '.' + after_image_url
    if not os.path.exists(after_image_path):
        return jsonify({'error': 'After image not found'}), 404
    
    # Get user token for credit deduction in background thread
    user_token = session.get('user', {}).get('token')
    
    # Create a unique session ID
    session_id = uuid.uuid4().hex
    turntable_folder = app.config['TURNTABLE_FOLDER']
    os.makedirs(turntable_folder, exist_ok=True)
    
    # Get before/after image URLs and graft summary from request
    before_image_url = data.get('beforeImageUrl', '')
    graft_summary = data.get('graftSummary', None)
    
    # Initialize session
    turntable_sessions[session_id] = {
        'status': 'starting',
        'completed': 0,
        'total': len(TURNTABLE_VIEWS),
        'current_angle': 0,
        'current_view': '',
        'images': [],
        'credits_used': 0,
        'error': None,
        'before_image': before_image_url,
        'after_image': after_image_url,
        'graft_summary': graft_summary
    }
    
    # Start background generation thread (pass user_token for credit deduction)
    thread = threading.Thread(
        target=generate_turntable_images_thread,
        args=(session_id, after_image_path, turntable_folder, user_token)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'sessionId': session_id,
        'creditsToBeUsed': 8
    })


@app.route('/turntable-progress/<session_id>', methods=['GET'])
@login_required
def turntable_progress(session_id):
    """Get the progress of turntable generation."""
    if session_id not in turntable_sessions:
        return jsonify({'error': 'Session not found'}), 404
    
    session_data = turntable_sessions[session_id]
    
    return jsonify({
        'status': session_data['status'],
        'completed': session_data['completed'],
        'total': session_data['total'],
        'currentAngle': session_data.get('current_angle', 0),
        'currentView': session_data.get('current_view', ''),
        'images': session_data.get('images', []),
        'creditsUsed': session_data.get('credits_used', 0),
        'error': session_data.get('error')
    })



# ============================================
# Unified Share System (Before/After and/or Turntable)
# ============================================

@app.route('/api/create-share', methods=['POST'])
@login_required
def create_share():
    """Create a shareable link for before/after results, optionally including turntable images."""
    try:
        data = request.json
        before_image = data.get('beforeImage', '')
        after_image = data.get('afterImage', '')
        graft_summary = data.get('graftSummary', None)
        turntable_session_id = data.get('turntableSessionId', None)
        
        if not before_image or not after_image:
            return jsonify({'error': 'Before and after images are required'}), 400
        
        # Generate a unique share ID
        share_id = uuid.uuid4().hex[:12]
        
        # Build share data
        share_data = {
            'before_image': before_image,
            'after_image': after_image,
            'graft_summary': graft_summary,
            'created_at': datetime.now().isoformat(),
            'share_type': 'before_after',  # default
            'turntable_images': []
        }
        
        # If turntable session ID provided, include turntable images
        if turntable_session_id:
            # Check in-memory first
            tt_session = turntable_sessions.get(turntable_session_id)
            if tt_session and tt_session.get('status') == 'complete':
                share_data['turntable_images'] = tt_session.get('images', [])
                share_data['share_type'] = 'full_360'
            else:
                # Check persisted sessions
                persisted_tt = load_persisted_turntable_sessions()
                if turntable_session_id in persisted_tt:
                    share_data['turntable_images'] = persisted_tt[turntable_session_id].get('images', [])
                    share_data['share_type'] = 'full_360'
        
        # Save to shares file
        shares = load_shares()
        shares[share_id] = share_data
        save_shares(shares)
        
        share_url = build_public_share_url(share_id)

        return jsonify({
            'success': True,
            'shareId': share_id,
            'shareUrl': share_url,
            'shareType': share_data['share_type'],
            'isPublic': True
        })
    except Exception as e:
        import traceback
        print(f"Create share error: {traceback.format_exc()}")
        return jsonify({'error': f'Failed to create share: {str(e)}'}), 500


def _absolute_asset_url(path):
    """Convert a relative /static/... path into an absolute https URL using the
    current request host (ProxyFix ensures this is the real public host).
    Already-absolute URLs are returned unchanged.
    """
    if not path:
        return ''
    if path.startswith('http://') or path.startswith('https://'):
        return path
    base = PUBLIC_BASE_URL or request.host_url.rstrip('/')
    if not path.startswith('/'):
        path = '/' + path
    return f"{base}{path}"


@app.route('/shared/<share_id>')
def view_share(share_id):
    """Public (no login required) page to view a shared result.

    This route is explicitly excluded from the global auth gate via
    PUBLIC_PATH_PREFIXES above, and sets permissive CORS/cache headers so that
    social-media link-unfurl crawlers (WhatsApp, X, Facebook, iMessage, etc.)
    can fetch it without any session cookie.
    """
    shares = load_shares()

    if share_id not in shares:
        resp = make_response(render_template('shared_results.html', error=True,
                             before_image='', after_image='',
                             turntable_images=[], graft_summary=None,
                             share_type='before_after', share_id=share_id))
        resp.status_code = 404
        resp.headers['Cache-Control'] = 'no-store'
        resp.headers['X-Robots-Tag'] = 'noindex'
        return resp

    share_data = shares[share_id]

    # Build absolute URLs for the before/after images so OG:image works on
    # social previews and links work even when embedded in other apps.
    before_abs = _absolute_asset_url(share_data.get('before_image', ''))
    after_abs = _absolute_asset_url(share_data.get('after_image', ''))
    tt_images = []
    for img in share_data.get('turntable_images', []) or []:
        if isinstance(img, dict):
            new_img = dict(img)
            if 'url' in new_img:
                new_img['url'] = _absolute_asset_url(new_img['url'])
            tt_images.append(new_img)

    resp = make_response(render_template('shared_results.html',
                         error=False,
                         before_image=before_abs,
                         after_image=after_abs,
                         turntable_images=tt_images,
                         graft_summary=share_data.get('graft_summary', None),
                         share_type=share_data.get('share_type', 'before_after'),
                         share_id=share_id))
    # Public caching for crawlers, but short-lived so revocation propagates fast.
    resp.headers['Cache-Control'] = 'public, max-age=120'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return resp


@app.route('/api/shared/<share_id>')
def shared_data_api(share_id):
    """Public JSON API for a shared result (no login required)."""
    shares = load_shares()

    if share_id not in shares:
        resp = jsonify({'error': 'Share not found or has been revoked by its owner.'})
        resp.status_code = 404
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Cache-Control'] = 'no-store'
        return resp

    share_data = shares[share_id]

    resp = jsonify({
        'success': True,
        'beforeImage': _absolute_asset_url(share_data.get('before_image', '')),
        'afterImage': _absolute_asset_url(share_data.get('after_image', '')),
        'turntableImages': [
            {**(img if isinstance(img, dict) else {}),
             'url': _absolute_asset_url((img or {}).get('url', ''))}
            for img in (share_data.get('turntable_images') or [])
        ],
        'graftSummary': share_data.get('graft_summary', None),
        'shareType': share_data.get('share_type', 'before_after'),
        'isPublic': True
    })
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Cache-Control'] = 'public, max-age=120'
    return resp


# Legacy route: redirect old turntable share links to new system
@app.route('/shared/turntable/<session_id>')
def shared_turntable_legacy(session_id):
    """Legacy support: redirect old turntable share URLs. Check if it exists in new shares or old turntable sessions."""
    # Check if this session_id exists in the new shares system
    shares = load_shares()
    if session_id in shares:
        return redirect(url_for('view_share', share_id=session_id))
    
    # Check old turntable sessions and auto-migrate
    session_data = turntable_sessions.get(session_id)
    if not session_data or session_data.get('status') != 'complete':
        persisted = load_persisted_turntable_sessions()
        session_data = persisted.get(session_id)
    
    if session_data:
        # Auto-migrate to new share system
        share_data = {
            'before_image': session_data.get('before_image', ''),
            'after_image': session_data.get('after_image', ''),
            'graft_summary': session_data.get('graft_summary', None),
            'created_at': session_data.get('created_at', datetime.now().isoformat()),
            'share_type': 'full_360' if session_data.get('images') else 'before_after',
            'turntable_images': session_data.get('images', [])
        }
        shares[session_id] = share_data
        save_shares(shares)
        return redirect(url_for('view_share', share_id=session_id))
    
    # Not found
    return render_template('shared_results.html', error=True,
                         before_image='', after_image='',
                         turntable_images=[], graft_summary=None,
                         share_type='before_after', share_id=session_id)


# ============================================
# Manage Shared Links API
# ============================================

@app.route('/api/list-shares', methods=['GET'])
@login_required
def list_shares():
    """Return all shares for the manage panel."""
    try:
        shares = load_shares()
        result = []
        for share_id, data in shares.items():
            turntable_imgs = data.get('turntable_images', [])
            thumbnail = turntable_imgs[0].get('url', '') if turntable_imgs else ''
            
            result.append({
                'shareId': share_id,
                'createdAt': data.get('created_at', ''),
                'thumbnail': thumbnail,
                'isPublic': True,
                'beforeImage': data.get('before_image', ''),
                'afterImage': data.get('after_image', ''),
                'turntableCount': len(turntable_imgs),
                'shareType': data.get('share_type', 'before_after'),
                'shareUrl': build_public_share_url(share_id),
                'graftSummary': data.get('graft_summary', None)
            })
        
        # Sort by creation date, newest first
        result.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        
        return jsonify({'success': True, 'shares': result})
    except Exception as e:
        import traceback
        print(f"List shares error: {traceback.format_exc()}")
        return jsonify({'error': f'Failed to list shares: {str(e)}'}), 500


@app.route('/api/delete-share/<share_id>', methods=['DELETE'])
@login_required
def delete_share(share_id):
    """Delete a share and optionally clean up turntable images from disk."""
    try:
        shares = load_shares()
        images_to_delete = []
        
        if share_id in shares:
            share_data = shares[share_id]
            # Collect turntable image file paths for cleanup
            for img in share_data.get('turntable_images', []):
                img_url = img.get('url', '')
                if img_url:
                    img_path = '.' + img_url
                    if os.path.exists(img_path):
                        images_to_delete.append(img_path)
            
            del shares[share_id]
            save_shares(shares)
        
        # Also remove from old turntable sessions if present
        if share_id in turntable_sessions:
            del turntable_sessions[share_id]
        persisted_tt = load_persisted_turntable_sessions()
        if share_id in persisted_tt:
            del persisted_tt[share_id]
            os.makedirs(os.path.dirname(TURNTABLE_DATA_FILE), exist_ok=True)
            with open(TURNTABLE_DATA_FILE, 'w') as f:
                json.dump(persisted_tt, f)
        
        # Delete the actual image files
        deleted_count = 0
        for img_path in images_to_delete:
            try:
                os.remove(img_path)
                deleted_count += 1
            except Exception:
                pass
        
        return jsonify({
            'success': True,
            'message': f'Share deleted successfully. Cleaned up {deleted_count} image files.',
            'deletedImages': deleted_count
        })
    except Exception as e:
        import traceback
        print(f"Delete share error: {traceback.format_exc()}")
        return jsonify({'error': f'Failed to delete share: {str(e)}'}), 500


# ============================================
# Per-User Cost Settings
# ============================================

@app.route('/api/cost-settings', methods=['GET'])
@login_required
def get_cost_settings():
    """Return the current user's cost tier configuration (or defaults)."""
    user = session.get('user', {})
    user_id = str(user.get('id', ''))
    all_settings = load_user_cost_settings()
    user_data = all_settings.get(user_id, DEFAULT_COST_TIERS) if user_id else DEFAULT_COST_TIERS
    # Handle new dict format {tiers: [...], _pin_hash: '...'}
    if isinstance(user_data, dict):
        tiers = user_data.get('tiers', DEFAULT_COST_TIERS)
    else:
        tiers = user_data
    return jsonify({'tiers': tiers, 'isCustom': user_id in all_settings})


@app.route('/api/cost-settings', methods=['POST'])
@login_required
def save_cost_settings():
    """Save the current user's cost tier configuration."""
    user = session.get('user', {})
    user_id = str(user.get('id', ''))
    if not user_id:
        return jsonify({'error': 'User ID not found in session'}), 400
    data = request.get_json()
    tiers = data.get('tiers')
    if not isinstance(tiers, list) or len(tiers) != 6:
        return jsonify({'error': 'Invalid tiers: must be a list of 6 tier objects'}), 400
    # Validate each tier
    for i, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            return jsonify({'error': f'Tier {i+1} is not an object'}), 400
        # Each tier must have either fixed (last tier) or min+max
        has_fixed = tier.get('fixed') is not None
        has_range = tier.get('min') is not None and tier.get('max') is not None
        if not has_fixed and not has_range:
            return jsonify({'error': f'Tier {i+1} must have either a fixed price or a min/max range'}), 400
    all_settings = load_user_cost_settings()
    all_settings[user_id] = tiers
    save_user_cost_settings(all_settings)
    return jsonify({'success': True, 'message': 'Cost settings saved successfully'})


@app.route('/api/cost-settings/reset', methods=['POST'])
@login_required
def reset_cost_settings():
    """Reset the current user's cost settings to defaults."""
    user = session.get('user', {})
    user_id = str(user.get('id', ''))
    if not user_id:
        return jsonify({'error': 'User ID not found in session'}), 400
    all_settings = load_user_cost_settings()
    if user_id in all_settings:
        del all_settings[user_id]
        save_user_cost_settings(all_settings)
    return jsonify({'success': True, 'tiers': DEFAULT_COST_TIERS})


# ============================================
# Pricing Config Page (PIN-protected hidden URL)
# ============================================

def _pin_hash(pin: str) -> str:
    """Return a SHA-256 hex digest of the PIN string."""
    return hashlib.sha256(pin.strip().encode('utf-8')).hexdigest()

@app.route('/pricing', methods=['GET'])
@app.route('/pricing-config', methods=['GET'])
@login_required
def pricing_config_page():
    """Hidden PIN-protected page for practitioners to configure their cost tiers."""
    user = session.get('user', {})
    user_id = str(user.get('id', ''))
    all_settings = load_user_cost_settings()
    user_data = all_settings.get(user_id, {})
    has_pin = isinstance(user_data, dict) and bool(user_data.get('_pin_hash'))
    # Check if PIN already verified this session
    pin_verified = session.get(f'pricing_pin_verified_{user_id}', False)
    # Load current tiers
    tiers = user_data.get('tiers', DEFAULT_COST_TIERS) if isinstance(user_data, dict) else DEFAULT_COST_TIERS
    return render_template('pricing_config.html',
                           user=user,
                           has_pin=has_pin,
                           pin_verified=pin_verified,
                           tiers=tiers,
                           default_tiers=DEFAULT_COST_TIERS)

@app.route('/api/pricing-config/verify-pin', methods=['POST'])
@login_required
def pricing_verify_pin():
    """Verify the PIN for the pricing config page."""
    user = session.get('user', {})
    user_id = str(user.get('id', ''))
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json() or {}
    pin = str(data.get('pin', '')).strip()
    if not pin:
        return jsonify({'error': 'PIN is required'}), 400
    all_settings = load_user_cost_settings()
    user_data = all_settings.get(user_id, {})
    if not isinstance(user_data, dict):
        # Migrate old list format to new dict format
        user_data = {'tiers': user_data}
    stored_hash = user_data.get('_pin_hash', '')
    if not stored_hash:
        return jsonify({'error': 'No PIN set. Please set a PIN first.'}), 400
    if _pin_hash(pin) != stored_hash:
        return jsonify({'error': 'Incorrect PIN. Please try again.'}), 403
    session[f'pricing_pin_verified_{user_id}'] = True
    return jsonify({'success': True})

@app.route('/api/pricing-config/set-pin', methods=['POST'])
@login_required
def pricing_set_pin():
    """Set or change the PIN for the pricing config page."""
    user = session.get('user', {})
    user_id = str(user.get('id', ''))
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401
    data = request.get_json() or {}
    pin = str(data.get('pin', '')).strip()
    if len(pin) < 4:
        return jsonify({'error': 'PIN must be at least 4 digits'}), 400
    if not pin.isdigit():
        return jsonify({'error': 'PIN must contain digits only'}), 400
    all_settings = load_user_cost_settings()
    user_data = all_settings.get(user_id, {})
    if not isinstance(user_data, dict):
        # Migrate old list format
        user_data = {'tiers': user_data}
    user_data['_pin_hash'] = _pin_hash(pin)
    all_settings[user_id] = user_data
    save_user_cost_settings(all_settings)
    session[f'pricing_pin_verified_{user_id}'] = True
    return jsonify({'success': True})

@app.route('/api/pricing-config/save', methods=['POST'])
@login_required
def pricing_config_save():
    """Save cost tiers from the pricing config page (PIN must be verified this session)."""
    user = session.get('user', {})
    user_id = str(user.get('id', ''))
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401
    if not session.get(f'pricing_pin_verified_{user_id}', False):
        return jsonify({'error': 'PIN verification required'}), 403
    data = request.get_json() or {}
    tiers = data.get('tiers')
    if not isinstance(tiers, list) or len(tiers) != 6:
        return jsonify({'error': 'Invalid tiers: must be a list of 6 tier objects'}), 400
    for i, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            return jsonify({'error': f'Tier {i+1} is not an object'}), 400
        has_fixed = tier.get('fixed') is not None
        has_range = tier.get('min') is not None and tier.get('max') is not None
        if not has_fixed and not has_range:
            return jsonify({'error': f'Tier {i+1} must have either a fixed price or a min/max range'}), 400
    all_settings = load_user_cost_settings()
    user_data = all_settings.get(user_id, {})
    if not isinstance(user_data, dict):
        user_data = {}
    user_data['tiers'] = tiers
    all_settings[user_id] = user_data
    save_user_cost_settings(all_settings)
    return jsonify({'success': True, 'message': 'Pricing saved successfully'})

@app.route('/api/pricing-config/reset', methods=['POST'])
@login_required
def pricing_config_reset():
    """Reset cost tiers to defaults (PIN must be verified this session)."""
    user = session.get('user', {})
    user_id = str(user.get('id', ''))
    if not user_id:
        return jsonify({'error': 'Not authenticated'}), 401
    if not session.get(f'pricing_pin_verified_{user_id}', False):
        return jsonify({'error': 'PIN verification required'}), 403
    all_settings = load_user_cost_settings()
    user_data = all_settings.get(user_id, {})
    if not isinstance(user_data, dict):
        user_data = {}
    user_data['tiers'] = DEFAULT_COST_TIERS
    all_settings[user_id] = user_data
    save_user_cost_settings(all_settings)
    return jsonify({'success': True, 'tiers': DEFAULT_COST_TIERS})

# ============================================
# Voice Command AI System
# ============================================
@app.route('/api/voice-command', methods=['POST'])
@login_required
def voice_command():
    """Process a voice command using Gemini AI to interpret intent and return structured actions.
    This is an additive feature — it does not replace any existing functionality."""
    try:
        data = request.json
        transcript = data.get('transcript', '').strip()
        current_step = data.get('currentStep', 'upload')  # upload, options, results
        has_image = data.get('hasImage', False)
        uploaded_filename = data.get('uploadedFilename', None)
        current_selections = data.get('currentSelections', [])
        has_after_image = data.get('hasAfterImage', False)
        has_turntable = data.get('hasTurntable', False)
        
        if not transcript:
            return jsonify({'error': 'No voice command received'}), 400
        
        # Build context about available areas and densities for the AI
        areas_context = ""
        for area_key, area_info in AREA_INFO.items():
            if area_key == 'area7':  # Skip donor zone
                continue
            densities_available = []
            for d_key in ['full', 'moderate', 'camouflage']:
                if d_key in GRAFT_COUNTS.get(area_key, {}):
                    d_info = DENSITY_INFO[d_key]
                    grafts = GRAFT_COUNTS[area_key][d_key]
                    densities_available.append(f"{d_key} ({d_info['fu_per_cm2']} FU/cm², ~{grafts} grafts)")
            areas_context += f"- {area_key}: {area_info['name']} — {area_info['description'][:100]}... Densities: {', '.join(densities_available)}\n"
        
        # Build the AI prompt
        ai_prompt = f"""You are the voice assistant for FlowMediQ AI Hair Studio, a hair restoration simulation tool.
You understand commands in ANY language. The user may speak in English, Spanish, Hindi, Arabic, French, German, Portuguese, Chinese, Japanese, Korean, Turkish, Russian, Italian, or any other language. You MUST understand the intent regardless of language.

The user gave this voice command: "{transcript}"

Current app state:
- Current step: {current_step} (upload = photo upload page, options = area/density selection page, results = viewing generated results)
- Has uploaded image: {has_image}
- Has generated after image: {has_after_image}
- Has turntable images: {has_turntable}
- Current area selections: {json.dumps(current_selections) if current_selections else 'None'}

Available treatment areas and densities:
{areas_context}

You must respond with a JSON object (and NOTHING else) with these fields:

1. "intent": one of:
   - "smart_plan" — user wants AI to create/modify a treatment plan (e.g., "create a plan for maximum coverage", "age appropriate plan", "focus on the hairline", "use minimum grafts")
   - "navigate" — user wants to perform an app action (e.g., "upload photo", "next step", "go back", "generate", "download", "share", "start over", "generate turntable", "open camera", "take photo")
   - "unknown" — cannot understand the command

2. "action": (for navigate intent) one of:
   "upload_photo", "open_camera", "take_snapshot", "retake_photo", "rotate_photo", "use_camera_photo", "continue_to_options", "go_back", "generate_preview", "download_before", "download_after", "download_combined", "download_pdf", "share_results", "share_with_turntable", "generate_turntable", "start_over", "auto_rotate"
   Camera-related actions:
   - "open_camera" — user wants to open/start the camera (e.g., "open camera", "start camera", "turn on camera", "use camera")
   - "take_snapshot" — user wants to capture/take a photo from the camera (e.g., "take photo", "capture", "snap", "take snapshot", "cheese")
   - "retake_photo" — user wants to retake/redo the camera photo (e.g., "retake", "try again", "redo")
   - "rotate_photo" — user wants to rotate the captured photo to fix its orientation (e.g., "rotate", "rotate photo", "turn it", "it's sideways", "rotate clockwise", "fix orientation"). Only valid after a photo has been captured in the camera preview.
   - "use_camera_photo" — user wants to use/confirm the captured photo (e.g., "use this photo", "looks good", "confirm", "use it")

3. "selections": (for smart_plan intent) array of objects like:
   [{{"area": "area2", "density": "moderate"}}, {{"area": "area3", "density": "full"}}]
   Choose areas and densities based on the user's intent:
   - "maximum coverage" / "full coverage" → select all frontal areas (area1-area4) at full density, plus crown areas if mentioned
   - "age appropriate" / "natural" / "conservative" → select area2 and area3 at moderate density (younger patients may get area1 too)
   - "minimum grafts" / "least grafts" / "budget" → select only the most impactful areas (area2) at camouflage or moderate
   - "focus on hairline" → area1 and area2 at full or moderate
   - "focus on crown" → area5a, area5b, area6a, area6b at moderate or camouflage
   - "balanced plan" → area1, area2, area3 at moderate
   Use your judgment for any other natural language request.

4. "speech": A SHORT, concise spoken response (1-2 sentences max). Keep it brief and to the point.
   - For smart_plan: State the areas selected and total grafts in ONE sentence. Example: "Selected frontal hairline and mid-scalp at moderate density, total 2000 grafts. Shall I generate?"
   - For navigate: Confirm the action in a few words. Example: "Opening camera." or "Generating preview now."
   - For unknown: Brief clarification. Example: "Could you rephrase that?"
   - IMPORTANT: Respond in the SAME LANGUAGE the user spoke in.
   - Do NOT be verbose. Do NOT include disclaimers. Do NOT explain what each area means. Just state what you did concisely.

5. "requires_image_analysis": boolean — true if the command mentions analyzing the person's appearance (age, ethnicity, hair loss pattern, etc.)

6. "detected_language": the ISO 639-1 language code of the language the user spoke in (e.g., "en", "es", "hi", "ar", "fr", "de", "pt", "zh", "ja", "ko", "tr", "ru", "it")

IMPORTANT: Return ONLY valid JSON, no markdown, no explanation."""

        # If the command requires image analysis and we have an uploaded image
        requires_analysis = any(kw in transcript.lower() for kw in [
            'age', 'ethnic', 'him', 'her', 'this person', 'appropriate', 'suitable',
            'look at', 'analyze', 'assess', 'evaluate', 'his', 'for them', 'for this'
        ])
        
        contents = [ai_prompt]
        
        if requires_analysis and uploaded_filename:
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_filename)
            if os.path.exists(image_path):
                try:
                    input_image = Image.open(image_path)
                    contents.append(input_image)
                    # Enhance the prompt with image analysis request
                    contents[0] = ai_prompt + "\n\nIMPORTANT: An image of the person is attached. Analyze their age, ethnicity, and hair loss pattern to personalize your area/density selections. Keep the speech response SHORT — just state what you selected and total grafts."
                except Exception as e:
                    print(f"Error loading image for voice analysis: {e}")
        
        # Call Gemini
        if not gemini_client:
            return jsonify({'error': 'Gemini API not configured. Set GEMINI_API_KEY.'}), 500
        response = gemini_client.models.generate_content(
            model=GEMINI_VOICE_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=['TEXT'],
                temperature=0.3,
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                ]
            )
        )
        
        # Parse the response
        response_text = response.text.strip()
        
        # Clean up potential markdown wrapping
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.startswith('```'):
            response_text = response_text[3:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        result = json.loads(response_text)
        
        # Validate and enrich the response
        intent = result.get('intent', 'unknown')
        
        if intent == 'smart_plan' and 'selections' in result:
            # Calculate graft totals for each selection
            total_grafts = 0
            enriched_selections = []
            for sel in result['selections']:
                area = sel.get('area', '')
                density = sel.get('density', 'moderate')
                if area in GRAFT_COUNTS and density in GRAFT_COUNTS.get(area, {}):
                    grafts = GRAFT_COUNTS[area][density]
                    total_grafts += grafts
                    enriched_selections.append({
                        'area': area,
                        'density': density,
                        'areaName': AREA_INFO.get(area, {}).get('name', area),
                        'densityName': DENSITY_INFO.get(density, {}).get('name', density),
                        'fuPerCm2': DENSITY_INFO.get(density, {}).get('fu_per_cm2', ''),
                        'grafts': grafts
                    })
            result['selections'] = enriched_selections
            result['totalGrafts'] = total_grafts
        
        # Bill for voice command (Gemini NLP)
        try:
            vc_ok, vc_data = deduct_credits(
                action='voice_command',
                raw_cost_usd=ESTIMATED_RAW_COSTS_USD['voice_command'],
                description=f'Voice command NLP ({GEMINI_VOICE_MODEL})'
            )
            if vc_ok:
                logger.info(f"[Billing] voice_command deduction OK: {vc_data.get('credits_deducted', '?')} credits")
            else:
                logger.warning(f"[Billing] voice_command deduction FAILED: {vc_data}")
        except Exception as billing_err:
            logger.warning(f"[Billing] voice_command billing error: {billing_err}")

        return jsonify({
            'success': True,
            'intent': result.get('intent', 'unknown'),
            'action': result.get('action', None),
            'selections': result.get('selections', []),
            'totalGrafts': result.get('totalGrafts', 0),
            'speech': result.get('speech', 'I didn\'t quite understand that. Could you please rephrase?'),
            'requires_image_analysis': result.get('requires_image_analysis', False),
            'detected_language': result.get('detected_language', 'en')
        })
        
    except json.JSONDecodeError as e:
        print(f"Voice command JSON parse error: {e}")
        print(f"Raw response: {response_text}")
        return jsonify({
            'success': True,
            'intent': 'unknown',
            'speech': 'I had trouble understanding that command. Could you please try again?',
            'action': None,
            'selections': []
        })
    except Exception as e:
        import traceback
        print(f"Voice command error: {traceback.format_exc()}")
        return jsonify({'error': f'Voice command processing failed: {str(e)}'}), 500


# ============================================
# Gemini Neural TTS Endpoint
# ============================================
# ============================================
# TTS Audio Cache — stores generated audio in memory for instant replay
# ============================================
from openai import OpenAI as OpenAIClient

# Initialize OpenAI client for TTS
openai_tts_client = None
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
if OPENAI_API_KEY:
    openai_tts_client = OpenAIClient(
        api_key=OPENAI_API_KEY,
        base_url='https://api.openai.com/v1'
    )
    print("[TTS] OpenAI TTS client initialized")
else:
    print("[TTS] WARNING: OPENAI_API_KEY not set, TTS will not work")

# Valid OpenAI TTS voices
OPENAI_TTS_VOICES = ['alloy', 'ash', 'ballad', 'coral', 'echo', 'fable', 'nova', 'onyx', 'sage', 'shimmer', 'verse', 'marin', 'cedar']
DEFAULT_TTS_VOICE = 'coral'  # Warm, professional voice

# Map language codes to TTS instructions
LANG_INSTRUCTIONS = {
    'en': 'Speak in a professional, warm, and clear tone suitable for a medical hair restoration application.',
    'es': 'Habla en un tono profesional, c\u00e1lido y claro, adecuado para una aplicaci\u00f3n m\u00e9dica de restauraci\u00f3n capilar.',
    'fr': 'Parlez d\'un ton professionnel, chaleureux et clair, adapt\u00e9 \u00e0 une application m\u00e9dicale de restauration capillaire.',
    'de': 'Sprechen Sie in einem professionellen, warmen und klaren Ton, der f\u00fcr eine medizinische Haarwiederherstellungsanwendung geeignet ist.',
    'hi': '\u090f\u0915 \u092a\u0947\u0936\u0947\u0935\u0930, \u0917\u0930\u094d\u092e \u0914\u0930 \u0938\u094d\u092a\u0937\u094d\u091f \u0932\u0939\u091c\u0947 \u092e\u0947\u0902 \u092c\u094b\u0932\u0947\u0902\u0964',
    'ar': '\u062a\u062d\u062f\u062b \u0628\u0646\u0628\u0631\u0629 \u0645\u0647\u0646\u064a\u0629 \u0648\u062f\u0627\u0641\u0626\u0629 \u0648\u0648\u0627\u0636\u062d\u0629.',
    'pt': 'Fale em um tom profissional, caloroso e claro.',
    'ja': '\u30d7\u30ed\u30d5\u30a7\u30c3\u30b7\u30e7\u30ca\u30eb\u3067\u6e29\u304b\u304f\u660e\u77ad\u306a\u30c8\u30fc\u30f3\u3067\u8a71\u3057\u3066\u304f\u3060\u3055\u3044\u3002',
    'ko': '\uc804\ubb38\uc801\uc774\uace0 \ub530\ub73b\ud558\uace0 \uba85\ud655\ud55c \uc5b4\uc870\ub85c \ub9d0\ud558\uc138\uc694.',
    'zh': '\u8bf7\u7528\u4e13\u4e1a\u3001\u6e29\u6696\u3001\u6e05\u6670\u7684\u8bed\u8c03\u8bf4\u8bdd\u3002',
}


@app.route('/api/tts', methods=['POST'])
@login_required
def text_to_speech():
    """Convert text to speech using OpenAI TTS with real-time streaming.
    Returns PCM audio streamed in chunks for immediate playback."""
    if not openai_tts_client:
        return jsonify({'error': 'TTS not configured. Set OPENAI_API_KEY.'}), 500
    
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        voice = data.get('voice', DEFAULT_TTS_VOICE).lower()
        language = data.get('language', 'en')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        if len(text) > 4096:
            text = text[:4096]
        
        # Validate voice
        if voice not in OPENAI_TTS_VOICES:
            voice = DEFAULT_TTS_VOICE
        
        # Get language-specific instructions
        lang_code = language[:2].lower() if language else 'en'
        instructions = LANG_INSTRUCTIONS.get(lang_code, LANG_INSTRUCTIONS['en'])
        
        # If non-English, add language instruction
        if lang_code != 'en':
            instructions += f" Speak the text in the language it is written in."
        
        # Bill for TTS based on text length
        try:
            char_count = len(text)
            raw_cost = (char_count / 1000.0) * ESTIMATED_RAW_COSTS_USD['voice_tts_per_1k_chars']
            tts_ok, tts_data = deduct_credits(
                action='voice_tts',
                raw_cost_usd=raw_cost,
                description=f'TTS generation ({char_count} chars, OpenAI gpt-4o-mini-tts)'
            )
            if tts_ok:
                logger.info(f"[Billing] voice_tts deduction OK: {tts_data.get('credits_deducted', '?')} credits")
            else:
                logger.warning(f"[Billing] voice_tts deduction FAILED: {tts_data}")
        except Exception as billing_err:
            logger.warning(f"[Billing] voice_tts billing error: {billing_err}")
        
        def generate_audio_stream():
            """Generator that yields PCM audio chunks from OpenAI TTS."""
            try:
                with openai_tts_client.audio.speech.with_streaming_response.create(
                    model="gpt-4o-mini-tts",
                    voice=voice,
                    input=text,
                    instructions=instructions,
                    response_format="pcm"  # Raw PCM 24kHz 16-bit mono
                ) as response:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        yield chunk
            except Exception as e:
                print(f"[TTS] Streaming error: {e}")
                # Yield empty to signal end
                return
        
        return app.response_class(
            generate_audio_stream(),
            mimetype='audio/pcm',
            headers={
                'Content-Type': 'audio/pcm',
                'X-Audio-Sample-Rate': '24000',
                'X-Audio-Channels': '1',
                'X-Audio-Bit-Depth': '16',
                'Cache-Control': 'no-cache',
                'Transfer-Encoding': 'chunked'
            }
        )
        
    except Exception as e:
        import traceback
        print(f"TTS error: {traceback.format_exc()}")
        return jsonify({'error': f'TTS generation failed: {str(e)}'}), 500


# ============================================
# Health Endpoint
# ============================================
@app.route('/health')
def health():
    """Health check with billing configuration info."""
    pricing = fetch_pricing_config()
    return jsonify({
        'app': APP_SLUG,
        'version': '3.0.0',
        'status': 'healthy',
        'billing_mode': 'universal_suite',
        'billing_method': 'raw_cost_usd -> Admin applies markup -> pool deduction',
        'markup_multiplier': pricing.get('markup_multiplier', 50),
        'exchange_rate_usd': pricing.get('credit_exchange_rate_usd', 0.10),
        'estimated_costs': ESTIMATED_RAW_COSTS_USD,
        'admin_url': 'configured' if ADMIN_URL else 'missing',
        'gemini': 'configured' if GEMINI_API_KEY else 'missing',
        'openai_tts': 'configured' if OPENAI_API_KEY else 'missing',
    })


for _folder in ('UPLOAD_FOLDER', 'RESULTS_FOLDER', 'TURNTABLE_FOLDER'):
    os.makedirs(app.config[_folder], exist_ok=True)

from studio360 import register as register_studio360
register_studio360(app, globals())


if __name__ == '__main__':
    # Ensure directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)
    os.makedirs(app.config['TURNTABLE_FOLDER'], exist_ok=True)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
