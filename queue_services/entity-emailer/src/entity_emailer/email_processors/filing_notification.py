# Copyright © 2019 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Email processing rules and actions for Incorporation Application notifications."""
from __future__ import annotations

import base64
import re
from http import HTTPStatus
from pathlib import Path

import requests
from entity_queue_common.service_utils import logger
from flask import current_app
from jinja2 import Template
from legal_api.models import Filing
from sentry_sdk import capture_message

from entity_emailer.email_processors import get_filing_info, get_recipients, substitute_template_parts


FILING_TYPE_CONVERTER = {
    'incorporationApplication': 'IA',
    'annualReport': 'AR',
    'changeOfDirectors': 'COD',
    'changeOfAddress': 'COA'
}


def _get_pdfs(status: str, token: str, business: dict, filing: Filing, filing_date_time: str) -> list:
    # pylint: disable=too-many-locals, too-many-branches
    """Get the pdfs for the incorporation output."""
    pdfs = []
    headers = {
        'Accept': 'application/pdf',
        'Authorization': f'Bearer {token}'
    }
    if status == Filing.Status.PAID.value:
        # add filing pdf
        filing_pdf = requests.get(
            f'{current_app.config.get("LEGAL_API_URL")}/businesses/{business["identifier"]}/filings/{filing.id}',
            headers=headers
        )
        if filing_pdf.status_code != HTTPStatus.OK:
            logger.error('Failed to get pdf for filing: %s', filing.id)
            capture_message(f'Email Queue: filing id={filing.id}, error=pdf generation', level='error')
        else:
            filing_pdf_encoded = base64.b64encode(filing_pdf.content)
            file_name = filing.filing_type[0].upper() + \
                ' '.join(re.findall('[a-zA-Z][^A-Z]*', filing.filing_type[1:]))
            pdfs.append(
                {
                    'fileName': f'Notice of {file_name}.pdf',
                    'fileBytes': filing_pdf_encoded.decode('utf-8'),
                    'fileUrl': '',
                    'attachOrder': '1'
                }
            )
        # add receipt pdf
        if filing.filing_type == 'incorporationApplication':
            corp_name = filing.filing_json['filing']['incorporationApplication']['nameRequest'].get(
                'legalName', 'Numbered Company')
        else:
            corp_name = business.get('legalName')

        receipt = requests.post(
            f'{current_app.config.get("PAY_API_URL")}/{filing.payment_token}/receipts',
            json={
                'corpName': corp_name,
                'filingDateTime': filing_date_time
            },
            headers=headers
        )
        if receipt.status_code != HTTPStatus.CREATED:
            logger.error('Failed to get receipt pdf for filing: %s', filing.id)
            capture_message(f'Email Queue: filing id={filing.id}, error=receipt generation', level='error')
        else:
            receipt_encoded = base64.b64encode(receipt.content)
            pdfs.append(
                {
                    'fileName': 'Receipt.pdf',
                    'fileBytes': receipt_encoded.decode('utf-8'),
                    'fileUrl': '',
                    'attachOrder': '2'
                }
            )
    if status == Filing.Status.COMPLETED.value:
        # add notice of articles
        noa = requests.get(
            f'{current_app.config.get("LEGAL_API_URL")}/businesses/{business["identifier"]}/filings/{filing.id}'
            '?type=noa',
            headers=headers
        )
        if noa.status_code != HTTPStatus.OK:
            logger.error('Failed to get noa pdf for filing: %s', filing.id)
            capture_message(f'Email Queue: filing id={filing.id}, error=noa generation', level='error')
        else:
            noa_encoded = base64.b64encode(noa.content)
            pdfs.append(
                {
                    'fileName': 'Notice of Articles.pdf',
                    'fileBytes': noa_encoded.decode('utf-8'),
                    'fileUrl': '',
                    'attachOrder': '1'
                }
            )

        if filing.filing_type == 'incorporationApplication':
            # add certificate
            certificate = requests.get(
                f'{current_app.config.get("LEGAL_API_URL")}/businesses/{business["identifier"]}/filings/{filing.id}'
                '?type=certificate',
                headers=headers
            )
            if certificate.status_code != HTTPStatus.OK:
                logger.error('Failed to get certificate pdf for filing: %s', filing.id)
                capture_message(f'Email Queue: filing id={filing.id}, error=certificate generation', level='error')
            else:
                certificate_encoded = base64.b64encode(certificate.content)
                pdfs.append(
                    {
                        'fileName': 'Incorporation Certificate.pdf',
                        'fileBytes': certificate_encoded.decode('utf-8'),
                        'fileUrl': '',
                        'attachOrder': '2'
                    }
                )

    return pdfs


def process(email_info: dict, token: str) -> dict:  # pylint: disable=too-many-locals
    """Build the email for Business Number notification."""
    logger.debug('filing_notification: %s', email_info)
    # get template and fill in parts
    filing_type, status = email_info['type'], email_info['option']

    template = Path(
        f'{current_app.config.get("TEMPLATE_PATH")}/BC-{FILING_TYPE_CONVERTER[filing_type]}-{status}.html'
    ).read_text()
    filled_template = substitute_template_parts(template)
    # get template vars from filing
    filing, business, leg_tmz_filing_date, leg_tmz_effective_date = get_filing_info(email_info['filingId'])
    filing_name = filing.filing_type[0].upper() + ' '.join(re.findall('[a-zA-Z][^A-Z]*', filing.filing_type[1:]))
    # render template with vars
    jnja_template = Template(filled_template, autoescape=True)
    html_out = jnja_template.render(
        business=business,
        filing=(filing.json)['filing'][f'{filing_type}'],
        header=(filing.json)['filing']['header'],
        filing_date_time=leg_tmz_filing_date,
        effective_date_time=leg_tmz_effective_date,
        entity_dashboard_url=current_app.config.get('DASHBOARD_URL') +
        (filing.json)['filing']['business'].get('identifier', ''),
        email_header=filing_name.upper()
    )

    # get attachments
    pdfs = _get_pdfs(status, token, business, filing, leg_tmz_filing_date)

    # get recipients
    recipients = get_recipients(status, filing.filing_json, token)

    # assign subject
    if status == Filing.Status.PAID.value:
        if filing_type == 'incorporationApplication':
            subject = 'Confirmation of Filing from the Business Registry'
        elif filing_type in ['changeOfAddress', 'changeOfDirectors']:
            address_director = [x for x in ['Address', 'Director'] if x in filing_type][0]
            subject = f'Confirmation of {address_director} Change'
        elif filing_type == 'annualReport':
            subject = 'Confirmation of Annual Report'

    elif status == Filing.Status.COMPLETED.value:
        if filing_type == 'incorporationApplication':
            subject = 'Incorporation Documents from the Business Registry'
        elif filing_type in ['changeOfAddress', 'changeOfDirectors']:
            subject = 'Notice of Articles'

    if not subject:  # fallback case - should never happen
        subject = 'Notification from the BC Business Registry'

    if filing.filing_type == 'incorporationApplication':
        legal_name = \
            filing.filing_json['filing']['incorporationApplication']['nameRequest'].get('legalName', None)
    else:
        legal_name = business.get('legalName', None)

    subject = f'{legal_name} - {subject}' if legal_name else subject

    return {
        'recipients': recipients,
        'requestBy': 'BCRegistries@gov.bc.ca',
        'content': {
            'subject': subject,
            'body': f'{html_out}',
            'attachments': pdfs
        }
    }