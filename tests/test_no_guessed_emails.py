"""Regression tests for the riversnap fork's email-safety guarantee.

The fork's core promise is that an address Scout never actually observed cannot
reach an outreach list. These tests fail loudly if an upstream merge reintroduces
a guessing path.

Run: python -m pytest tests/ -v
"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(allow_guessing: str):
    """Reimport enrichment with the flag set, since it is read at import time."""
    os.environ['SCOUT_ALLOW_GUESSED_EMAILS'] = allow_guessing
    for mod in [m for m in sys.modules if m.startswith('app')]:
        del sys.modules[mod]
    return importlib.import_module('app.scrapers.enrichment')


def _stub_network(enrichment, calls):
    """Replace every synthesising / network call with a tripwire."""
    E = enrichment.LeadEnricher
    E._generate_email_candidates = lambda s, n, w: calls.append('generate') or ['guess@acme.com']
    E._predict_email_from_pattern = lambda s, n, w, e: calls.append('predict') or 'pattern@acme.com'
    E._verify_email_smtp = lambda s, e: calls.append('smtp') or {'exists': True, 'accept_all': False, 'score': 90}
    E._find_company_domain = lambda s, d: 'acme.com'
    E._deep_scrape_website = lambda s, w: {'email': None, 'phone': None, 'all_emails': []}


NO_CONTACT_LEAD = {'full_name': 'Jane Doe', 'username': 'janedoe', 'bio': 'no contact here', 'website': ''}


def test_no_guessed_email_by_default():
    """A lead with a resolvable domain but no published address yields nothing."""
    enrichment = _load('false')
    calls = []
    _stub_network(enrichment, calls)

    out = enrichment.LeadEnricher().enrich_lead(dict(NO_CONTACT_LEAD))

    assert out.get('email') is None, f"invented an address: {out.get('email')}"
    assert out.get('possible_emails') is None, "leaked a possible_emails list into the export"
    assert calls == [], f"called a synthesising path despite the guard: {calls}"


def test_guessing_can_be_re_enabled_explicitly():
    """The capability is gated, not deleted — research use can opt back in."""
    enrichment = _load('true')
    calls = []
    _stub_network(enrichment, calls)

    out = enrichment.LeadEnricher().enrich_lead(dict(NO_CONTACT_LEAD))

    assert out.get('email') == 'pattern@acme.com'
    assert 'predict' in calls


def test_observed_bio_email_still_survives():
    """The guard must not cost us the addresses creators actually publish."""
    enrichment = _load('false')
    E = enrichment.LeadEnricher
    E._verify_email_smtp = lambda s, e: {'exists': False, 'accept_all': False, 'score': 0}
    E._deep_scrape_website = lambda s, w: {'email': None, 'phone': None, 'all_emails': []}
    E._find_company_domain = lambda s, d: None

    bio = "Food, travels & everything I love\n\U0001F48C whatlizhaseaten@gmail.com • DM!"
    out = E().enrich_lead(
        {'full_name': 'Liz', 'username': 'whatlizhaseaten', 'bio': bio, 'website': ''}
    )

    assert out['email'] == 'whatlizhaseaten@gmail.com'
    assert out['email_source'] == 'bio'


def test_backstop_drops_unobserved_source():
    """Defence in depth: even a directly-injected guess is stripped on the way out."""
    enrichment = _load('false')
    E = enrichment.LeadEnricher
    E._verify_email_smtp = lambda s, e: {'exists': False, 'accept_all': False, 'score': 0}
    E._deep_scrape_website = lambda s, w: {'email': None, 'phone': None, 'all_emails': []}
    E._find_company_domain = lambda s, d: None
    # Simulate a future upstream merge appending a guessed candidate.
    original = E._extract_from_text
    E._extract_from_text = lambda s, t: {'email': None, 'phone': None}

    out = E().enrich_lead({'full_name': 'Jane Doe', 'username': 'jd', 'bio': '', 'website': ''})
    E._extract_from_text = original

    assert out.get('email') is None
    assert out.get('email_source') not in enrichment.OBSERVED_SOURCES or out.get('email') is None


def test_no_upstream_kill_switch():
    """The fork must never regain a remote disable path."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = open(os.path.join(root, 'scout.py'), encoding='utf-8').read()

    assert '_check_for_updates' not in source, "upstream update checker reintroduced"
    assert 'api.github.com/repos' not in source, "fork phones home to an upstream release API"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
