"""Integration tests use synthetic images and mocked billing/provider calls."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['ADMIN_URL'] = ''  # Test process only; never touches Render ENV.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import app as application


def body():
    return {'protocol':'combined','zones':[{'area':'area3','density':'moderate','area_cm2':50,
            'baseline_density':100,'baseline_diameter_um':40,'responsive_percent':100,'grafts':1250}]}

def image_bytes():
    buf=io.BytesIO();Image.effect_noise((128,128),50).convert('RGB').save(buf,format='PNG');buf.seek(0);return buf

class RoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        application.app.config.update(TESTING=True,SECRET_KEY='only-a-test-secret',
            STUDIO360_DATA_DIR=str(root/'private'),UPLOAD_FOLDER=str(root/'uploads'))
        (root/'uploads').mkdir()
        self.client=application.app.test_client()
        with self.client.session_transaction() as s:s['user']={'id':'test-a','username':'Preview','token':'synthetic'}
        self.patches=[patch.object(application,'REMBG_AVAILABLE',False),
            patch.object(application,'check_usage_limit',return_value=(True,'',{'pool_remaining':100})),
            patch.object(application,'gemini_client',object()),
            patch.object(application,'generate_gemini_image_content',return_value=(type('Response',(),{'parts':['test']})(),'test-model')),
            patch.object(application,'extract_generated_image',side_effect=lambda parts:Image.open(image_bytes())),
            patch.object(application,'increment_usage',return_value=True)]
        self.mocks=[p.start() for p in self.patches]

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def upload(self):
        response=self.client.post('/upload',data={'image':(image_bytes(),'test.png')})
        self.assertEqual(response.status_code,200,response.data)
        return response.get_json()

    def test_shell_legacy_and_calculator_render(self):
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        for text in [b'Hair Studio 360',b'Side-by-side',b'Combined + graft savings']:
            self.assertIn(text,response.data)
        with patch.object(application,'refresh_user_session'):
            self.assertEqual(self.client.get('/transplant').status_code,200)
        self.assertEqual(self.client.post('/api/360/model',json=body()).status_code,200)

    def test_private_image_owner_and_traversal(self):
        data=self.upload();url='/api/360/image/'+data['imageId']
        with self.client.get(url) as response:
            self.assertEqual(response.status_code,200)
        with self.client.session_transaction() as s:s['user']={'id':'test-b'}
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get('/api/360/image/not-a-valid-id').status_code,404)

    def test_each_view_reuses_one_snapshot_and_bills_once(self):
        data=self.upload()
        for view in ['transplant','nonsurgical','combined']:
            request={'image_id':data['imageId'],'view':view,'reviewed':True,'scenario':body()}
            first=self.client.post('/api/360/generate',json=request)
            self.assertEqual(first.status_code,200,first.data)
            second=self.client.post('/api/360/generate',json=request)
            self.assertEqual(second.status_code,200,second.data)
            self.assertTrue(second.get_json()['cached'])
            self.assertEqual(first.get_json()['model'],second.get_json()['model'])
        self.assertEqual(self.mocks[-1].call_count,3)

    def test_billing_error_preserves_generated_result_for_retry(self):
        data=self.upload()
        request={'image_id':data['imageId'],'view':'nonsurgical','reviewed':True,'scenario':body()}
        self.mocks[-1].side_effect=RuntimeError('Test billing outage')
        first=self.client.post('/api/360/generate',json=request)
        self.assertEqual(first.status_code,200)
        self.assertFalse(first.get_json()['billingRecorded'])
        second=self.client.post('/api/360/generate',json=request)
        self.assertTrue(second.get_json()['cached'])
        self.assertEqual(self.mocks[-1].call_count,1)

    def test_validation_happens_before_billing(self):
        data=self.upload();p=body();p['zones'][0]['area_cm2']=0
        response=self.client.post('/api/360/generate',json={'image_id':data['imageId'],'view':'nonsurgical','reviewed':True,'scenario':p})
        self.assertEqual(response.status_code,400)
        self.mocks[-1].assert_not_called()

    def test_corrupt_upload_is_rejected(self):
        response=self.client.post('/upload',data={'image':(io.BytesIO(b'not an image'),'test.png')})
        self.assertEqual(response.status_code,400)

    def test_credit_refusal_can_be_retried_after_topup(self):
        data=self.upload();request={'image_id':data['imageId'],'view':'nonsurgical','reviewed':True,'scenario':body()}
        self.mocks[1].return_value=(False,'Insufficient credits',{})
        self.assertEqual(self.client.post('/api/360/generate',json=request).status_code,403)
        self.mocks[1].return_value=(True,'',{})
        self.assertEqual(self.client.post('/api/360/generate',json=request).status_code,200)

    def test_unreviewed_and_unauthenticated_requests_denied(self):
        data=self.upload()
        response=self.client.post('/api/360/generate',json={'image_id':data['imageId'],'view':'nonsurgical','scenario':body()})
        self.assertEqual(response.status_code,400)
        with self.client.session_transaction() as s:s.clear()
        response=self.client.post('/api/360/model',json=body())
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.headers['Location'],application.SUITE_URL+'/launch/flowmediq-hair-studio-360')

if __name__=='__main__':unittest.main()
