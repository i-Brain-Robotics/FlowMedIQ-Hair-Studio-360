#!/usr/bin/env python3
"""Regression checks for the Gemini 3 Pro Image 2K migration.

These tests use a fake Gemini client and make no external API calls.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ.pop('GEMINI_API_KEY', None)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image
import app
from google.genai import types


class FakeImagePart:
    inline_data = object()

    def as_image(self):
        return Image.new('RGB', (64, 64), 'white')


class CurrentSdkImagePart:
    """Represents google-genai 2.x Part.as_image() behavior."""

    def __init__(self):
        # Use a non-uniform payload that exceeds the app's 1 KB corruption guard.
        image = Image.effect_noise((256, 256), 100).convert('RGB')
        payload = io.BytesIO()
        image.save(payload, format='PNG')
        self.inline_data = types.Blob(data=payload.getvalue(), mime_type='image/png')

    def as_image(self):
        return types.Image(
            image_bytes=self.inline_data.data,
            mime_type=self.inline_data.mime_type,
        )


class FakeResponse:
    parts = [FakeImagePart()]


class CurrentSdkResponse:
    parts = [CurrentSdkImagePart()]


class FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse()


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeModels()


class FakeCurrentSdkGeminiClient:
    def __init__(self):
        self.models = FakeModels()
        self.models.generate_content = lambda **kwargs: CurrentSdkResponse()


class RetryThenCurrentSdkModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError('503 UNAVAILABLE: temporary high demand')
        return CurrentSdkResponse()


class RetryThenCurrentSdkGeminiClient:
    def __init__(self):
        self.models = RetryThenCurrentSdkModels()


class AlwaysUnavailableModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError('503 UNAVAILABLE: temporary high demand')


class AlwaysUnavailableGeminiClient:
    def __init__(self):
        self.models = AlwaysUnavailableModels()


class SequenceModels:
    def __init__(self, outcomes):
        self.calls = []
        self.outcomes = list(outcomes)

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class SequenceGeminiClient:
    def __init__(self, outcomes):
        self.models = SequenceModels(outcomes)


def test_constants():
    assert app.GEMINI_IMAGE_MODEL == 'gemini-3-pro-image'
    assert app.GEMINI_IMAGE_FALLBACK_MODEL == 'gemini-3.1-flash-image'
    assert app.GEMINI_IMAGE_OUTPUT_SIZE == '2K'
    assert app.get_image_generation_raw_cost(app.GEMINI_IMAGE_MODEL) == 0.137
    assert app.get_image_generation_raw_cost(app.GEMINI_IMAGE_FALLBACK_MODEL) == 0.104


def test_sdk_image_config():
    config = types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE'],
        image_config=types.ImageConfig(image_size='2K'),
    )
    assert config.image_config.image_size == '2K'


def test_current_sdk_image_object_converts_to_pil():
    result = app.extract_generated_image([CurrentSdkImagePart()])
    assert isinstance(result, Image.Image)
    assert result.size == (256, 256)


def test_transient_gemini_error_retries_before_succeeding():
    original_client = app.gemini_client
    original_sleep = app.time_billing.sleep
    fake_client = RetryThenCurrentSdkGeminiClient()
    delays = []
    app.gemini_client = fake_client
    app.time_billing.sleep = delays.append
    try:
        response, model_used = app.generate_gemini_image_content(
            contents=['Create a hair restoration preview.'],
            config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE']),
        )
    finally:
        app.gemini_client = original_client
        app.time_billing.sleep = original_sleep

    assert response.parts
    assert len(fake_client.models.calls) == 2
    assert [call['model'] for call in fake_client.models.calls] == [
        'gemini-3-pro-image', 'gemini-3.1-flash-image'
    ]
    assert model_used == 'gemini-3.1-flash-image'
    assert delays == []


def test_transient_gemini_error_reports_capacity_after_final_attempt():
    original_client = app.gemini_client
    original_sleep = app.time_billing.sleep
    fake_client = AlwaysUnavailableGeminiClient()
    delays = []
    app.gemini_client = fake_client
    app.time_billing.sleep = delays.append
    try:
        try:
            app.generate_gemini_image_content(
                contents=['Create a hair restoration preview.'],
                config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE']),
            )
        except app.GeminiTransientCapacityError as error:
            assert 'No Hair Studio credits were deducted' in str(error)
        else:
            raise AssertionError('Expected GeminiTransientCapacityError')
    finally:
        app.gemini_client = original_client
        app.time_billing.sleep = original_sleep

    assert len(fake_client.models.calls) == 3
    assert [call['model'] for call in fake_client.models.calls] == [
        'gemini-3-pro-image', 'gemini-3.1-flash-image', 'gemini-3-pro-image'
    ]
    assert delays == [5]


def test_flash_connection_failure_gets_final_pro_attempt():
    original_client = app.gemini_client
    original_sleep = app.time_billing.sleep
    fake_client = SequenceGeminiClient([
        RuntimeError('503 UNAVAILABLE: temporary high demand'),
        ConnectionError('connection reset by peer'),
        CurrentSdkResponse(),
    ])
    delays = []
    app.gemini_client = fake_client
    app.time_billing.sleep = delays.append
    try:
        response, model_used = app.generate_gemini_image_content(
            contents=['Create a hair restoration preview.'],
            config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE']),
        )
    finally:
        app.gemini_client = original_client
        app.time_billing.sleep = original_sleep

    assert response.parts
    assert model_used == 'gemini-3-pro-image'
    assert [call['model'] for call in fake_client.models.calls] == [
        'gemini-3-pro-image', 'gemini-3.1-flash-image', 'gemini-3-pro-image'
    ]
    assert delays == [5]


def test_non_503_pro_error_does_not_use_flash_fallback():
    original_client = app.gemini_client
    fake_client = SequenceGeminiClient([RuntimeError('400 INVALID_ARGUMENT')])
    app.gemini_client = fake_client
    try:
        try:
            app.generate_gemini_image_content(
                contents=['Create a hair restoration preview.'],
                config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE']),
            )
        except RuntimeError as error:
            assert '400 INVALID_ARGUMENT' in str(error)
        else:
            raise AssertionError('Expected the original non-503 error')
    finally:
        app.gemini_client = original_client

    assert len(fake_client.models.calls) == 1


def test_non_high_demand_503_does_not_use_flash_fallback():
    original_client = app.gemini_client
    fake_client = SequenceGeminiClient([RuntimeError('503 SERVICE_UNAVAILABLE')])
    app.gemini_client = fake_client
    try:
        try:
            app.generate_gemini_image_content(
                contents=['Create a hair restoration preview.'],
                config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE']),
            )
        except RuntimeError as error:
            assert '503 SERVICE_UNAVAILABLE' in str(error)
        else:
            raise AssertionError('Expected the original non-high-demand 503 error')
    finally:
        app.gemini_client = original_client

    assert len(fake_client.models.calls) == 1


def test_flash_generation_bills_flash_raw_cost():
    original_deduct_credits = app.deduct_credits
    calls = []

    def fake_deduct_credits(**kwargs):
        calls.append(kwargs)
        return True, {'credits_deducted': 52}

    app.deduct_credits = fake_deduct_credits
    try:
        assert app.increment_usage(app.GEMINI_IMAGE_FALLBACK_MODEL) is True
    finally:
        app.deduct_credits = original_deduct_credits

    assert calls == [{
        'action': 'hair_generation',
        'raw_cost_usd': 0.104,
        'description': 'Hair generation (gemini-3.1-flash-image)',
    }]


def test_turntable_generation_uses_2k():
    original_client = app.gemini_client
    fake_client = FakeGeminiClient()
    app.gemini_client = fake_client
    try:
        image, error, model_used = app._call_gemini_with_retry(
            'Create a consistent turntable image.', Image.new('RGB', (16, 16), 'white'), max_retries=1
        )
    finally:
        app.gemini_client = original_client

    assert error is None
    assert image.size == (64, 64)
    assert model_used == 'gemini-3-pro-image'
    assert len(fake_client.models.calls) == 1
    call = fake_client.models.calls[0]
    assert call['model'] == 'gemini-3-pro-image'
    assert call['config'].response_modalities == ['TEXT', 'IMAGE']
    assert call['config'].image_config.image_size == '2K'


def test_primary_generation_route_handles_current_sdk_image():
    original_client = app.gemini_client
    original_upload_folder = app.app.config['UPLOAD_FOLDER']
    original_results_folder = app.app.config['RESULTS_FOLDER']
    original_check_usage = app.check_usage_limit
    original_increment_usage = app.increment_usage
    original_refresh_session = app.refresh_user_session

    with tempfile.TemporaryDirectory() as temp_dir:
        upload_folder = Path(temp_dir) / 'uploads'
        results_folder = Path(temp_dir) / 'results'
        upload_folder.mkdir()
        results_folder.mkdir()
        Image.new('RGB', (16, 16), 'white').save(upload_folder / 'source.png')

        app.gemini_client = FakeCurrentSdkGeminiClient()
        app.app.config['UPLOAD_FOLDER'] = str(upload_folder)
        app.app.config['RESULTS_FOLDER'] = str(results_folder)
        app.check_usage_limit = lambda estimated_credits=0: (True, 'ok', {'pool_remaining': 999})
        app.increment_usage = lambda *args: True
        app.refresh_user_session = lambda: None

        try:
            client = app.app.test_client()
            with client.session_transaction() as session:
                session['user'] = {'pool_remaining': 999, 'token': 'test-token'}
            response = client.post('/generate', json={
                'filename': 'source.png',
                'areaSelections': [{'area': 'area2', 'density': 'moderate'}],
            })
        finally:
            app.gemini_client = original_client
            app.app.config['UPLOAD_FOLDER'] = original_upload_folder
            app.app.config['RESULTS_FOLDER'] = original_results_folder
            app.check_usage_limit = original_check_usage
            app.increment_usage = original_increment_usage
            app.refresh_user_session = original_refresh_session

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['modelUsed'] == 'gemini-3-pro-image'
        result_path = results_folder / Path(data['resultUrl']).name
        assert result_path.exists()
        assert Image.open(result_path).size == (256, 256)


def test_primary_generation_route_bills_successful_flash_fallback():
    original_client = app.gemini_client
    original_upload_folder = app.app.config['UPLOAD_FOLDER']
    original_results_folder = app.app.config['RESULTS_FOLDER']
    original_check_usage = app.check_usage_limit
    original_increment_usage = app.increment_usage
    original_refresh_session = app.refresh_user_session
    fake_client = SequenceGeminiClient([
        RuntimeError('503 UNAVAILABLE: temporary high demand'),
        CurrentSdkResponse(),
    ])
    billed_models = []

    with tempfile.TemporaryDirectory() as temp_dir:
        upload_folder = Path(temp_dir) / 'uploads'
        results_folder = Path(temp_dir) / 'results'
        upload_folder.mkdir()
        results_folder.mkdir()
        Image.new('RGB', (16, 16), 'white').save(upload_folder / 'source.png')

        app.gemini_client = fake_client
        app.app.config['UPLOAD_FOLDER'] = str(upload_folder)
        app.app.config['RESULTS_FOLDER'] = str(results_folder)
        app.check_usage_limit = lambda estimated_credits=0: (True, 'ok', {'pool_remaining': 999})
        app.increment_usage = lambda model_used: billed_models.append(model_used) or True
        app.refresh_user_session = lambda: None

        try:
            client = app.app.test_client()
            with client.session_transaction() as session:
                session['user'] = {'pool_remaining': 999, 'token': 'test-token'}
            response = client.post('/generate', json={
                'filename': 'source.png',
                'areaSelections': [{'area': 'area2', 'density': 'moderate'}],
            })
        finally:
            app.gemini_client = original_client
            app.app.config['UPLOAD_FOLDER'] = original_upload_folder
            app.app.config['RESULTS_FOLDER'] = original_results_folder
            app.check_usage_limit = original_check_usage
            app.increment_usage = original_increment_usage
            app.refresh_user_session = original_refresh_session

        assert response.status_code == 200
        assert response.get_json()['modelUsed'] == 'gemini-3.1-flash-image'
        assert billed_models == ['gemini-3.1-flash-image']
        assert [call['model'] for call in fake_client.models.calls] == [
            'gemini-3-pro-image', 'gemini-3.1-flash-image'
        ]


def test_primary_generation_route_returns_retryable_capacity_error():
    original_client = app.gemini_client
    original_upload_folder = app.app.config['UPLOAD_FOLDER']
    original_results_folder = app.app.config['RESULTS_FOLDER']
    original_check_usage = app.check_usage_limit
    original_sleep = app.time_billing.sleep
    fake_client = AlwaysUnavailableGeminiClient()

    with tempfile.TemporaryDirectory() as temp_dir:
        upload_folder = Path(temp_dir) / 'uploads'
        results_folder = Path(temp_dir) / 'results'
        upload_folder.mkdir()
        results_folder.mkdir()
        Image.new('RGB', (16, 16), 'white').save(upload_folder / 'source.png')

        app.gemini_client = fake_client
        app.app.config['UPLOAD_FOLDER'] = str(upload_folder)
        app.app.config['RESULTS_FOLDER'] = str(results_folder)
        app.check_usage_limit = lambda estimated_credits=0: (True, 'ok', {'pool_remaining': 999})
        app.time_billing.sleep = lambda _seconds: None

        try:
            client = app.app.test_client()
            with client.session_transaction() as session:
                session['user'] = {'pool_remaining': 999, 'token': 'test-token'}
            response = client.post('/generate', json={
                'filename': 'source.png',
                'areaSelections': [{'area': 'area2', 'density': 'moderate'}],
            })
        finally:
            app.gemini_client = original_client
            app.app.config['UPLOAD_FOLDER'] = original_upload_folder
            app.app.config['RESULTS_FOLDER'] = original_results_folder
            app.check_usage_limit = original_check_usage
            app.time_billing.sleep = original_sleep

        assert response.status_code == 503
        data = response.get_json()
        assert data['retryable'] is True
        assert 'No Hair Studio credits were deducted' in data['error']
        assert len(fake_client.models.calls) == 3


def test_demo_path_includes_2k_image_config():
    demo_source = (PROJECT_ROOT / 'demo_leads.py').read_text()
    assert 'GEMINI_IMAGE_OUTPUT_SIZE' in demo_source
    assert 'types.ImageConfig(image_size=GEMINI_IMAGE_OUTPUT_SIZE)' in demo_source
    assert 'extract_generated_image' in demo_source
    assert 'generate_gemini_image_content' in demo_source
    assert 'GeminiTransientCapacityError' in demo_source
    assert 'get_image_generation_raw_cost' in demo_source


def test_client_restores_options_after_retryable_failure():
    client_source = (PROJECT_ROOT / 'static/js/app.js').read_text()
    assert 'else if (data.retryable)' in client_source
    assert "document.getElementById('step-options').style.display = 'block';" in client_source


def test_client_displays_shared_pool_credits():
    client_source = (PROJECT_ROOT / 'static/js/app.js').read_text()
    assert 'usage.pool_remaining' in client_source
    assert 'usage.pool_total' in client_source
    assert '`${remaining} remaining`' in client_source


if __name__ == '__main__':
    tests = [
        test_constants,
        test_sdk_image_config,
        test_current_sdk_image_object_converts_to_pil,
        test_transient_gemini_error_retries_before_succeeding,
        test_transient_gemini_error_reports_capacity_after_final_attempt,
        test_flash_connection_failure_gets_final_pro_attempt,
        test_non_503_pro_error_does_not_use_flash_fallback,
        test_non_high_demand_503_does_not_use_flash_fallback,
        test_flash_generation_bills_flash_raw_cost,
        test_turntable_generation_uses_2k,
        test_primary_generation_route_handles_current_sdk_image,
        test_primary_generation_route_bills_successful_flash_fallback,
        test_primary_generation_route_returns_retryable_capacity_error,
        test_demo_path_includes_2k_image_config,
        test_client_restores_options_after_retryable_failure,
        test_client_displays_shared_pool_credits,
    ]
    for test in tests:
        test()
        print(f'passed={test.__name__}')
    print('gemini_migration_regression_checks=passed')
