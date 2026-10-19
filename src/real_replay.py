"""Pack-specific replay adapter for the supplied One User, One Agent dataset.

Uses only the supplied data pack. The policy is deterministic and auditable; model proposals
are deliberately not trusted for eligibility or safety checks.
"""
from __future__ import annotations
import csv, json, re, time, hashlib, math
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .utils import read_jsonl, read_json, write_jsonl, parse_dt, iso
from .model_provider import ReplayFaultProvider

UTC = timezone.utc
IST = ZoneInfo('Asia/Kolkata')

def csv_rows(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def json_dump(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding='utf-8')

def dt(value): return parse_dt(value)
def event_name(e): return str(e.get('event', '')).lower()
def uid(e): return str(e.get('user_id', ''))
def evtime(e): return dt(e.get('received_at') or e.get('deliver_at') or e.get('at'))
def dedupe_events(rows):
    by = {}
    for e in rows:
        k=e.get('event_id')
        if not k: continue
        old=by.get(k)
        if old is None or str(e.get('received_at','')) < str(old.get('received_at','')): by[k]=e
    return list(by.values())
def true_bool(v): return str(v).strip().lower() in ('true','1','yes')
def ist_day(value):
    d=dt(value)
    return d.astimezone(IST).date().isoformat() if d else None

def estimate_trigger_age_seconds(trigger):
    # Phone timestamps may be skewed; sent_at - occurred_at approximates offline buffering.
    occurred=dt(trigger.get('occurred_at')); sent=dt(trigger.get('sent_at'))
    return max(0,(sent-occurred).total_seconds()) if occurred and sent else None

def load_inputs(root):
    root=Path(root)
    profiles_by_user=defaultdict(list)
    for p in csv_rows(root/'data/profiles_snapshot.csv'): profiles_by_user[p['user_id']].append(p)
    profiles={u:max(rows,key=lambda r:r.get('updated_at','')) for u,rows in profiles_by_user.items()}
    catalogue=csv_rows(root/'data/catalogue.csv')
    cat_by_id={r['title_id']:r for r in catalogue}
    episodes=defaultdict(list)
    for e in csv_rows(root/'data/episodes.csv'): episodes[e['content_slug']].append(e)
    for vals in episodes.values(): vals.sort(key=lambda r:(int(r.get('season') or 0),int(r.get('episode') or 0)))
    events=dedupe_events(read_jsonl(root/'data/events.jsonl'))
    history=defaultdict(list)
    for e in events: history[uid(e)].append(e)
    for rows in history.values(): rows.sort(key=lambda e:str(e.get('received_at','')))
    arms={r['user_id']:r['arm'].lower() for r in csv_rows(root/'replay/arms.csv')}
    triggers=read_jsonl(root/'replay/triggers.jsonl')
    live=read_jsonl(root/'replay/live_events.jsonl')
    controls=read_jsonl(root/'replay/control_events.jsonl')
    faults={r['trigger_event_id']:r for r in read_jsonl(root/'replay/model_faults.jsonl')}
    goals=read_json(root/'config/goals.json',{})
    interventions=read_json(root/'config/interventions.json',{})
    pricing=read_json(root/'config/pricing.json',{})
    return locals()

def current_status(profile, history, at):
    status=profile.get('subscription_status') or 'unknown'
    snap=dt(profile.get('updated_at') or profile.get('snapshot_at'))
    paid_before=False
    for e in history:
        et=evtime(e)
        if not et or et>at: continue
        if event_name(e) in ('purchase_completed','subscription_renewed'):
            is_trial=true_bool(e.get('properties',{}).get('is_trial',False))
            if not is_trial: paid_before=True
            if snap and et>snap: status='active' if not is_trial else 'trial_active'
        elif event_name(e)=='subscription_lapsed' and (not snap or et>snap): status='lapsed'
    if paid_before and status=='never': status='active'
    return status, paid_before

def dialect_for(trigger, profile):
    app=trigger.get('app_dialect')
    profile_d=profile.get('preferred_dialect')
    link=trigger.get('properties',{}).get('deeplink','')
    m=re.search(r'ott://c/[^/]+/(d[1-6])/title/', link)
    campaign=m.group(1) if m else None
    chosen=app or profile_d or campaign
    conflicts=[]
    for source,val in [('profile',profile_d),('campaign_link',campaign)]:
        if val and chosen and val!=chosen: conflicts.append({'fact':'dialect','source':source,'value':val,'chosen':chosen,'resolution':'current app setting wins; profile is stale baseline and campaign link is context only'})
    return chosen, ('trigger.app_dialect' if app else 'profile.preferred_dialect' if profile_d else 'campaign_link' if campaign else 'unknown'), conflicts

def profile_signup(profile, history):
    s=profile.get('signup_at')
    if s: return dt(s), 'profiles_snapshot.csv'
    vals=[evtime(e) for e in history if event_name(e)=='signup_completed']
    vals=[x for x in vals if x]
    return (min(vals),'event:signup_completed') if vals else (None,None)

def eligibility_goal(profile, history, catalogue, episodes, now, goals_doc, corrected_goals=None):
    corrected_goals = corrected_goals or set()
    """Choose one measurable goal using explicit pack rules; skip goals without an event signal."""
    status, ever_paid=current_status(profile, history, now)
    signup, signup_src=profile_signup(profile, history)
    evs=[e for e in history if evtime(e) and evtime(e)<=now]
    def es(name): return [e for e in evs if event_name(e)==name]
    plays=es('play_started'); completes=es('episode_completed'); opens=es('app_open')
    # Goals with no supported signal are intentionally not candidates (G10, G11).
    candidates=[]
    age_days=(now-signup).total_seconds()/86400 if signup else None
    if age_days is not None and 0 <= age_days <= 7 and not plays:
        candidates.append(('G01','first_play_24h','play_started',24,'New signup within 7 days and no observed play_started event.'))
    if not completes:
        candidates.append(('G02','first_full_episode_3d','episode_completed',72,'No observed episode_completed event in available history.'))
    # Resume an unfinished show/micro-drama after at least 3 days of inactivity.
    last_play_by_slug={}
    for e in plays:
        tid=e.get('properties',{}).get('title_id'); t=next((x for x in catalogue if x['title_id']==tid),None)
        if t and t.get('content_type') in ('show','micro_drama'):
            slug=t['content_slug']; last_play_by_slug[slug]=max(last_play_by_slug.get(slug,datetime.min.replace(tzinfo=UTC)),evtime(e))
    completed_ids={e.get('properties',{}).get('episode_id') for e in completes}
    resume_slugs=[]
    for slug,last in last_play_by_slug.items():
        eps=episodes.get(slug,[])
        if now-last>=timedelta(days=3) and len([x for x in eps if x['episode_id'] not in completed_ids])>0:
            resume_slugs.append(slug)
    if resume_slugs:
        candidates.append(('G07','resume_series_3d','play_started',72,'An unfinished show/micro-drama has been inactive for at least 3 days.'))
    if status=='trial_active': candidates.append(('G04','trial_to_paid_7d','purchase_completed',168,'Resolved subscription status is trial_active.'))
    if status=='never' and not ever_paid: candidates.append(('G05','first_paid_7d','purchase_completed',168,'No paid purchase observed and subscription status is never.'))
    if status=='lapsed': candidates.append(('G06','reactivate_lapsed_14d','purchase_completed',336,'Resolved subscription status is lapsed.'))
    if status=='active':
        recent_titles=[e for e in plays if now-evtime(e)<=timedelta(days=30)]
        recent_slugs={next((x['content_slug'] for x in catalogue if x['title_id']==e.get('properties',{}).get('title_id')),None) for e in recent_titles}
        fresh=any(t.get('content_slug') in recent_slugs and False for t in catalogue) # retained for clarity; release rule below
        if any(t.get('release_date') and (now.date()-datetime.strptime(t['release_date'],'%Y-%m-%d').date()).days <=30 and (now.date()-datetime.strptime(t['release_date'],'%Y-%m-%d').date()).days >=0 for t in catalogue):
            candidates.append(('G08','try_new_release_7d','play_started',168,'Active subscriber; recent releases exist in catalogue.'))
        play_days={ist_day(e.get('received_at')) for e in plays if evtime(e) and now-evtime(e)<=timedelta(days=14)}
        if len(play_days)<=1: candidates.append(('G09','weekly_habit_14d','play_started',336,'Active subscriber with plays on at most one distinct IST day in last 14 days.'))
    last_open=max([evtime(e) for e in opens if evtime(e)] or [None])
    if last_open is None or now-last_open>=timedelta(days=14):
        candidates.append(('G12','return_after_absence_7d','play_started',168,'No app_open received in the preceding 14 days.'))
    if age_days is not None and 0 <= age_days <= 2:
        candidates.append(('G03','second_day_return_2d','play_started' if 'G03' in corrected_goals else 'app_open',48,('Signup within 2 days; corrected success signal uses play_started, not app_open.' if 'G03' in corrected_goals else 'Signup within 2 days; pre-correction rule version used app_open, subject to live rule correction.'))) 
    # Prioritize first-session activation, then completion/continuation, then lifecycle/retention.
    priority={'G01':0,'G02':1,'G07':2,'G04':3,'G05':4,'G06':5,'G08':6,'G09':7,'G12':8,'G03':9}
    candidates.sort(key=lambda x:priority.get(x[0],99))
    if not candidates: return None
    gid,name,signal,hours,reason=candidates[0]
    return {'id':gid,'name':name,'deadline':iso(now+timedelta(hours=hours)),'started_at':iso(now),'success_signal':signal,'window_hours':hours,'eligibility_reason':reason,'rule_version':goals_doc.get('version','unknown'),'resume_content_slugs':resume_slugs if gid=='G07' else []}

def title_available(t, at):
    start=dt(t.get('available_from')); end=dt(t.get('available_until'))
    return (not start or start<=at) and (not end or at<end)

def make_page(state, goal, catalogue, at, dialect, withdrawn):
    if not goal: return None,'No measurable eligible goal was supported by the available evidence.'
    if not dialect: return None,'No reliable app dialect is available; abstaining is safer than publishing the wrong variant.'
    facts=state['history']; genre_counts=Counter()
    last_slug=None; completed_ids={}
    for e in facts:
        props=e.get('properties',{}); tid=props.get('title_id'); t=state['cat_by_id'].get(tid)
        if t and event_name(e)=='play_started':
            for g in t.get('genres','').split('|'):
                if g: genre_counts[g]+=1
            last_slug=t['content_slug']
        if t and event_name(e)=='episode_completed': completed_ids.setdefault(t['content_slug'],set()).add(props.get('episode_id'))
    available=[t for t in catalogue if t['dialect']==dialect and title_available(t,at) and t['title_id'] not in withdrawn]
    # Ranking uses only catalogued metadata and observed genre affinity; descriptions are never executed as instructions.
    def score(t):
        gs=[g for g in t.get('genres','').split('|') if g]
        s=sum(genre_counts[g] for g in gs)
        if goal.get('id')=='G08' and t.get('release_date'):
            try:
                age=(at.date()-datetime.strptime(t['release_date'],'%Y-%m-%d').date()).days
                if 0<=age<=30: s+=100
            except ValueError: pass
        if goal.get('id')=='G07' and t.get('content_slug') in goal.get('resume_content_slugs',[]): s+=1000
        return s
    available.sort(key=lambda t:(-score(t),t.get('title_id','')))
    picked=[]; slugs=set()
    for t in available:
        slug=t.get('content_slug')
        if slug in slugs: continue
        picked.append(t); slugs.add(slug)
        if len(picked)>=8: break
    if len(picked)<3: return None,'Fewer than three available titles in the viewer app dialect; platform would drop the row.'
    hero=picked[0]; row_titles=picked[1:7]
    if len(row_titles)<3: row_titles=picked[:3]; hero=None
    row_type='next_episode' if goal.get('id')=='G07' else 'new_releases' if goal.get('id')=='G08' else 'genre' if genre_counts else 'popular_in_dialect'
    action={'type':'home_page','dialect':dialect,'hero_title_id':hero['title_id'] if hero else None,
            'rows':[{'row_type':row_type,'title_ids':[t['title_id'] for t in row_titles[:10]]}],
            'reason':'Eligible measurable goal; available catalogue variants match the current app dialect; independent checks follow.'}
    return action,action['reason']

def verify_action(action, state, trigger, arm, at, withdrawn, prior_message_days):
    checks={'passed':[],'failed':[]}
    if arm=='holdout': checks['failed'].append('holdout_zero_action')
    else: checks['passed'].append('agent_arm')
    if not action: checks['passed'].append('explicit_no_action')
    else:
        d=action['dialect']; byid=state['cat_by_id']; slugs=set(); valid=True
        for row in action.get('rows',[]):
            if len(row.get('title_ids',[]))<3: checks['failed'].append('homepage_row_below_minimum'); valid=False
            for tid in row.get('title_ids',[]):
                t=byid.get(tid)
                if not t: checks['failed'].append('unknown_title:'+tid); valid=False; continue
                if t['dialect']!=d: checks['failed'].append('wrong_dialect:'+tid); valid=False
                if not title_available(t,at) or tid in withdrawn: checks['failed'].append('unavailable_title:'+tid); valid=False
                if t['content_slug'] in slugs: checks['failed'].append('duplicate_content_slug:'+t['content_slug']); valid=False
                slugs.add(t['content_slug'])
        hero=byid.get(action.get('hero_title_id')) if action.get('hero_title_id') else None
        if action.get('hero_title_id') and (not hero or hero['dialect']!=d or not title_available(hero,at) or action['hero_title_id'] in withdrawn):
            checks['failed'].append('invalid_hero'); valid=False
        if valid: checks['passed'].append('dialect_availability_row_size_and_dedup')
    return checks

def run_pack_replay(pack_root, out_dir):
    root=Path(pack_root); out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    x=load_inputs(root); profiles=x['profiles']; history=x['history']; catalogue=x['catalogue']; cat_by_id=x['cat_by_id']; episodes=x['episodes']; arms=x['arms']
    triggers=sorted(x['triggers'],key=lambda e:str(e.get('deliver_at') or e.get('received_at') or ''))
    live=sorted(x['live'],key=lambda e:str(e.get('deliver_at') or e.get('received_at') or ''))
    controls=sorted(x['controls'],key=lambda e:str(e.get('at','')))
    live_i=0; control_i=0; withdrawn={}; corrected_goals=set(); dependency_windows=[]; decisions=[]; actions=[]; per_user_goal={}; actioned=set(); seen_trigger=set(); action_count_by_user_day=set(); duplicate_count=0
    live_by_user=defaultdict(list)
    for i,tr in enumerate(triggers,1):
        start_clock=time.perf_counter(); trigger_id=tr.get('event_id'); user=uid(tr); at=dt(tr.get('deliver_at') or tr.get('received_at'))
        if not user or not at: continue
        if trigger_id in seen_trigger:
            duplicate_count+=1
            decisions.append({'decision_id':f'D-{i:06d}','user_id':user,'trigger':{'event_id':trigger_id,'received_at':iso(at)},'goal':None,'action':'NO_ACTION','status':'ABSTAINED','no_action_reason':'Duplicate trigger event_id; idempotent replay.','checks':{'passed':['duplicate_trigger_dedup'],'failed':[]},'decided_in_ms':int((time.perf_counter()-start_clock)*1000)})
            continue
        seen_trigger.add(trigger_id)
        while live_i<len(live) and dt(live[live_i].get('deliver_at') or live[live_i].get('received_at'))<=at:
            le=live[live_i]; live_by_user[uid(le)].append(le); live_i+=1
        while control_i<len(controls) and dt(controls[control_i].get('at'))<=at:
            c=controls[control_i]
            if c.get('type')=='title_withdrawn': withdrawn[c['title_id']]=dt(c['at'])
            if c.get('type')=='goal_rule_corrected':
                gid=c.get('goal_id'); corrected_goals.add(gid)
                new_signal=(c.get('new_success') or {}).get('event')
                for active_goal in per_user_goal.values():
                    if active_goal and active_goal.get('id')==gid and dt(active_goal.get('deadline')) and dt(active_goal['deadline'])>dt(c.get('at')):
                        active_goal['success_signal']=new_signal or active_goal.get('success_signal')
                        active_goal['rule_correction']={'at':c.get('at'),'from':(c.get('old_success') or {}).get('event'),'to':new_signal,'applied_to_open_goal':True}
            if c.get('type') in ('dependency_unavailable','dependency_degraded'):
                dependency_windows.append({'dependency':c.get('dependency'),'type':c.get('type'),'start':c.get('at'),'until':c.get('until'),'detail':c.get('detail')})
            control_i+=1
        profile=profiles.get(user,{})
        # Event evidence is only available up to this trigger; historic warehouse events are bounded by server receipt time.
        hist=[e for e in history.get(user,[]) if evtime(e) and evtime(e)<=at]
        hist += [e for e in live_by_user.get(user,[]) if evtime(e) and evtime(e)<=at]
        hist=dedupe_events(hist)
        # app-open itself is not allowed to prove that a viewer was absent before this trigger.
        state={'history':hist,'cat_by_id':cat_by_id,'profile':profile}
        dialect,dialect_source,conflicts=dialect_for(tr,profile)
        if not dialect and hist:
            latest=max([e for e in hist if e.get('app_dialect')],key=lambda e:str(e.get('received_at','')),default=None)
            if latest: dialect=latest['app_dialect']; dialect_source='latest historical event app_dialect'
        arm=arms.get(user,'unknown')
        # A phone's event clock may be wrong; sent_at - occurred_at approximates offline buffering as used by the simulator.
        age_s=estimate_trigger_age_seconds(tr)
        goal=per_user_goal.get(user)
        if not goal and not (age_s is not None and age_s>600):
            # Goal assignment is computed for both randomized arms; holdout changes only whether an action may be published.
            goal=eligibility_goal(profile,hist,catalogue,episodes,at,x['goals'],corrected_goals); per_user_goal[user]=goal
        reason=''
        proposed=None
        if arm=='holdout': reason='Randomized holdout: policy prohibits every agent action.'
        elif age_s is not None and age_s>600: reason=f'Stale/offline-buffered trigger ({int(age_s)}s estimated phone-side lag); no action on a non-current visit.'
        elif user in actioned: reason='A compliant home page was already published for this viewer during this replay; avoid duplicate interventions.'
        else:
            proposed,reason=make_page(state,goal,catalogue,at,dialect,withdrawn)
        fault=x['faults'].get(trigger_id)
        mock_provider=ReplayFaultProvider(x['faults'])
        model_proposal=None
        if fault:
            try:
                model_proposal=mock_provider.propose(trigger_id)
            except TimeoutError:
                model_proposal={'fallback':'timeout'}
        active_dependencies=[w for w in dependency_windows if dt(w['start'])<=at and dt(w['until']) and at<dt(w['until'])]
        fault_note=None
        if fault:
            # Reproduce the supplied fault signal, but never accept its claims as evidence.
            fault_note={'fault':fault.get('fault'),'injected':True,'handled_safely':True,'proposal_type':type(model_proposal).__name__,'proposal_accepted_as_evidence':False}
            if fault.get('fault') in ('unsupported_claim','malformed_output','timeout'):
                reason += ' Mock model fault was observed; proposal ignored and deterministic evidence-based policy used.'
        for dep in active_dependencies:
            if dep['dependency']=='model_provider':
                reason += ' Model provider outage active; no model call is required by the deterministic policy.'
            elif dep['dependency']=='user_data_store':
                reason += ' Data-store degradation active; using the preloaded read-only local snapshot and conservative checks.'
        checks=verify_action(proposed,state,tr,arm,at,withdrawn,action_count_by_user_day)
        action='NO_ACTION'; action_obj=None
        if proposed and not checks['failed'] and arm=='agent':
            action='HOME_PAGE'
            action_obj={'action_id':f'A-{len(actions)+1:06d}','decision_id':f'D-{i:06d}','user_id':user,'trigger_event_id':trigger_id,
                        'type':'home_page','published_at':iso(at+timedelta(milliseconds=max(1,int((time.perf_counter()-start_clock)*1000)))),
                        'dialect':proposed['dialect'],'hero_title_id':proposed.get('hero_title_id'),'rows':proposed['rows']}
            actions.append(action_obj); actioned.add(user)
            checks['passed'].append('holdout_exclusion')
        else:
            if proposed and checks['failed']:
                reason='Independent verifier rejected proposed action: '+', '.join(checks['failed']); proposed=None
            if not reason: reason='No compliant action was available.'
        elapsed=int((time.perf_counter()-start_clock)*1000)
        goal_out=None
        if goal:
            goal_out={'id':goal['id'],'name':goal['name'],'started_at':goal['started_at'],'deadline':goal['deadline'],'success_signal':goal['success_signal'],'window_hours':goal['window_hours'],'eligibility_reason':goal['eligibility_reason'],'rule_version':goal['rule_version']}
        decision={'decision_id':f'D-{i:06d}','user_id':user,
          'trigger':{'event_id':trigger_id,'event':tr.get('event'),'received_at':iso(at),'event_age_s':age_s,'session_id':tr.get('session_id')},
          'goal':goal_out,'action':action,'dialect':{'used':dialect,'source':dialect_source,'conflicts':conflicts},
          'content':([tid for row in proposed['rows'] for tid in row['title_ids']] if proposed and action!='NO_ACTION' else []),
          'hero_title_id':proposed.get('hero_title_id') if proposed and action!='NO_ACTION' else None,
          'rows':proposed.get('rows',[]) if proposed and action!='NO_ACTION' else [],
          'confidence':0.72 if goal and proposed else 0.35 if goal else 0.15,
          'confidence_reason':'Heuristic confidence reflects explicit eligibility and independent catalogue checks; it is not a calibrated probability.',
          'evidence':[{'source':'profiles_snapshot.csv','fact':'signup/subscription/consent baseline','observed_at':profile.get('updated_at'),'freshness':'daily snapshot, potentially stale'},
                      {'source':'data/events.jsonl + replay/live_events.jsonl','fact':'viewer event history','freshness':'deduplicated and bounded by received_at at decision time'},
                      {'source':'data/catalogue.csv','fact':'dialect, availability and content_slug','freshness':'checked at publish time'}],
          'assumptions':[reason],'conflicts':conflicts,'checks':checks,'decided_in_ms':elapsed,'deadline':goal.get('deadline') if goal else None,
          'success_signal':goal.get('success_signal') if goal else None,'no_action_reason':reason if action=='NO_ACTION' else None,
          'model_fault':fault_note,'active_dependency_conditions':active_dependencies,'status':'PUBLISHED' if action!='NO_ACTION' else 'ABSTAINED'}
        decisions.append(decision)
        # Current trigger becomes history only after decision, so it cannot prove prior eligibility.
        live_by_user[user].append(tr)
    write_jsonl(out/'decisions.jsonl',decisions); write_jsonl(out/'actions.jsonl',actions)
    # Durable per-viewer state, facts and chosen goal are serialized for audit.
    state_dir=out/'viewer_state'; state_dir.mkdir(exist_ok=True)
    for user,goal in per_user_goal.items():
        prof=profiles.get(user,{})
        user_decisions=[d for d in decisions if d['user_id']==user]
        state={'user_id':user,'profile_snapshot':prof,'active_goal':goal,'decision_ids':[d['decision_id'] for d in user_decisions],
               'action_ids':[a['action_id'] for a in actions if a['user_id']==user], 'last_decision_at':user_decisions[-1]['trigger']['received_at'] if user_decisions else None}
        (state_dir/(user+'.json')).write_text(json.dumps(state,indent=2,default=str),encoding='utf-8')
    latency=[d.get('decided_in_ms',0) for d in decisions]
    lat_report={'decision_count':len(decisions),'trigger_count':len(triggers),'duplicate_triggers_dropped':duplicate_count,'published_actions':len(actions),
                'agent_arm_users':sum(1 for a in arms.values() if a=='agent'),'holdout_users':sum(1 for a in arms.values() if a=='holdout'),
                'max_processing_ms':max(latency,default=0),'p95_processing_ms':sorted(latency)[min(len(latency)-1,int(.95*(len(latency)-1)))] if latency else 0,
                'within_60_seconds':all(x<=60000 for x in latency),'model_fault_triggers':sum(1 for d in decisions if d.get('model_fault')),'control_dependency_windows':dependency_windows,
                'note':'published_at includes measured local decision processing time; all action publication times are generated from trigger deliver_at.'}
    json_dump(out/'latency_report.json',lat_report)
    return {'decisions':len(decisions),'actions':len(actions),'latency':lat_report,'goals_assigned':sum(1 for g in per_user_goal.values() if g)}

def judge_outcomes(pack_root, out_dir, sim_out_dir):
    root=Path(pack_root); out=Path(out_dir); sim=Path(sim_out_dir)
    decisions=read_jsonl(out/'decisions.jsonl'); events=read_jsonl(sim/'outcome_events.jsonl')
    catalogue=csv_rows(root/'data/catalogue.csv'); cat={t['title_id']:t for t in catalogue}
    first_goal={}
    for d in decisions:
        g=d.get('goal')
        if g and d['user_id'] not in first_goal: first_goal[d['user_id']]=g
    by_user=defaultdict(list)
    for e in events: by_user[uid(e)].append(e)
    simulation_horizon=max([evtime(e) for e in events if evtime(e)] or [datetime(2026,10,1,tzinfo=UTC)])
    outcomes=[]
    for user,g in first_goal.items():
        start=dt(g['started_at']); deadline=dt(g['deadline']); goal_id=g['id']; matching=[]
        for e in by_user.get(user,[]):
            t=evtime(e)
            if not t or not start<t<=deadline: continue
            name=event_name(e); props=e.get('properties',{})
            ok=False
            if goal_id=='G01': ok=name=='play_started'
            elif goal_id=='G02': ok=name=='episode_completed'
            elif goal_id=='G03':
                correction=dt('2026-10-01T08:30:00Z')
                effective_signal='play_started' if start<correction and deadline>correction else g.get('success_signal','play_started')
                ok=name==effective_signal and ist_day(t)!=ist_day(start)
            elif goal_id in ('G04','G05'): ok=name=='purchase_completed' and not true_bool(props.get('is_trial',False))
            elif goal_id=='G06': ok=name=='purchase_completed' and not true_bool(props.get('is_trial',False))
            elif goal_id=='G07':
                tid=props.get('title_id'); slug=cat.get(tid,{}).get('content_slug')
                ok=name=='play_started' and slug in g.get('resume_content_slugs',[])
            elif goal_id=='G08':
                title=cat.get(props.get('title_id'),{}); release=title.get('release_date')
                try: fresh=bool(release) and 0 <= (start.date()-datetime.strptime(release,'%Y-%m-%d').date()).days <= 30
                except ValueError: fresh=False
                ok=name=='play_started' and fresh
            elif goal_id=='G09': ok=name=='play_started'
            elif goal_id=='G12': ok=name=='play_started'
            if ok: matching.append(e)
        success=False
        if goal_id=='G09':
            days={ist_day(evtime(e)) for e in matching}
            success=len(days)>=3
        else: success=bool(matching)
        status='succeeded' if success else ('failed' if deadline <= simulation_horizon else 'inconclusive')
        outcomes.append({'user_id':user,'goal_id':goal_id,'goal_name':g.get('name'),'goal_started_at':g['started_at'],'deadline':g['deadline'],
                         'status':status,'success':success,'success_event_ids':[e.get('event_id') for e in matching],
                         'evidence_source':'simulator/outcome_events.jsonl','simulation_horizon_end':iso(simulation_horizon),'measurement_note':'Goal-specific signal checked only in its deadline window; G03 uses corrected play_started signal; goals whose deadlines extend beyond simulator coverage remain inconclusive.'})
    write_jsonl(out/'outcomes.jsonl',outcomes)
    arms={r['user_id']:r['arm'].lower() for r in csv_rows(root/'replay/arms.csv')}
    # Intention-to-treat on randomized arm among users assigned a measurable goal; no action remains in treatment denominator.
    result={}
    for arm in ('agent','holdout'):
        rows=[r for r in outcomes if arms.get(r['user_id'])==arm]
        result[arm]={'n':len(rows),'succeeded':sum(r['success'] for r in rows),'success_rate':sum(r['success'] for r in rows)/len(rows) if rows else 0.0,
                     'inconclusive':sum(r['status']=='inconclusive' for r in rows)}
    a=result['agent']['success_rate']; h=result['holdout']['success_rate']; uplift=a-h
    se=math.sqrt((a*(1-a)/result['agent']['n'] if result['agent']['n'] else 0)+(h*(1-h)/result['holdout']['n'] if result['holdout']['n'] else 0))
    report={'method':'intention-to-treat among viewers assigned a measurable goal; all assigned viewers retained in their randomized arm, including no-action viewers',
            'agent':result['agent'],'holdout':result['holdout'],'risk_difference':uplift,'risk_difference_percentage_points':100*uplift,
            'approx_95pct_ci':[uplift-1.96*se,uplift+1.96*se],
            'caveat':'This replay is one synthetic simulator run and only goal-assigned viewers are in this goal-specific estimate. Do not interpret as a production causal effect; inspect simulator policy problems and assignment balance.'}
    json_dump(out/'impact_report.json',report)
    lines=['# Replay impact report','',f"- Agent arm: {result['agent']['succeeded']}/{result['agent']['n']} goal-assigned viewers succeeded ({result['agent']['success_rate']:.1%}).",f"- Holdout arm: {result['holdout']['succeeded']}/{result['holdout']['n']} goal-assigned viewers succeeded ({result['holdout']['success_rate']:.1%}).",f"- Difference (agent − holdout): {uplift*100:.2f} percentage points.",f"- Approximate 95% CI: [{100*(uplift-1.96*se):.2f}, {100*(uplift+1.96*se):.2f}] percentage points.",'', '**Interpretation caution:** '+report['caveat'],'','## Why the pilot headline is not causal','The supplied pilot summary compares 217 served viewers with 3,674 other users, even though the assignment file contains randomized agent and holdout arms. Served status is post-randomization and strongly selected; users who received an action may differ in engagement, eligibility, or ability to be served. Use the randomized arm as the denominator (intention-to-treat), not served-versus-unserved.']
    (out/'impact_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report
