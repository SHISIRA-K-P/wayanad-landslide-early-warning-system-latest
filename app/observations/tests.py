from contextlib import redirect_stdout
from io import StringIO
import smtplib
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
import numpy as np
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    EmergencyAuthority,
    LandslideObservation,
)
from .rag import RagConfigurationError, create_chunks, load_pdf_pages
from .prediction import (
    FEATURE_COLUMNS,
    ONE_HOT_FEATURE_COLUMNS,
    predict_landslide,
)
from .response_agent import (
    get_emergency_contact,
    _tool_result,
    retrieve_safety_measures,
    run_landslide_response_agent,
    send_emergency_email,
)


class LandslideObservationApiTests(APITestCase):
    url = '/api/observations/'
    valid_observation = {
        'location_id': 1,
        'max_temp_c': 27.5,
        'humidity_pct': 84.0,
        'wind_speed_kmh': 12.0,
        'rainfall_mm': 35.5,
        'slope_angle_deg': 32,
        'vegetation_cover': 'Medium',
    }

    def setUp(self):
        patcher = patch('observations.views._start_response_agent')
        self.response_agent_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_returns_empty_array_when_no_observations_exist(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_cors_allows_local_react_development_origin(self):
        response = self.client.get(
            self.url,
            HTTP_ORIGIN='http://localhost:5173',
        )

        self.assertEqual(
            response['Access-Control-Allow-Origin'],
            'http://localhost:5173',
        )

    @patch(
        'observations.views.predict_landslide',
        return_value={
            'landslide_prediction': 'Yes',
            'landslide_probability': 0.75,
        },
    )
    def test_observation_api_does_not_expose_emergency_contacts(self, _predict):
        EmergencyAuthority.objects.create(
            authority_name='Private backend contact',
            authority_type=EmergencyAuthority.AuthorityType.OTHER,
            location_id=1,
            district='Test district',
            email='contact@example.invalid',
            phone_number='0000000000',
        )

        response = self.client.post(
            self.url,
            self.valid_observation,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('authority_contacts', response.data)

    def test_post_creates_observation_and_get_returns_it(self):
        with patch(
            'observations.views.predict_landslide',
            return_value={
                'landslide_prediction': 'Yes',
                'landslide_probability': 0.75,
            },
        ):
            with self.captureOnCommitCallbacks(execute=True):
                first_response = self.client.post(
                    self.url,
                    self.valid_observation,
                    format='json',
                )
        with patch(
            'observations.views.predict_landslide',
            return_value={
                'landslide_prediction': 'No',
                'landslide_probability': 0.25,
            },
        ):
            second_response = self.client.post(
                self.url,
                {**self.valid_observation, 'location_id': 2},
                format='json',
            )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first_response.data['landslide_prediction'], 'Yes')
        self.assertEqual(first_response.data['landslide_probability'], 0.75)
        self.assertIsNone(first_response.data['landslide_observed'])
        self.assertIn('id', first_response.data)
        self.assertIn('created_at', first_response.data)
        self.response_agent_mock.assert_called_once_with(first_response.data['id'])

        list_response = self.client.get(self.url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 2)
        self.assertEqual(
            [record['id'] for record in list_response.data],
            [second_response.data['id'], first_response.data['id']],
        )
        self.assertEqual(
            list_response.data[1]['landslide_prediction'],
            'Yes',
        )
        self.assertEqual(
            list_response.data[1]['landslide_probability'],
            0.75,
        )

    def test_post_uses_the_saved_model_to_predict_landslide(self):
        response = self.client.post(
            self.url,
            self.valid_observation,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn(response.data['landslide_prediction'], ('Yes', 'No'))
        self.assertGreaterEqual(response.data['landslide_probability'], 0)
        self.assertLessEqual(response.data['landslide_probability'], 1)

    @patch(
        'observations.views.predict_landslide',
        return_value={
            'landslide_prediction': 'Yes',
            'landslide_probability': 0.8,
        },
    )
    def test_post_accepts_dataset_column_names(self, _predict):
        dataset_observation = {
            'Location_ID': 1,
            'Max_Temp_C': 27.5,
            'Humidity_Pct': 84.0,
            'Wind_Speed_kmh': 12.0,
            'Rainfall_mm': 35.5,
            'Slope_Angle_Deg': 32,
            'Vegetation_Cover': 'Medium',
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url,
                dataset_observation,
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['location_id'], 1)
        self.assertEqual(response.data['max_temp_c'], 27.5)
        self.assertEqual(response.data['vegetation_cover'], 'Medium')
        self.response_agent_mock.assert_called_once_with(response.data['id'])

    @patch(
        'observations.views.predict_landslide',
        return_value={
            'landslide_prediction': 'No',
            'landslide_probability': 0.2,
        },
    )
    def test_put_updates_observation_and_recalculates_prediction(self, predict):
        created = self.client.post(self.url, self.valid_observation, format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        updated_data = {**self.valid_observation, 'rainfall_mm': 70}
        response = self.client.put(
            f'{self.url}{created.data["id"]}/',
            updated_data,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['rainfall_mm'], 70)
        self.assertEqual(response.data['landslide_prediction'], 'No')
        self.assertEqual(response.data['landslide_probability'], 0.2)
        predict.assert_called()

    @patch(
        'observations.views.predict_landslide',
        return_value={
            'landslide_prediction': 'No',
            'landslide_probability': 0.3,
        },
    )
    def test_patch_updates_observation(self, predict):
        created = self.client.post(self.url, self.valid_observation, format='json')
        response = self.client.patch(
            f'{self.url}{created.data["id"]}/',
            {'rainfall_mm': 55},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['rainfall_mm'], 55)
        self.assertEqual(response.data['landslide_prediction'], 'No')
        predict.assert_called()

    @patch(
        'observations.views.predict_landslide',
        return_value={
            'landslide_prediction': 'No',
            'landslide_probability': 0.3,
        },
    )
    def test_delete_removes_observation(self, _predict):
        created = self.client.post(self.url, self.valid_observation, format='json')
        response = self.client.delete(f'{self.url}{created.data["id"]}/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get(self.url).data, [])

    @patch(
        'observations.views.predict_landslide',
        return_value={
            'landslide_prediction': 'No',
            'landslide_probability': 0.3,
        },
    )
    def test_prediction_fields_cannot_be_set_by_the_client(self, _predict):
        response = self.client.post(
            self.url,
            {
                **self.valid_observation,
                'landslide_observed': 'Yes',
                'landslide_prediction': 'Yes',
                'landslide_probability': 1,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['landslide_prediction'], 'No')
        self.assertEqual(response.data['landslide_probability'], 0.3)

    @patch(
        'observations.views.predict_landslide',
        side_effect=ImproperlyConfigured('model missing'),
    )
    def test_create_returns_service_unavailable_when_model_is_missing(self, _predict):
        response = self.client.post(self.url, self.valid_observation, format='json')

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @patch(
        'observations.views.predict_landslide',
        return_value={
            'landslide_prediction': 'No',
            'landslide_probability': 0.3,
        },
    )
    def test_post_rejects_invalid_choice(self, _predict):
        invalid_observation = {
            **self.valid_observation,
            'vegetation_cover': 'Unknown',
        }

        response = self.client.post(
            self.url,
            invalid_observation,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('vegetation_cover', response.data)


class LandslideResponseSelectionTests(TestCase):
    def setUp(self):
        self.observation = LandslideObservation.objects.create(
            location_id=1,
            max_temp_c=27.5,
            humidity_pct=84.0,
            wind_speed_kmh=12.0,
            rainfall_mm=35.5,
            slope_angle_deg=32,
            vegetation_cover='Medium',
            landslide_prediction='Yes',
            landslide_probability=0.8,
        )
        self.authority = EmergencyAuthority.objects.create(
            authority_name='Verified test authority',
            authority_type=EmergencyAuthority.AuthorityType.OTHER,
            location_id=1,
            district='Test district',
            email='verified@example.invalid',
            phone_number='0000000000',
            is_active=True,
            is_verified=True,
        )

    def _tool_response(self, name, arguments=None):
        return SimpleNamespace(
            message=SimpleNamespace(
                content='',
                tool_calls=[
                    SimpleNamespace(
                        function=SimpleNamespace(
                            name=name,
                            arguments=arguments or {},
                        )
                    )
                ],
            )
        )

    def _configure_agent_tool_calls(self, chat_mock, include_email=True):
        responses = [
            self._tool_response('retrieve_safety_measures'),
            self._tool_response('get_emergency_contact'),
        ]
        if include_email:
            responses.append(self._tool_response('send_emergency_email'))
        chat_mock.side_effect = responses

    @patch('observations.response_agent.chat')
    @patch('observations.response_agent.ask_rag')
    def test_positive_prediction_invokes_tool_and_returns_first_contact(
        self,
        ask_rag_mock,
        chat_mock,
    ):
        first_authority = EmergencyAuthority.objects.create(
            authority_name='A First Authority',
            authority_type=EmergencyAuthority.AuthorityType.POLICE,
            location_id=999,
            district='First district',
            email='first@example.invalid',
            phone_number='1111111111',
            is_active=False,
            is_verified=False,
        )
        ask_rag_mock.return_value = {
            'answer': 'Use the cited safety guidance.',
            'sources': [{'page': 2, 'score': 0.9}],
        }
        self._configure_agent_tool_calls(chat_mock)
        output = StringIO()

        with (
            patch(
                'observations.response_agent.get_emergency_contact',
                wraps=get_emergency_contact,
            ) as lookup,
            patch('observations.response_agent.send_mail') as send_mail_mock,
            override_settings(LANDSLIDE_EMAIL_DRY_RUN=True),
            redirect_stdout(output),
        ):
            result = run_landslide_response_agent(self.observation.pk)
        lookup.assert_called_once_with()
        send_mail_mock.assert_not_called()

        printed = output.getvalue()
        self.assertIn('Landslide response agent result:', printed)
        self.assertIn('Use the cited safety guidance.', printed)
        self.assertIn('Landslide_safety.pdf (page 2)', printed)
        self.assertIn('A First Authority', printed)
        self.assertIn('first@example.invalid', printed)
        self.assertIn('1111111111', printed)
        self.assertEqual(result['observation_id'], self.observation.pk)
        self.assertEqual(
            result['safety_precautions']['recommendation'],
            'Use the cited safety guidance.',
        )
        self.assertEqual(
            result['emergency_contact'],
            {
                'id': first_authority.pk,
                'authority_name': 'A First Authority',
                'authority_type': 'Police',
                'district': 'First district',
                'email': 'first@example.invalid',
                'phone_number': '1111111111',
            },
        )
        self.assertEqual(
            result['agent_tools_called'],
            [
                'retrieve_safety_measures',
                'get_emergency_contact',
                'send_emergency_email',
            ],
        )
        self.assertEqual(chat_mock.call_count, 3)
        self.assertEqual(
            [
                call.kwargs['tools'][0]['function']['name']
                for call in chat_mock.call_args_list
            ],
            [
                'retrieve_safety_measures',
                'get_emergency_contact',
                'send_emergency_email',
            ],
        )
        self.assertEqual(result['email_status'], 'dry_run')
        self.assertEqual(result['recipient'], 'first@example.invalid')
        self.assertIn('Observation ID:', result['email_preview']['message'])
        self.assertIn('Use the cited safety guidance.', result['email_preview']['message'])

    @patch('observations.response_agent.chat')
    @patch('observations.response_agent.ask_rag')
    def test_positive_prediction_ignores_arguments_for_no_argument_tools(
        self,
        ask_rag_mock,
        chat_mock,
    ):
        ask_rag_mock.return_value = {
            'answer': 'Use the cited safety guidance.',
            'sources': [{'page': 1, 'score': 0.9}],
        }
        chat_mock.side_effect = [
            self._tool_response(
                'retrieve_safety_measures',
                {'observation_id': self.observation.pk},
            ),
            self._tool_response(
                'get_emergency_contact',
                '{"location_id": 123}',
            ),
            self._tool_response('send_emergency_email'),
        ]

        with (
            patch(
                'observations.response_agent.get_emergency_contact',
                wraps=get_emergency_contact,
            ) as lookup,
            override_settings(LANDSLIDE_EMAIL_DRY_RUN=True),
        ):
            result = run_landslide_response_agent(self.observation.pk)

        lookup.assert_called_once_with()
        self.assertIn('emergency_contact', result)
        self.assertEqual(
            result['agent_tools_called'],
            [
                'retrieve_safety_measures',
                'get_emergency_contact',
                'send_emergency_email',
            ],
        )

    @patch('observations.response_agent.chat')
    @patch('observations.response_agent.ask_rag')
    def test_non_risk_prediction_does_not_run_agent_tools(
        self,
        ask_rag_mock,
        chat_mock,
    ):
        self.observation.landslide_prediction = 'No'
        self.observation.save(update_fields=['landslide_prediction'])
        output = StringIO()

        with patch('observations.response_agent.get_emergency_contact') as lookup:
            with redirect_stdout(output):
                result = run_landslide_response_agent(self.observation.pk)
        ask_rag_mock.assert_not_called()
        chat_mock.assert_not_called()
        lookup.assert_not_called()
        self.assertEqual(
            result,
            {
                'observation_id': self.observation.pk,
                'location_id': self.observation.location_id,
                'safety_precautions': None,
                'emergency_contact': None,
                'recipient': None,
                'email_status': 'skipped_prediction_no',
                'email_error': None,
                'agent_tools_called': [],
            },
        )
        self.assertEqual(output.getvalue(), '')

    @patch('observations.response_agent.chat')
    @patch('observations.response_agent.ask_rag')
    def test_positive_prediction_without_contact_returns_no_contact_message(
        self,
        ask_rag_mock,
        chat_mock,
    ):
        self.authority.delete()
        ask_rag_mock.return_value = {
            'answer': 'Use the cited safety guidance.',
            'sources': [{'page': 1, 'score': 0.9}],
        }
        self._configure_agent_tool_calls(chat_mock)

        with patch(
            'observations.response_agent.get_emergency_contact',
            wraps=get_emergency_contact,
        ) as lookup:
            result = run_landslide_response_agent(self.observation.pk)

        lookup.assert_called_once_with()
        self.assertEqual(
            result['emergency_contact'],
            {'message': 'No emergency contact is available.'},
        )
        self.assertEqual(
            result['agent_tools_called'],
            ['retrieve_safety_measures', 'get_emergency_contact'],
        )
        self.assertEqual(result['email_status'], 'skipped_no_contact')
        self.assertEqual(chat_mock.call_count, 2)

    @patch('observations.response_agent.chat')
    @patch('observations.response_agent.ask_rag')
    def test_positive_prediction_skips_email_if_contact_has_blank_email(
        self,
        ask_rag_mock,
        chat_mock,
    ):
        self.authority.email = ''
        self.authority.save(update_fields=['email'])
        ask_rag_mock.return_value = {
            'answer': 'Use this precaution.',
            'sources': [{'page': 1, 'score': 0.9}],
        }
        self._configure_agent_tool_calls(chat_mock, include_email=False)

        result = run_landslide_response_agent(self.observation.pk)

        self.assertEqual(result['email_status'], 'skipped_no_email')
        self.assertEqual(chat_mock.call_count, 2)
        self.assertNotIn('send_emergency_email', result['agent_tools_called'])

    @patch('observations.response_agent.send_mail', return_value=1)
    def test_send_emergency_email_reports_success_only_after_mail_backend_success(
        self,
        send_mail_mock,
    ):
        contact = get_emergency_contact()

        with override_settings(
            LANDSLIDE_EMAIL_DRY_RUN=False,
            DEFAULT_FROM_EMAIL='sender@example.invalid',
        ):
            result = send_emergency_email(
                self.observation,
                {
                    'recommendation': 'Move away from unstable slopes.',
                    'source_documents': ['Landslide_safety.pdf (page 1)'],
                },
                contact,
            )

        self.assertEqual(result['status'], 'success')
        send_mail_mock.assert_called_once()
        self.assertEqual(
            send_mail_mock.call_args.kwargs['recipient_list'],
            ['verified@example.invalid'],
        )
        self.assertIn(
            'Move away from unstable slopes.',
            send_mail_mock.call_args.kwargs['message'],
        )

    @patch(
        'observations.response_agent.send_mail',
        side_effect=smtplib.SMTPException('SMTP unavailable'),
    )
    def test_send_emergency_email_reports_failure_without_claiming_success(
        self,
        send_mail_mock,
    ):
        contact = get_emergency_contact()

        with override_settings(
            LANDSLIDE_EMAIL_DRY_RUN=False,
            DEFAULT_FROM_EMAIL='sender@example.invalid',
        ):
            result = send_emergency_email(
                self.observation,
                {
                    'recommendation': 'Move away from unstable slopes.',
                    'source_documents': ['Landslide_safety.pdf (page 1)'],
                },
                contact,
            )

        self.assertEqual(result['status'], 'failed')
        self.assertIn('SMTP unavailable', result['error'])

    @patch(
        'observations.response_agent.send_mail',
        side_effect=smtplib.SMTPAuthenticationError(
            535,
            b'Authentication failed',
        ),
    )
    def test_send_emergency_email_reports_authentication_failure_safely(
        self,
        send_mail_mock,
    ):
        contact = get_emergency_contact()

        with override_settings(
            LANDSLIDE_EMAIL_DRY_RUN=False,
            DEFAULT_FROM_EMAIL='sender@example.invalid',
        ):
            result = send_emergency_email(
                self.observation,
                {'recommendation': 'Use caution.', 'source_documents': []},
                contact,
            )

        self.assertEqual(result['status'], 'failed')
        self.assertIn('Google App Password', result['error'])
        self.assertNotIn('Authentication failed', result['error'])

    @patch(
        'observations.response_agent.send_mail',
        side_effect=smtplib.SMTPServerDisconnected(
            'Connection unexpectedly closed',
        ),
    )
    def test_send_emergency_email_reports_smtp_disconnect_actionably(
        self,
        send_mail_mock,
    ):
        contact = get_emergency_contact()

        with override_settings(
            LANDSLIDE_EMAIL_DRY_RUN=False,
            DEFAULT_FROM_EMAIL='sender@example.invalid',
        ):
            result = send_emergency_email(
                self.observation,
                {'recommendation': 'Use caution.', 'source_documents': []},
                contact,
            )

        self.assertEqual(result['status'], 'failed')
        self.assertIn('Connection unexpectedly closed', result['error'])
        self.assertIn('same Gmail username and App Password', result['error'])
        send_mail_mock.assert_called_once()

    @patch(
        'observations.response_agent.send_mail',
        side_effect=smtplib.SMTPException('SMTP unavailable'),
    )
    @patch('observations.response_agent.chat')
    @patch('observations.response_agent.ask_rag')
    def test_agent_reports_email_failure_after_invoking_send_tool(
        self,
        ask_rag_mock,
        chat_mock,
        send_mail_mock,
    ):
        ask_rag_mock.return_value = {
            'answer': 'Move away from unstable slopes.',
            'sources': [{'page': 1, 'score': 0.9}],
        }
        self._configure_agent_tool_calls(chat_mock)

        with override_settings(
            LANDSLIDE_EMAIL_DRY_RUN=False,
            DEFAULT_FROM_EMAIL='sender@example.invalid',
        ):
            result = run_landslide_response_agent(self.observation.pk)

        self.assertEqual(result['email_status'], 'failed')
        self.assertEqual(result['recipient'], 'verified@example.invalid')
        self.assertIn('SMTP unavailable', result['email_error'])
        self.assertEqual(
            result['agent_tools_called'],
            [
                'retrieve_safety_measures',
                'get_emergency_contact',
                'send_emergency_email',
            ],
        )
        send_mail_mock.assert_called_once()

    def test_tool_returns_first_contact_with_blank_email_and_phone(self):
        self.authority.email = ''
        self.authority.phone_number = ''
        self.authority.save(update_fields=['email', 'phone_number'])
        EmergencyAuthority.objects.create(
            authority_name='Z Later Authority',
            authority_type=EmergencyAuthority.AuthorityType.OTHER,
            location_id=2,
            district='Later district',
        )

        result = _tool_result('get_emergency_contact', self.observation)

        self.assertEqual(result['id'], self.authority.pk)
        self.assertEqual(result['email'], '')
        self.assertEqual(result['phone_number'], '')

    def test_tool_returns_first_contact_even_if_inactive_and_unverified(self):
        self.authority.is_active = False
        self.authority.is_verified = False
        self.authority.save(update_fields=['is_active', 'is_verified'])

        result = _tool_result('get_emergency_contact', self.observation)

        self.assertEqual(result['id'], self.authority.pk)
        self.assertEqual(result['authority_name'], self.authority.authority_name)


class EmergencyAuthorityFixtureTests(TestCase):
    def test_demo_fixture_loads_as_inactive_and_unverified(self):
        call_command('loaddata', 'demo_emergency_authorities', verbosity=0)

        demo_authority = EmergencyAuthority.objects.get(
            authority_name='DEMO ONLY - Not an official authority',
        )
        self.assertEqual(demo_authority.email, 'demo-authority@example.invalid')
        self.assertEqual(demo_authority.phone_number, '0000000000')
        self.assertFalse(demo_authority.is_active)
        self.assertFalse(demo_authority.is_verified)
        result = get_emergency_contact()
        self.assertEqual(result['id'], demo_authority.pk)


class LandslidePredictionTests(SimpleTestCase):
    observation = {
        'max_temp_c': 27.5,
        'humidity_pct': 84.0,
        'wind_speed_kmh': 12.0,
        'rainfall_mm': 35.5,
        'slope_angle_deg': 32,
        'vegetation_cover': 'Medium',
    }

    @patch('observations.prediction.load_model')
    def test_predicts_using_notebook_one_hot_feature_schema(self, load_model):
        model = load_model.return_value
        model.feature_names_in_ = ONE_HOT_FEATURE_COLUMNS
        model.classes_ = [0, 1]
        model.predict.return_value = [1]
        model.predict_proba.return_value = np.array([[0.2, 0.8]])

        result = predict_landslide(self.observation)

        self.assertEqual(result['landslide_prediction'], 'Yes')
        self.assertEqual(result['landslide_probability'], 0.8)
        model_input = model.predict.call_args.args[0]
        self.assertEqual(tuple(model_input.columns), ONE_HOT_FEATURE_COLUMNS)
        self.assertEqual(model_input.loc[0, 'Vegetation_Cover_Medium'], 1)
        self.assertEqual(model_input.loc[0, 'Vegetation_Cover_High'], 0)
        self.assertEqual(model_input.loc[0, 'Vegetation_Cover_Low'], 0)

    @patch('observations.prediction.load_model')
    def test_predicts_using_raw_feature_schema(self, load_model):
        model = load_model.return_value
        model.feature_names_in_ = FEATURE_COLUMNS
        model.classes_ = [0, 1]
        model.predict.return_value = [0]
        model.predict_proba.return_value = np.array([[0.7, 0.3]])

        result = predict_landslide(self.observation)

        self.assertEqual(result['landslide_prediction'], 'No')
        self.assertEqual(result['landslide_probability'], 0.3)
        model_input = model.predict.call_args.args[0]
        self.assertEqual(tuple(model_input.columns), FEATURE_COLUMNS)
        self.assertEqual(model_input.loc[0, 'Vegetation_Cover'], 'Medium')


class SafetyAssistantApiTests(APITestCase):
    url = '/api/safety-assistant/'

    @patch(
        'observations.views.ask_rag',
        return_value={
            'answer': 'Move away from the path of a landslide [page 1].',
            'sources': [
                {'page': 1, 'score': 0.83, 'text': 'Move away from the path.'}
            ],
        },
    )
    def test_post_returns_document_answer_and_sources(self, ask_rag):
        response = self.client.post(
            self.url,
            {'question': 'What should I do during a landslide?'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['answer'], 'Move away from the path of a landslide [page 1].')
        self.assertEqual(response.data['sources'][0]['page'], 1)
        ask_rag.assert_called_once_with('What should I do during a landslide?')

    @patch('observations.views.ask_rag')
    def test_post_rejects_short_question(self, ask_rag):
        response = self.client.post(
            self.url,
            {'question': '  '},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        ask_rag.assert_not_called()

    @patch(
        'observations.views.ask_rag',
        side_effect=RagConfigurationError('Set PINECONE_API_KEY in .env.'),
    )
    def test_post_reports_missing_pinecone_configuration(self, _ask_rag):
        response = self.client.post(
            self.url,
            {'question': 'How should I stay safe?'},
            format='json',
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class RagDocumentTests(SimpleTestCase):
    def test_create_chunks_keeps_overlap_between_chunks(self):
        chunks = create_chunks('one two three four five six', chunk_size=4, overlap=2)

        self.assertEqual(
            chunks,
            ['one two three four', 'three four five six'],
        )

    def test_create_chunks_rejects_invalid_overlap(self):
        with self.assertRaises(ValueError):
            create_chunks('some words', chunk_size=4, overlap=4)

    def test_load_pdf_pages_reads_project_safety_guide(self):
        pages = load_pdf_pages()

        self.assertTrue(pages)
        self.assertIn('LANDSLIDE', pages[0][1])
        self.assertIn('-', pages[0][1])
