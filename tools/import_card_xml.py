"""Normalize a frozen exported CardDefs snapshot for planning and data review."""

from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hs_sim.card_xml import read_card_xml


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xml',type=Path,required=True)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Use a new output file; preserve old source snapshots')
    receipt=json.loads(args.receipt.read_text(encoding='utf-8'))
    expected=receipt['files']['CardDefs.xml']['sha256']
    with args.xml.open('rb') as f:before=hashlib.file_digest(f,'sha256').hexdigest()
    if before!=expected:raise ValueError('XML differs from its frozen source receipt')
    version=receipt['client_version']
    catalog=read_card_xml(args.xml,expected_build=int(version.rsplit('.',1)[1]))
    with args.xml.open('rb') as f:after=hashlib.file_digest(f,'sha256').hexdigest()
    if after!=before:raise ValueError('XML changed during normalization')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(catalog.cards,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'client_version':version,'records':len(catalog.cards),
        'collectible_marked':sum(r['collectible'] for r in catalog.cards),
        'formal_pool_complete':False,'source_sha256':before}))


if __name__=='__main__':main()
