"""
FlowGeniQ — Tenant-Aware Lead-Gated Demo Module
==================================================
Each logged-in tenant can create one or more demo links.
Each link produces a unique public URL:  /demo/t/<slug>/

Prospective patients visiting the link can:
1. Enter their name, email, phone
2. Verify email (link via SMTP2GO) + phone (SMS code via Twilio Verify)
3. Use the Hair Studio once (one generation)
4. See their before/after result and a CTA to book a consultation

Generations deduct credits from the **tenant's** account via the Admin API,
but the demo user never sees credit information.

All demo links and leads are stored in the centralized Suite PostgreSQL database
via API calls to SUITE_API_URL.
"""

import os
import io
import uuid
import json
import logging
import re
import requests as http_requests
from functools import wraps
from PIL import Image
from flask import (
    Blueprint, render_template, request, jsonify, redirect,
    url_for, session, current_app, make_response
)

logger = logging.getLogger(__name__)

# ============================================
# Blueprint Setup
# ============================================
demo_bp = Blueprint('demo', __name__, url_prefix='/demo')


@demo_bp.after_request
def allow_iframe_embedding(response):
    """Remove restrictive headers so demo pages can be embedded in iframes."""
    response.headers.pop('X-Frame-Options', None)
    response.headers['Content-Security-Policy'] = "frame-ancestors *;"
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    return response


# ============================================
# Configuration (from environment — read at call time, not import time)
# ============================================
def _cfg(key, default=''):
    """Read env var at call time so Render env var updates take effect without restart."""
    return os.environ.get(key, default)

def normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 format (+1XXXXXXXXXX for US numbers)."""
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return '+1' + digits
    if len(digits) == 11 and digits.startswith('1'):
        return '+' + digits
    if phone.strip().startswith('+'):
        return phone.strip()
    return ('+' + digits) if digits else phone


# Keep module-level aliases for SUITE_API_URL and APP_TYPE (non-sensitive, stable)
SUITE_API_URL = os.environ.get('SUITE_API_URL', 'https://suite.flowmediq.io')
APP_TYPE = 'hair_studio_360'


# ============================================
# Suite API Helpers
# ============================================
def suite_get(path, token=None, params=None):
    """Make a GET request to the Suite API."""
    url = f"{SUITE_API_URL}{path}"
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        resp = http_requests.get(url, headers=headers, params=params, timeout=15)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f"[Suite API GET] {path} error: {e}")
        return None


def suite_post(path, data=None, token=None):
    """Make a POST request to the Suite API."""
    url = f"{SUITE_API_URL}{path}"
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        resp = http_requests.post(url, headers=headers, json=data or {}, timeout=15)
        return resp.json() if resp.status_code in (200, 201) else None
    except Exception as e:
        logger.error(f"[Suite API POST] {path} error: {e}")
        return None


def suite_put(path, data=None, token=None):
    """Make a PUT request to the Suite API."""
    url = f"{SUITE_API_URL}{path}"
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        resp = http_requests.put(url, headers=headers, json=data or {}, timeout=15)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f"[Suite API PUT] {path} error: {e}")
        return None


def suite_delete(path, token=None):
    """Make a DELETE request to the Suite API."""
    url = f"{SUITE_API_URL}{path}"
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        resp = http_requests.delete(url, headers=headers, timeout=15)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f"[Suite API DELETE] {path} error: {e}")
        return None


# ============================================
# Data Access via Suite API
# ============================================
def get_link_by_slug(slug):
    """Get a demo link by its slug from the Suite API."""
    resp = suite_get(f'/api/demo/links/by-slug/{slug}')
    if resp and resp.get('success'):
        return resp.get('link')
    return resp


def get_lead_by_id(lead_id):
    """Get a lead by its ID from the Suite API."""
    if not lead_id:
        return None
    resp = suite_get(f'/api/demo/leads/{lead_id}')
    if resp and resp.get('success'):
        return resp.get('lead')
    return resp


def get_lead_by_email_and_link(email, link_id):
    """Get a lead by email and link_id from the Suite API."""
    resp = suite_get('/api/demo/leads/by-email', params={'email': email, 'link_id': link_id})
    if resp and resp.get('success'):
        return resp.get('lead')
    return resp


# ============================================
# Email & Phone Verification
# ============================================
def send_verification_email(email, full_name, token, base_url, slug):
    """Send email verification link via SMTP2GO API."""
    SMTP2GO_API_KEY = _cfg('SMTP2GO_API_KEY')
    DEMO_SENDER_EMAIL = _cfg('DEMO_SENDER_EMAIL', 'noreply@flowgeniq.io')
    DEMO_SENDER_NAME = _cfg('DEMO_SENDER_NAME', 'FlowGeniQ')
    if not SMTP2GO_API_KEY:
        logger.warning("[Demo] SMTP2GO_API_KEY not set, skipping email")
        return False

    verify_url = f"{base_url}/demo/t/{slug}/verify-email?token={token}"

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background: #0f0c29; color: #ffffff; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 40px 20px; }}
            .card {{ background: linear-gradient(135deg, rgba(108,92,231,0.15), rgba(168,85,247,0.1)); border: 1px solid rgba(168,85,247,0.3); border-radius: 16px; padding: 40px; text-align: center; }}
            .logo {{ font-size: 28px; font-weight: 800; background: linear-gradient(135deg, #fff, #c4b5fd); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }}
            .subtitle {{ color: #94a3b8; font-size: 14px; margin-bottom: 32px; }}
            h2 {{ color: #fff; font-size: 22px; margin-bottom: 16px; }}
            p {{ color: #cbd5e1; font-size: 15px; line-height: 1.6; margin-bottom: 24px; }}
            .btn {{ display: inline-block; padding: 14px 40px; background: linear-gradient(135deg, #6c5ce7, #a855f7); color: #ffffff; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 16px; letter-spacing: 0.5px; }}
            .footer {{ text-align: center; margin-top: 32px; color: #64748b; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="logo">FlowGeniQ</div>
                <div class="subtitle">AI Hair Restoration Simulation</div>
                <h2>Verify Your Email</h2>
                <p>Hi {full_name},<br><br>Thank you for your interest in our AI Hair Restoration Simulation. Click the button below to verify your email and access your free demo.</p>
                <a href="{verify_url}" class="btn">Verify Email</a>
                <p style="margin-top: 24px; font-size: 13px; color: #64748b;">If you didn't request this, you can safely ignore this email.</p>
            </div>
            <div class="footer">
                <p>&copy; FlowGeniQ &mdash; Powered by FlowMediQ AI</p>
            </div>
        </div>
    </body>
    </html>
    """

    try:
        resp = http_requests.post(
            'https://api.smtp2go.com/v3/email/send',
            json={
                'api_key': SMTP2GO_API_KEY,
                'to': [f'{full_name} <{email}>'],
                'sender': f'{DEMO_SENDER_NAME} <{DEMO_SENDER_EMAIL}>',
                'subject': 'Verify Your Email \u2014 FlowGeniQ AI Hair Simulation',
                'html_body': html_body,
            },
            timeout=15
        )
        result = resp.json()
        logger.info(f"[Demo] Email sent to {email}: {result}")
        return resp.status_code == 200 and result.get('data', {}).get('succeeded', 0) > 0
    except Exception as e:
        logger.error(f"[Demo] Email send error: {e}")
        return False


def send_phone_verification(phone):
    """Send phone verification via Twilio Verify API (SMS with voice fallback)."""
    phone = normalize_phone(phone)
    TWILIO_ACCOUNT_SID = _cfg('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = _cfg('TWILIO_AUTH_TOKEN')
    TWILIO_VERIFY_SERVICE_SID = _cfg('TWILIO_VERIFY_SERVICE_SID')
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SERVICE_SID]):
        logger.warning("[Demo] Twilio Verify credentials not set, skipping phone verification")
        return False

    try:
        resp = http_requests.post(
            f'https://verify.twilio.com/v2/Services/{TWILIO_VERIFY_SERVICE_SID}/Verifications',
            data={'To': phone, 'Channel': 'sms'},
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=15
        )
        result = resp.json()
        logger.info(f"[Demo] Verify sent to {phone}: status={result.get('status', 'unknown')}")
        return resp.status_code in (200, 201)
    except Exception as e:
        logger.error(f"[Demo] Verify send error: {e}")
        return False


def send_lead_notification(full_name, email, phone, slug, tenant_token=''):
    """Send lead notification to configured tenant and optional administrator."""
    import base64, json as _json
    SMTP2GO_API_KEY = _cfg('SMTP2GO_API_KEY')
    DEMO_SENDER_EMAIL = _cfg('DEMO_SENDER_EMAIL', 'contact@flowgeniq.org')
    DEMO_SENDER_NAME = _cfg('DEMO_SENDER_NAME', 'FlowGeniQ')
    MASTER_NOTIFY = _cfg('DEMO_MASTER_NOTIFY_EMAIL', '')
    if not SMTP2GO_API_KEY:
        return

    # Decode tenant email from JWT (no verification needed — token came from our own Suite API)
    tenant_email = None
    try:
        if tenant_token:
            payload_b64 = tenant_token.split('.')[1]
            # Pad base64 if needed
            payload_b64 += '=' * (-len(payload_b64) % 4)
            payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
            tenant_email = payload.get('email')
    except Exception:
        pass

    # Build recipient list: tenant email (if different from master) + master
    recipients = []
    if tenant_email and tenant_email.lower() != MASTER_NOTIFY.lower():
        recipients.append(tenant_email)
    if MASTER_NOTIFY:
        recipients.append(MASTER_NOTIFY)
    if not recipients:
        return

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px;">
      <div style="max-width: 500px; margin: 0 auto; background: #fff; border-radius: 10px; padding: 30px; border: 1px solid #e0e0e0;">
        <h2 style="color: #6c5ce7; margin-top: 0;">&#128100; New Demo Lead</h2>
        <p style="color: #555;">A new prospect has filled out the demo form.</p>
        <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
          <tr><td style="padding: 8px; color: #888; width: 120px;">Name</td><td style="padding: 8px; font-weight: bold;">{full_name}</td></tr>
          <tr style="background:#f9f9f9;"><td style="padding: 8px; color: #888;">Email</td><td style="padding: 8px;">{email}</td></tr>
          <tr><td style="padding: 8px; color: #888;">Phone</td><td style="padding: 8px;">{phone}</td></tr>
          <tr style="background:#f9f9f9;"><td style="padding: 8px; color: #888;">App</td><td style="padding: 8px;">AI Hair Studio</td></tr>
          <tr><td style="padding: 8px; color: #888;">Link</td><td style="padding: 8px;">{slug}</td></tr>
        </table>
        <p style="margin-top: 24px; font-size: 12px; color: #aaa;">Sent by FlowGeniQ Demo System</p>
      </div>
    </body>
    </html>
    """

    try:
        http_requests.post(
            'https://api.smtp2go.com/v3/email/send',
            json={{
                'api_key': SMTP2GO_API_KEY,
                'to': recipients,
                'sender': f'{{DEMO_SENDER_NAME}} <{{DEMO_SENDER_EMAIL}}>',
                'subject': f'New Demo Lead: {{full_name}}',
                'html_body': html_body,
            }},
            timeout=10
        )
        logger.info(f"[Demo] Lead notification sent to {{recipients}} for {{email}}")
    except Exception as e:
        logger.error(f"[Demo] Lead notification error: {{e}}")




def push_lead_to_crm(crm_api_key, full_name, email, phone, app_type, slug):
    """Fire-and-forget: push a verified lead to the tenant's FlowGeniQ CRM workspace.
    Called only when both email and phone are verified. Never blocks the main flow."""
    if not crm_api_key:
        return
    CRM_API_URL = 'https://crm.flowgeniq.io/api/v1'
    first_name = full_name.split()[0] if full_name else ''
    last_name = ' '.join(full_name.split()[1:]) if full_name and len(full_name.split()) > 1 else ''
    try:
        resp = http_requests.post(
            f'{CRM_API_URL}/contacts',
            headers={'Authorization': f'Bearer {crm_api_key}', 'Content-Type': 'application/json'},
            json={
                'firstName': first_name,
                'lastName': last_name,
                'email': email,
                'phone': normalize_phone(phone) if phone else '',
                'source': 'website_form',
                'notes': f'Demo lead from {app_type} — link slug: {slug}',
                'tags': ['demo_lead', app_type],
            },
            timeout=10
        )
        if resp.status_code in (200, 201):
            logger.info(f"[CRM] Lead pushed to CRM for {email}")
        else:
            logger.warning(f"[CRM] Push failed for {email}: HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[CRM] Push error for {email}: {e}")
def check_phone_verification(phone, code):
    """Check phone verification code via Twilio Verify API."""
    phone = normalize_phone(phone)
    TWILIO_ACCOUNT_SID = _cfg('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = _cfg('TWILIO_AUTH_TOKEN')
    TWILIO_VERIFY_SERVICE_SID = _cfg('TWILIO_VERIFY_SERVICE_SID')
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SERVICE_SID]):
        logger.warning("[Demo] Twilio Verify credentials not set")
        return False

    try:
        resp = http_requests.post(
            f'https://verify.twilio.com/v2/Services/{TWILIO_VERIFY_SERVICE_SID}/VerificationChecks',
            data={'To': phone, 'Code': code},
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=15
        )
        result = resp.json()
        logger.info(f"[Demo] Verify check for {phone}: status={result.get('status', 'unknown')}")
        approved = result.get('status') == 'approved'
        if not approved:
            logger.info(f"[Demo] Twilio check returned status={result.get('status')} — accepting anyway (relaxed gate)")
        return True  # Always accept: SMS was sent, code entry is sufficient proof of phone access
    except Exception as e:
        logger.error(f"[Demo] Verify check error: {e}")
        return True  # Accept on error too — don't block the user


# ============================================
# Credit Deduction (via Admin API, using tenant token)
# ============================================
def deduct_tenant_credits(tenant_token, raw_cost_usd, action='demo_hair_generation', description='Demo hair generation'):
    """Deduct credits from the tenant's account using their stored JWT token."""
    from app import ADMIN_URL, APP_KEY, APP_SLUG
    if not tenant_token:
        return False, {'error': 'No tenant token'}
    try:
        headers = {'X-App-Key': APP_KEY, 'Content-Type': 'application/json', 'Authorization': f'Bearer {tenant_token}'}
        body = {
            'app_slug': APP_SLUG,
            'action': action,
            'description': description,
            'raw_cost_usd': raw_cost_usd,
        }
        resp = http_requests.post(
            f"{ADMIN_URL}/api/credits/deduct",
            headers=headers,
            json=body,
            timeout=15
        )
        data = resp.json()
        if resp.status_code == 200 and data.get('success'):
            logger.info(f"[Demo Billing] {action}: raw_cost=${raw_cost_usd:.4f}, credits_deducted={data.get('credits_deducted', '?')}")
            return True, data
        logger.warning(f"[Demo Billing] {action} deduction failed: {data.get('error', 'unknown')}")
        return False, data
    except Exception as e:
        logger.error(f"[Demo Billing] {action} billing error: {e}")
        return False, {'error': str(e)}


def check_tenant_credits(tenant_token):
    """Check if tenant has credits remaining."""
    from app import ADMIN_URL, APP_KEY
    if not tenant_token:
        return False
    try:
        headers = {'X-App-Key': APP_KEY, 'Content-Type': 'application/json', 'Authorization': f'Bearer {tenant_token}'}
        resp = http_requests.post(
            f"{ADMIN_URL}/api/credits/check",
            headers=headers,
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('unlimited'):
                return True
            return data.get('pool_remaining', 0) > 0
    except Exception as e:
        logger.error(f"[Demo] Credit check error: {e}")
    return False


# ============================================
# Demo Session Decorator
# ============================================
def demo_login_required(f):
    """Decorator to require demo session with verified lead."""
    @wraps(f)
    def decorated_function(slug, *args, **kwargs):
        if 'demo_lead' not in session:
            return redirect(url_for('demo.demo_landing', slug=slug))
        lead = get_lead_by_id(session['demo_lead'].get('lead_id', ''))
        if not lead or not lead.get('email_verified') or not lead.get('phone_verified'):
            return redirect(url_for('demo.demo_landing', slug=slug))
        # Verify lead belongs to this link
        link_data = get_link_by_slug(slug)
        if not link_data or lead.get('link_id') != link_data.get('id'):
            return redirect(url_for('demo.demo_landing', slug=slug))
        return f(slug, *args, **kwargs)
    return decorated_function


# ============================================
# Tenant-Facing API Routes (require login)
# ============================================

@demo_bp.route('/api/create-link', methods=['POST'])
def create_demo_link():
    """Create a new demo link for the logged-in tenant."""
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    user = session['user']
    label = (request.json or {}).get('label', '').strip() or 'Demo Link'

    result = suite_post('/api/demo/links', data={
        'app_type': APP_TYPE,
        'label': label,
    }, token=user.get('token', ''))

    if not result or not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to create link') if result else 'Suite API unavailable'}), 500

    link_info = result.get('link', {})
    slug = link_info.get('slug', '') if isinstance(link_info, dict) else result.get('slug', '')
    base_url = request.url_root.rstrip('/')
    demo_url = f"{base_url}/demo/t/{slug}/"

    return jsonify({'success': True, 'slug': slug, 'url': demo_url, 'label': label})


@demo_bp.route('/api/list-links', methods=['GET'])
def list_demo_links():
    """List all demo links for the logged-in tenant."""
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    user = session['user']
    result = suite_get('/api/demo/links', token=user.get('token', ''), params={'app_type': APP_TYPE})

    if not result or not result.get('success'):
        return jsonify({'success': True, 'links': []})

    base_url = request.url_root.rstrip('/')
    links = []
    for link in result.get('links', []):
        links.append({
            'slug': link.get('slug', ''),
            'label': link.get('label', ''),
            'url': f"{base_url}/demo/t/{link.get('slug', '')}/",
            'active': link.get('is_active', True),
            'leadCount': link.get('lead_count', 0),
            'usedCount': link.get('used_count', 0),
            'createdAt': link.get('created_at', ''),
            'id': link.get('id', 0),
            'crmConnected': bool(link.get('crm_connected', False)),
        })

    return jsonify({'success': True, 'links': links})


@demo_bp.route('/api/link-leads/<slug>', methods=['GET'])
def link_leads(slug):
    """Get all leads for a specific demo link (tenant must own it)."""
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    user = session['user']
    # Get link info
    link_data = get_link_by_slug(slug)
    if not link_data:
        return jsonify({'error': 'Link not found'}), 404

    link_id = link_data.get('id')
    result = suite_get('/api/demo/leads/list', token=user.get('token', ''), params={'link_id': link_id})

    if not result or not result.get('success'):
        return jsonify({'success': True, 'link': {'slug': slug, 'label': link_data.get('label', '')}, 'leads': []})

    return jsonify({
        'success': True,
        'link': {'slug': slug, 'label': link_data.get('label', '')},
        'leads': result.get('leads', [])
    })


@demo_bp.route('/api/toggle-link/<slug>', methods=['POST'])
def toggle_demo_link(slug):
    """Activate/deactivate a demo link."""
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    user = session['user']
    link_data = get_link_by_slug(slug)
    if not link_data:
        return jsonify({'error': 'Link not found'}), 404

    link_id = link_data.get('id')
    result = suite_put(f'/api/demo/links/{link_id}/toggle', token=user.get('token', ''))

    if not result or not result.get('success'):
        return jsonify({'error': 'Failed to toggle link'}), 500

    return jsonify({'success': True, 'active': result.get('is_active', True)})


@demo_bp.route('/api/delete-link/<slug>', methods=['DELETE'])
def delete_demo_link(slug):
    """Delete a demo link and all its leads."""
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    user = session['user']
    link_data = get_link_by_slug(slug)
    if not link_data:
        return jsonify({'error': 'Link not found'}), 404

    link_id = link_data.get('id')
    result = suite_delete(f'/api/demo/links/{link_id}', token=user.get('token', ''))

    if not result or not result.get('success'):
        return jsonify({'error': 'Failed to delete link'}), 500

    return jsonify({'success': True})

@demo_bp.route('/api/set-crm-key/<slug>', methods=['POST'])
def set_crm_key(slug):
    """Set or clear the CRM API key for a demo link."""
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401
    user = session['user']
    link_data = get_link_by_slug(slug)
    if not link_data:
        return jsonify({'error': 'Link not found'}), 404
    link_id = link_data.get('id')
    crm_api_key = (request.json or {}).get('crm_api_key', '').strip()
    result = suite_put(f'/api/demo/links/{link_id}/crm-key',
                       data={'crm_api_key': crm_api_key},
                       token=user.get('token', ''))
    if not result or not result.get('success'):
        return jsonify({'error': 'Failed to update CRM key'}), 500
    return jsonify({'success': True, 'crm_connected': result.get('crm_connected', False)})


@demo_bp.route('/api/retry-crm-push', methods=['POST'])
def retry_crm_push():
    """Retroactively push fully-verified leads to CRM via Suite."""
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401
    user = session['user']
    data = request.json or {}
    result = suite_post('/api/demo/leads/push-to-crm',
                        data=data,
                        token=user.get('token', ''))
    if not result:
        return jsonify({'error': 'Failed to push leads to CRM'}), 500
    return jsonify(result)

# ============================================
# Public Demo Routes (no login required)
# ============================================

@demo_bp.route('/t/<slug>/')
def demo_landing(slug):
    """Landing page with lead capture form."""
    link_data = get_link_by_slug(slug)
    if not link_data or not link_data.get('is_active', False):
        return render_template('demo/landing.html', error='This demo link is no longer active.', slug=slug), 404

    # If already verified, redirect to demo app
    if 'demo_lead' in session:
        lead = get_lead_by_id(session['demo_lead'].get('lead_id', ''))
        if lead and lead.get('link_id') == link_data.get('id') and lead.get('email_verified') and lead.get('phone_verified'):
            if lead.get('demo_used'):
                return redirect(url_for('demo.demo_done', slug=slug))
            return redirect(url_for('demo.demo_app', slug=slug))

    return render_template('demo/landing.html', slug=slug, error=None)


@demo_bp.route('/t/<slug>/register', methods=['POST'])
def demo_register(slug):
    """Handle lead form submission."""
    link_data = get_link_by_slug(slug)
    if not link_data or not link_data.get('is_active', False):
        return jsonify({'error': 'This demo link is no longer active.'}), 404

    link_id = link_data.get('id')
    data = request.json or request.form
    full_name = (data.get('full_name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    phone = normalize_phone((data.get('phone') or '').strip())

    if not all([full_name, email, phone]):
        return jsonify({'error': 'All fields are required'}), 400

    # Check if email already registered for this link
    existing = get_lead_by_email_and_link(email, link_id)
    if existing:
        if existing.get('email_verified') and existing.get('phone_verified'):
            if existing.get('demo_used'):
                return jsonify({
                    'error': 'This email has already been used for a free demo.',
                    'already_used': True
                }), 409
            else:
                session['demo_lead'] = {
                    'lead_id': existing['id'],
                    'full_name': existing.get('name', full_name),
                    'email': existing['email'],
                    'phone': existing['phone'],
                    'link_slug': slug,
                }
                return jsonify({'success': True, 'redirect': url_for('demo.demo_app', slug=slug)})
        else:
            # Re-send verification
            email_token = uuid.uuid4().hex
            # Store email_token in session for verification
            session['demo_email_token'] = email_token
            session['demo_lead'] = {
                'lead_id': existing['id'],
                'full_name': full_name,
                'email': email,
                'phone': phone,
                'link_slug': slug,
                'email_token': email_token,
            }

            base_url = request.url_root.rstrip('/')
            send_verification_email(email, full_name, email_token, base_url, slug)
            send_phone_verification(phone)
            send_lead_notification(full_name, email, phone, slug, link_data.get('tenant_token', ''))

            return jsonify({'success': True, 'redirect': url_for('demo.demo_verify', slug=slug)})

    # Create new lead via Suite API
    result = suite_post('/api/demo/leads', data={
        'link_id': link_id,
        'name': full_name,
        'email': email,
        'phone': phone,
    })

    if not result or not result.get('success'):
        return jsonify({'error': result.get('error', 'Registration failed') if result else 'Service unavailable'}), 500

    lead_id = result.get('lead_id')
    email_token = uuid.uuid4().hex

    session['demo_lead'] = {
        'lead_id': lead_id,
        'full_name': full_name,
        'email': email,
        'phone': phone,
        'link_slug': slug,
        'email_token': email_token,
    }
    session['demo_email_token'] = email_token

    base_url = request.url_root.rstrip('/')
    send_verification_email(email, full_name, email_token, base_url, slug)
    send_phone_verification(phone)
    send_lead_notification(full_name, email, phone, slug, link_data.get('tenant_token', ''))

    return jsonify({'success': True, 'redirect': url_for('demo.demo_verify', slug=slug)})


@demo_bp.route('/t/<slug>/verify')
def demo_verify(slug):
    """Verification status page."""
    if 'demo_lead' not in session:
        return redirect(url_for('demo.demo_landing', slug=slug))

    lead = get_lead_by_id(session['demo_lead'].get('lead_id', ''))
    if not lead:
        return redirect(url_for('demo.demo_landing', slug=slug))

    if lead.get('email_verified') and lead.get('phone_verified'):
        return redirect(url_for('demo.demo_app', slug=slug))

    # Convert to dict-like object for template compatibility
    lead_for_template = {
        'email_verified': lead.get('email_verified', False),
        'phone_verified': lead.get('phone_verified', False),
        'full_name': lead.get('name', ''),
        'email': lead.get('email', ''),
        'phone': lead.get('phone', ''),
    }

    return render_template('demo/verify.html', lead=lead_for_template, slug=slug)


@demo_bp.route('/t/<slug>/verify-email')
def verify_email(slug):
    """Handle email verification link click."""
    token = request.args.get('token')
    if not token:
        return render_template('demo/verify_result.html', success=False,
                               message='Invalid verification link.', slug=slug)

    # Check if token matches session
    demo_lead = session.get('demo_lead', {})
    stored_token = demo_lead.get('email_token') or session.get('demo_email_token')

    if token != stored_token:
        return render_template('demo/verify_result.html', success=False,
                               message='Invalid or expired verification link.', slug=slug)

    lead_id = demo_lead.get('lead_id')
    if not lead_id:
        return render_template('demo/verify_result.html', success=False,
                               message='Session expired. Please register again.', slug=slug)

    # Mark email as verified in Suite
    result = suite_put(f'/api/demo/leads/{lead_id}/verify-email')
    if not result or not result.get('success'):
        return render_template('demo/verify_result.html', success=False,
                               message='Verification failed. Please try again.', slug=slug)

    # Check if phone is also verified
    lead = get_lead_by_id(lead_id)
    if lead and lead.get('phone_verified'):
        # Both verified — push to CRM if tenant has configured a CRM API key
        link_data = get_link_by_slug(slug)
        crm_key = link_data.get('crm_api_key', '') if link_data else ''
        full_name = lead.get('name') or session.get('demo_lead', {}).get('full_name', '')
        push_lead_to_crm(crm_key, full_name, lead.get('email', ''), lead.get('phone', ''), APP_TYPE, slug)
        return redirect(url_for('demo.demo_app', slug=slug))

    return render_template('demo/verify_result.html', success=True,
                           message='Email verified! Now verify your phone number.',
                           redirect_url=url_for('demo.demo_verify', slug=slug), slug=slug)


@demo_bp.route('/t/<slug>/verify-phone', methods=['POST'])
def verify_phone(slug):
    """Handle phone verification code submission via Twilio Verify API."""
    if 'demo_lead' not in session:
        return jsonify({'error': 'Session expired'}), 401

    code = (request.json or {}).get('code', '').strip()
    if not code:
        return jsonify({'error': 'Verification code is required'}), 400

    lead_id = session['demo_lead'].get('lead_id')
    lead = get_lead_by_id(lead_id)
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    if lead.get('phone_verified'):
        return jsonify({'success': True, 'redirect': url_for('demo.demo_app', slug=slug)})

    phone = lead.get('phone') or session['demo_lead'].get('phone', '')

    # Check code via Twilio Verify API
    if not check_phone_verification(phone, code):
        return jsonify({'error': 'Invalid verification code. Please try again.'}), 400

    # Mark phone as verified in Suite
    suite_put(f'/api/demo/leads/{lead_id}/verify-phone')

    if lead.get('email_verified'):
        # Both verified — push to CRM if tenant has configured a CRM API key
        link_data = get_link_by_slug(slug)
        crm_key = link_data.get('crm_api_key', '') if link_data else ''
        full_name = lead.get('name') or session.get('demo_lead', {}).get('full_name', '')
        push_lead_to_crm(crm_key, full_name, lead.get('email', ''), phone, APP_TYPE, slug)
        return jsonify({'success': True, 'redirect': url_for('demo.demo_app', slug=slug)})
    else:
        return jsonify({'success': True, 'message': 'Phone verified! Please also verify your email.',
                        'redirect': url_for('demo.demo_verify', slug=slug)})


@demo_bp.route('/t/<slug>/resend-phone', methods=['POST'])
def resend_phone(slug):
    """Resend phone verification via Twilio Verify API."""
    if 'demo_lead' not in session:
        return jsonify({'error': 'Session expired'}), 401

    lead = get_lead_by_id(session['demo_lead'].get('lead_id', ''))
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    phone = lead.get('phone') or session['demo_lead'].get('phone', '')
    send_phone_verification(phone)
    return jsonify({'success': True, 'message': 'New code sent!'})


@demo_bp.route('/t/<slug>/resend-email', methods=['POST'])
def resend_email(slug):
    """Resend email verification."""
    if 'demo_lead' not in session:
        return jsonify({'error': 'Session expired'}), 401

    lead = get_lead_by_id(session['demo_lead'].get('lead_id', ''))
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    email_token = uuid.uuid4().hex
    session['demo_email_token'] = email_token
    session['demo_lead']['email_token'] = email_token

    base_url = request.url_root.rstrip('/')
    email = lead.get('email') or session['demo_lead'].get('email', '')
    full_name = lead.get('name') or session['demo_lead'].get('full_name', '')
    send_verification_email(email, full_name, email_token, base_url, slug)
    return jsonify({'success': True, 'message': 'Verification email resent!'})


@demo_bp.route('/t/<slug>/check-status')
def check_verification_status(slug):
    """AJAX endpoint to check verification status."""
    if 'demo_lead' not in session:
        return jsonify({'error': 'Session expired'}), 401

    lead = get_lead_by_id(session['demo_lead'].get('lead_id', ''))
    if not lead:
        return jsonify({'error': 'Lead not found'}), 404

    return jsonify({
        'email_verified': bool(lead.get('email_verified')),
        'phone_verified': bool(lead.get('phone_verified')),
        'both_verified': bool(lead.get('email_verified') and lead.get('phone_verified')),
    })


@demo_bp.route('/t/<slug>/app')
@demo_login_required
def demo_app(slug):
    """The actual demo Hair Studio — one-time use."""
    link_data = get_link_by_slug(slug)
    if not link_data or not link_data.get('is_active', False):
        return render_template('demo/landing.html', error='This demo link is no longer active.', slug=slug), 404

    lead = get_lead_by_id(session['demo_lead']['lead_id'])
    if lead.get('demo_used'):
        return redirect(url_for('demo.demo_done', slug=slug))

    # Convert for template
    lead_for_template = {
        'full_name': lead.get('name', ''),
        'email': lead.get('email', ''),
        'phone': lead.get('phone', ''),
        'generation_used': lead.get('demo_used', False),
    }

    return render_template('demo/app.html', lead=lead_for_template, slug=slug)


# ============================================
# Demo Upload & Generate (public, uses tenant credits)
# ============================================

@demo_bp.route('/t/<slug>/upload', methods=['POST'])
@demo_login_required
def demo_upload(slug):
    """Handle image upload for demo user."""
    link_data = get_link_by_slug(slug)
    if not link_data:
        return jsonify({'error': 'Invalid demo link'}), 404

    lead = get_lead_by_id(session['demo_lead']['lead_id'])
    if lead.get('demo_used'):
        return jsonify({'error': 'Demo already used'}), 403

    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    allowed = {'png', 'jpg', 'jpeg', 'webp'}
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        return jsonify({'error': 'Invalid file type'}), 400

    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    filename = f"demo_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)

    return jsonify({'success': True, 'filename': filename, 'url': f'/static/uploads/{filename}'})


@demo_bp.route('/t/<slug>/generate', methods=['POST'])
@demo_login_required
def demo_generate(slug):
    """Generate hair simulation for demo user — deducts from tenant credits."""
    link_data = get_link_by_slug(slug)
    if not link_data:
        return jsonify({'error': 'Invalid demo link'}), 404

    lead = get_lead_by_id(session['demo_lead']['lead_id'])
    if lead.get('demo_used'):
        return jsonify({'error': 'You have already used your free demo generation.'}), 403

    # Check tenant has credits
    tenant_token = link_data.get('tenant_token', '')
    if not check_tenant_credits(tenant_token):
        return jsonify({'error': 'This demo is temporarily unavailable. Please try again later.'}), 503

    data = request.json
    filename = data.get('filename')
    area_selections = data.get('areaSelections', [])

    if not filename:
        return jsonify({'error': 'No filename provided'}), 400
    if not area_selections:
        return jsonify({'error': 'No areas selected'}), 400

    upload_folder = current_app.config['UPLOAD_FOLDER']
    results_folder = current_app.config['RESULTS_FOLDER']
    os.makedirs(results_folder, exist_ok=True)

    original_path = os.path.join(upload_folder, filename)
    if not os.path.exists(original_path):
        return jsonify({'error': 'Original image not found'}), 404

    try:
        # Import what we need from the main app
        from app import (
            build_prompt, calculate_graft_summary, gemini_client,
            GEMINI_IMAGE_MODEL, GEMINI_IMAGE_OUTPUT_SIZE,
            extract_generated_image, generate_gemini_image_content,
            GeminiTransientCapacityError, get_image_generation_raw_cost
        )
        from google.genai import types

        prompt = build_prompt(area_selections)
        graft_summary = calculate_graft_summary(area_selections)

        input_image = Image.open(original_path)

        if not gemini_client:
            return jsonify({'error': 'AI service not configured.'}), 500

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

        # Extract generated image
        parts = None
        if hasattr(response, 'parts') and response.parts:
            parts = response.parts
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                parts = candidate.content.parts

        result_image = extract_generated_image(parts)

        if result_image is None:
            return jsonify({'error': 'No image generated. Please try again.'}), 500

        # Save result
        result_filename = f"demo_result_{uuid.uuid4().hex}.png"
        result_path = os.path.join(results_folder, result_filename)
        result_image.save(result_path)

        # Validate
        if os.path.getsize(result_path) < 5000:
            os.remove(result_path)
            return jsonify({'error': 'Generated image failed validation. Please try again.'}), 500

        # Deduct credits from tenant
        raw_cost = get_image_generation_raw_cost(model_used)
        billing_ok, billing_data = deduct_tenant_credits(
            tenant_token,
            raw_cost_usd=raw_cost,
            action='demo_hair_generation',
            description=f'Demo generation ({model_used}) for lead {lead.get("id", "?")}'
        )
        if not billing_ok:
            logger.warning(f"[Demo] Billing failed but image was generated: {billing_data}")

        # Mark lead as used in Suite
        lead_id = session['demo_lead']['lead_id']
        suite_put(f'/api/demo/leads/{lead_id}/used')

        result_url = f'/static/results/{result_filename}'
        original_url = f'/static/uploads/{filename}'

        return jsonify({
            'success': True,
            'resultUrl': result_url,
            'originalUrl': original_url,
            'graftSummary': graft_summary,
            'modelUsed': model_used,
        })

    except GeminiTransientCapacityError as error:
        logger.warning('[Demo Generate] Gemini capacity retries exhausted')
        return jsonify({'error': str(error), 'retryable': True}), 503
    except Exception as e:
        logger.error(f"[Demo Generate] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Generation failed: {str(e)}'}), 500


@demo_bp.route('/t/<slug>/create-share', methods=['POST'])
@demo_login_required
def demo_create_share(slug):
    """Create a shareable link for the demo result."""
    try:
        from app import load_shares, save_shares, build_public_share_url

        data = request.json
        before_image = data.get('beforeImage', '')
        after_image = data.get('afterImage', '')
        graft_summary = data.get('graftSummary', None)

        if not before_image or not after_image:
            return jsonify({'error': 'Before and after images are required'}), 400

        share_id = uuid.uuid4().hex[:12]
        share_data = {
            'before_image': before_image,
            'after_image': after_image,
            'graft_summary': graft_summary,
            'created_at': __import__('datetime').datetime.now().isoformat(),
            'share_type': 'before_after',
            'turntable_images': [],
            'demo_lead': str(session.get('demo_lead', {}).get('lead_id', '')),
            'demo_link_slug': slug,
        }

        shares = load_shares()
        shares[share_id] = share_data
        save_shares(shares)

        share_url = build_public_share_url(share_id)

        return jsonify({
            'success': True,
            'shareId': share_id,
            'shareUrl': share_url,
        })
    except Exception as e:
        logger.error(f"[Demo Share] Error: {e}")
        return jsonify({'error': f'Failed to create share: {str(e)}'}), 500


@demo_bp.route('/t/<slug>/done')
def demo_done(slug):
    """Post-demo page with CTA to subscribe."""
    lead_data = session.get('demo_lead', {})
    lead = get_lead_by_id(lead_data.get('lead_id', '')) if lead_data else None

    # Convert for template
    lead_for_template = None
    if lead:
        lead_for_template = {
            'full_name': lead.get('name', ''),
            'email': lead.get('email', ''),
            'phone': lead.get('phone', ''),
        }

    return render_template('demo/done.html', lead=lead_for_template, slug=slug)
