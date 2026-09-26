import json
import time
from unittest.mock import patch

import pytest
from agents.news import portfolio_context as pc, brief, intelligence as intel
from test_news_brief import article


def test_policy_stage_does_not_confuse_committee_vote_with_passage():
    assert pc.bill_stage('Ordered to be Reported in the Nature of a Substitute by Yeas and Nays: 35 - 0.') == 'Committee reported; not enacted'
    assert pc.bill_stage('Became Public Law No: 119-12.') == 'Enacted'


def test_context_excludes_stale_macro_and_irrelevant_travel_bill(tmp_path):
    now = time.time()
    (tmp_path/'macro_cache.json').write_text(json.dumps({'_fetched_at':now, 'date':pc.today_eastern().isoformat(),
        'yield_10y':5.18, 'headlines':['Old undated story must not enter prompt'],
        'measurements':{'fed_funds':{'value':9,'stale':True,'source':'FRED','series_id':'FEDFUNDS'}}}))
    bills = [dict(bill_id='H.R. 9382', title='Link applications of family members throughout the NEXUS application process',
                  domains=['trade'], action_date=pc.today_eastern().isoformat(), latest_action='Referred to committee',
                  url='https://www.congress.gov/bill/119th-congress/house-bill/9382'),
             dict(bill_id='H.R. 8893',title='Protecting Consumers from Deceptive AI Act',domains=['consumer'],
                  action_date=pc.today_eastern().isoformat(),latest_action='Ordered to be Reported by Yeas and Nays: 35 - 0.',
                  url='https://www.congress.gov/bill/119th-congress/house-bill/8893')]
    (tmp_path/'bills_cache.json').write_text(json.dumps({'_fetched_at':now,'bills':bills}))
    result = pc.load_context(tmp_path,['AAA','FUND'],{'AAA':{'domains':['trade','technology']},'FUND':{'domains':['technology'],'is_fund':True}},now)
    assert 'M:yield_10y' in result['sources'] and 'M:fed_funds' not in result['sources']
    assert result['policy_count'] == 1
    policy = result['sources']['P1']
    assert policy['affected_tickers'] == ['AAA']
    assert policy['stage'] == 'Committee reported; not enacted'
    assert not policy['detail_available']
    assert 'Old undated' not in json.dumps(result)


def analysis_fixture():
    selected = {'AAA':[article()]}
    context = {'AAA':{'weight_pct':7},'BBB':{'weight_pct':12}}
    aux = {'sources':{'M:rates':{'kind':'macro','title':'10Y yield','text':'10Y yield 5.18 percent.','affected_tickers':['AAA','BBB'],'url':'https://example.com/rates'}}}
    parsed = {'brief':[['risk','Funding exposure',['AAA','BBB'],'The 10Y yield stands at 5.18 percent.',
                'Refinancing at higher rates could pressure cash generation; exposure depends on debt maturity.',
                'Review upcoming debt maturities before adding exposure.',['M:rates']]]}
    return selected, context, aux, parsed


def test_portfolio_analysis_reaches_holdings_without_direct_news():
    selected, context, aux, parsed = analysis_fixture()
    result = pc.validate_analysis(parsed,selected,context,aux,intel._article_id)
    assert result['insights'][0]['tickers'] == ['AAA','BBB']
    assert result['insights'][0]['exposure_pct'] == 19
    assert 'BBB' not in selected


@pytest.mark.parametrize('failure',['unknown_source','unheld_ticker','invented_number','invented_threshold','wrong_exposure'])
def test_portfolio_grounding_rejects_invalid_conclusions(failure):
    selected, context, aux, parsed = analysis_fixture()
    if failure == 'unknown_source': parsed['brief'][0][6] = ['madeup']
    if failure == 'unheld_ticker': parsed['brief'][0][2] = ['CCC']
    if failure == 'invented_number': parsed['brief'][0][3] = 'The yield reached 99 percent.'
    if failure == 'invented_threshold': parsed['brief'][0][5] = 'Require $100 million per week before adding.'
    if failure == 'wrong_exposure': aux['sources']['M:rates']['affected_tickers'] = ['AAA']
    with pytest.raises(ValueError): pc.validate_analysis(parsed,selected,context,aux,intel._article_id)


def test_title_only_policy_is_watch_not_confirmed_opportunity():
    selected, context, aux, parsed = analysis_fixture()
    aux['sources']['P1'] = {'kind':'policy','title':'H.R. 5109','text':'H.R. 5109 referred to committee.',
                          'affected_tickers':['AAA'],'stage':'In committee; not enacted','detail_available':False}
    parsed['brief'] = [['opportunity','Credential proposal',['AAA'],'H.R. 5109 remains in committee.',
                      'Possible operational relevance needs verification from bill text.', 'Read the committee text before changing assumptions.',['P1']]]
    result = pc.validate_analysis(parsed,selected,context,aux,intel._article_id)
    assert result['insights'][0]['kind'] == 'policy'
    assert 'unverified' in result['insights'][0]['evidence_level']
    parsed['brief'][0][3] = 'H.R. 5109 is now law.'
    with pytest.raises(ValueError,match='Pending legislation'): pc.validate_analysis(parsed,selected,context,aux,intel._article_id)


def test_prompt_requires_mechanism_action_and_policy_evidence():
    selected, context, aux, _ = analysis_fixture()
    prompt = brief.build_prompt(selected,context,aux)
    assert 'business transmission mechanism' in prompt
    assert 'M:rates' in prompt and 'BBB' in prompt
    assert 'Pending bills are not law' in prompt
    assert '600 words' in prompt


def test_empty_analysis_is_allowed_rather_than_manufacturing_opportunity():
    selected, context, aux, _ = analysis_fixture()
    assert pc.validate_analysis({'brief':[]},selected,context,aux,intel._article_id)['insights'] == []


def test_short_source_ids_map_to_exact_articles():
    selected = {'AAA':[article()], 'BBB':[article('BBB')]}
    manifest = pc.source_manifest(selected, {'sources':{}}, intel._article_id)
    assert manifest['N1']['article_id'] == intel._article_id(article())
    assert manifest['N2']['affected_tickers'] == ['BBB']


def test_projected_company_event_keeps_grounding_and_reviewed_status():
    selected = {'AAA':[article()], 'BBB':[article('BBB')]}
    sources = pc.source_manifest(selected, {'sources':{}}, intel._article_id)
    analysis = {'sources':sources, 'insights':[{'tickers':['AAA'],'source_ids':['N1'],
        'what_changed':'Revenue guidance rose to $20 million.','portfolio_impact':'Supports growth if execution follows.',
        'watch_or_action':'Compare actual revenue with guidance.',
        'event':{'type':'GUIDANCE_CHANGE','direction':'POSITIVE','magnitude':'MEDIUM'}}]}
    summaries, events = brief.project_analysis(analysis,selected)
    assert summaries['AAA']['status'] == 'material'
    assert summaries['BBB']['status'] == 'reviewed'
    assert 'BBB' not in events
    assert events['AAA'][0]['article_ids'] == [intel._article_id(article())]


def test_title_quote_repair_does_not_invent_missing_evidence():
    text = '{\n"brief":[{\n"title": Missing opening quote",\n"source_ids":["N1"]\n}]} '
    assert brief.parse_model_json(text)['brief'][0]['title'] == 'Missing opening quote'
    with pytest.raises(json.JSONDecodeError): brief.parse_model_json('{"brief":[')


def test_missing_official_summary_is_fetched_and_cached(tmp_path, monkeypatch):
    monkeypatch.setenv('CONGRESS_API_KEY', 'test-key')
    def auxiliary():
        return {'sources':{'P1':{'kind':'policy','url':'https://www.congress.gov/bill/119th-congress/house-bill/5109',
            'as_of':'2026-09-16','text':'H.R. 5109. No bill text/CRS summary available: do not invent.', 'detail_available':False}}}
    summary = 'TSA must improve access to credentials for prisoners before release.'
    with patch('macro_context._fetch_crs_summary', return_value=summary) as fetch:
        result = pc.hydrate_policy(auxiliary(),tmp_path,time.monotonic()+1)
        assert result['sources']['P1']['detail_available']
        assert summary in result['sources']['P1']['text']
        assert 'No bill text' not in result['sources']['P1']['text']
        fetch.assert_called_once_with(119,'hr','5109','test-key')
        pc.hydrate_policy(auxiliary(),tmp_path,time.monotonic()+1)
        assert fetch.call_count == 1


def test_congress_list_without_optional_has_summary_still_fetches_summary():
    import io
    import macro_context as mc
    response = {'bills':[{'type':'HR','number':'5109','congress':119,
        'title':'Transportation Worker Identification Credential Efficiency Act',
        'latestAction':{'text':'Referred to committee','actionDate':'2026-09-16'}}]}
    with patch.object(mc.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())), \
         patch.object(mc,'_fetch_crs_summary',return_value='Official summary') as fetch, patch.object(mc.time,'sleep'):
        bills = mc._fetch_congress_api_bills('test-key')
    fetch.assert_called_once_with(119,'hr','5109','test-key')
    assert bills[0]['summary'] == 'Official summary'


def test_invalid_card_does_not_discard_independently_grounded_analysis():
    selected, context, aux, parsed = analysis_fixture()
    invalid = list(parsed['brief'][0])
    invalid[5] = 'Require an invented $100 million threshold.'
    parsed['brief'].append(invalid)
    result = pc.validate_analysis(parsed,selected,context,aux,intel._article_id)
    assert len(result['insights']) == 1
    assert result['validation']['withheld'] == 1
    assert 'withheld' in result['context_status']['limitations'][-1]
    assert 'limitations' not in aux


def test_review_packet_contains_only_cited_evidence_and_actual_businesses():
    selected = {'AAA':[article()], 'BBB':[article('BBB')]}
    context = {'AAA':{'business':'Manufacturer'},'BBB':{'business':'Unrelated'}}
    draft = {'brief':[{'tickers':['AAA'],'source_ids':['N1'],'title':'Diligence'}]}
    prompt = brief.review_prompt(draft,selected,context,{'sources':{}})
    assert 'Manufacturer' in prompt
    assert 'Unrelated' not in prompt
    assert '"N2"' not in prompt
    assert 'LEGISLATIVE CONNECTION RULE' in prompt
    assert 'Conflicting reports' in prompt


def test_share_class_alias_does_not_hide_all_portfolio_weights():
    result = brief.current_position_prices([{'Stock':'BRK.B','Shares':'2'},{'Stock':'AAA','Shares':'1'}],
        {'BRK-B':{'price':100},'AAA':{'price':200}})
    assert result['BRK.B']['weight_pct'] == 50
    assert result['BRK.B']['price'] == 100
    assert result['AAA']['weight_pct'] == 50
