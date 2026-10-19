import argparse, json, subprocess, sys
from pathlib import Path
from .replay import run_demo
from .real_replay import run_pack_replay, judge_outcomes

def main():
    p=argparse.ArgumentParser(description='One User, One Agent: real supplied-pack replay')
    p.add_argument('--demo',action='store_true',help='Run a synthetic smoke demo only; not assignment evidence')
    p.add_argument('--pack-root',default='.',help='Root folder containing data/, config/, replay/, simulator/, pilot/')
    p.add_argument('--out-dir',default='sample_run',help='Output directory')
    p.add_argument('--simulate',action='store_true',help='Run supplied outcome simulator and judge goal outcomes')
    p.add_argument('--seed',default='oua-practice',help='Deterministic simulator seed')
    a=p.parse_args()
    if a.demo:
        result=run_demo(a.out_dir)
    else:
        result=run_pack_replay(a.pack_root,a.out_dir)
        if a.simulate:
            sim_dir=Path(a.out_dir)/'simulator_output'
            cmd=[sys.executable,str(Path(a.pack_root)/'simulator/simulate_outcomes.py'),'--pack',str(Path(a.pack_root).resolve()),'--actions',str((Path(a.out_dir)/'actions.jsonl').resolve()),'--out',str(sim_dir.resolve()),'--seed',a.seed]
            subprocess.run(cmd,check=True)
            impact=judge_outcomes(a.pack_root,a.out_dir,sim_dir)
            result['impact_report']=impact
            # Include simulator quality/policy diagnostics in final report.
            sim_report=json.loads((sim_dir/'simulator_report.json').read_text(encoding='utf-8'))
            (Path(a.out_dir)/'simulator_quality_report.json').write_text(json.dumps({'counts':sim_report.get('counts',{}),'policy_problem_count':sim_report.get('policy_problem_count',0),'policy_problems_sample':sim_report.get('policy_problems',[])[:50]},indent=2),encoding='utf-8')
            (Path(a.out_dir)/'final_report.md').write_text(
                '# One User, One Agent — replay summary\n\n'
                f"- Decisions: {result['decisions']}\n- Published home-page actions: {result['actions']}\n"
                f"- Measurable goals assigned: {result['goals_assigned']}\n"
                f"- Max local processing time: {result['latency']['max_processing_ms']} ms\n"
                f"- Simulator policy problem count: {sim_report.get('policy_problem_count',0)}\n\n"
                'See `decisions.jsonl`, `actions.jsonl`, `outcomes.jsonl`, `latency_report.json`, `impact_report.md`, '
                '`simulator_quality_report.json`, and `viewer_state/` for audit details.\n\n'
                '**Caution:** this is one synthetic simulator seed; its result is not a production causal claim.\n',encoding='utf-8')
    print(json.dumps(result,indent=2,default=str))
if __name__=='__main__': main()
