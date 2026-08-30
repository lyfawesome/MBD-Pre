#!/usr/bin/env python3
"""Recover a completed classification report when only STEP export validation failed."""
import argparse, csv, json
from collections import defaultdict
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('run',type=Path); a=ap.parse_args(); d=a.run
    failed=d/'export_failure_workflow_manifest.json'
    if not failed.is_file(): raise SystemExit('missing export_failure_workflow_manifest.json')
    manifest=json.loads(failed.read_text()); precision=json.loads((d/'precision_report.json').read_text())
    with (d/'parts.csv').open(encoding='utf-8-sig') as f: parts=list(csv.DictReader(f))
    with (d/'similarities.csv').open(encoding='utf-8-sig') as f: sims=list(csv.DictReader(f))
    groups=defaultdict(list)
    for row in parts: groups[int(row['group'])].append(int(row['part_index']))
    sim={(int(r['part_a']),int(r['part_b'])):float(r['similarity']) for r in sims}
    summaries=[]
    for gid, ids in sorted(groups.items()):
        vals=[sim[(min(x,y),max(x,y))] for i,x in enumerate(ids) for y in ids[:i]]
        summaries.append({'group':gid,'part_count':len(ids),'parts':ids,
                          'minimum_internal_similarity':min(vals) if vals else 1.0,
                          'mean_internal_similarity':sum(vals)/len(vals) if vals else 1.0})
    report={'version':'4.0.0-recovered','method':'boolean-classification-with-export-warning',
            'source':manifest['config']['step_file'],'source_sha256':manifest['source_sha256'],
            'config':manifest['config'],'part_count':len(parts),
            'candidate_group_count':precision['candidate_group_count'],
            'group_count':precision['final_group_count'],'groups':summaries,
            'precision':{k:v for k,v in precision.items() if k!='pairs'},
            'data_quality':json.loads((d/'data_quality.json').read_text())}
    (d/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    manifest['status']='completed_with_export_warning'
    manifest['recovery_note']='Classification completed; grouped STEP roundtrip gate failed and is preserved.'
    (d/'workflow_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(f"Recovered {d.name}: {len(parts)} solids -> {len(groups)} groups")
if __name__=='__main__': main()
